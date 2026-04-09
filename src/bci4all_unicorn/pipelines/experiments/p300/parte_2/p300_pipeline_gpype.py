"""
Nome do ficheiro:
    p300_pipeline_gpype.py

Descrição:
    Camada 3 do protótipo P300.

    Este ficheiro implementa uma pipeline em gpype responsável por:
    - adquirir ou simular sinal EEG
    - filtrar esse sinal
    - receber continuamente dois canais de eventos por UDP
    - receber um canal de controlo para iniciar/parar gravação CSV
    - anexar os canais Ch09 e Ch10 ao EEG como sinais contínuos
    - mostrar o EEG num scope
    - mostrar os canais de evento noutro scope
    - gravar tudo num único CSV

Convenção dos canais:
    Ch01..Ch08 -> EEG
    Ch09       -> código do estímulo (0..9)
    Ch10       -> trigger binário (0/1)

Controlo:
    Porta 12347:
        0 = idle
        1 = START_CSV
        2 = STOP_CSV
"""

# Biblioteca para escrever ficheiros CSV
import csv

# Biblioteca para comunicação por sockets UDP
import socket

# Biblioteca para correr listeners em paralelo ao pipeline
import threading

# dataclass simplifica a criação de classes de armazenamento de estado
from dataclasses import dataclass, field

# datetime e timedelta servem para gerar timestamps por amostra no CSV
from datetime import datetime, timedelta

# NumPy para manipulação matricial dos blocos de sinal
import numpy as np

# gpype / g.Pype para criação da pipeline BCI
import gpype as gp

# IONode é a classe base para nós customizados de entrada/saída em gpype
from gpype.backend.core.io_node import IONode

# Constants fornece chaves e portas padrão utilizadas internamente pelo gpype
from gpype.common.constants import Constants


# Constantes internas do gpype:
# PORT_IN  -> porta de entrada de um nó
# PORT_OUT -> porta de saída de um nó
PORT_IN = Constants.Defaults.PORT_IN
PORT_OUT = Constants.Defaults.PORT_OUT


# Taxa de amostragem do sistema (250 Hz = 250 amostras por segundo)
SAMPLING_RATE = 250

# Número de canais EEG reais do Unicorn Core-8
EEG_CHANNEL_COUNT = 8


# Porta UDP para receber o código do estímulo (Ch09)
UDP_PORT_CODE = 12345

# Porta UDP para receber o trigger binário target/non-target (Ch10)
UDP_PORT_TRIGGER = 12346

# Porta UDP para receber comandos de controlo de gravação CSV
UDP_PORT_CONTROL = 12347


# Se True, usa um gerador sintético em vez do amplificador real
# Útil para testes quando não há hardware ligado
USE_GENERATOR = True

# Nome do ficheiro CSV gerado
CSV_FILE = "p300_full_output.csv"


@dataclass
class SharedEventChannels:
    """
    Estrutura partilhada entre threads.

    Esta classe guarda os dois valores mais recentes recebidos por UDP:
    - stim_code    -> código do estímulo (vai para Ch09)
    - stim_trigger -> trigger binário (vai para Ch10)

    O lock garante acesso seguro quando várias threads lêem/escrevem
    ao mesmo tempo nestas variáveis.
    """

    # Último valor recebido para o código do estímulo
    stim_code: float = 0.0

    # Último valor recebido para o trigger binário
    stim_trigger: float = 0.0

    # Lock para sincronização entre threads
    lock: threading.Lock = field(default_factory=threading.Lock)


class ContinuousUDPValueListener(threading.Thread):
    """
    Thread que escuta continuamente uma porta UDP e guarda o último valor recebido.

    Exemplo de uso:
        - uma instância para o stim_code
        - outra instância para o stim_trigger

    Sempre que chega um novo valor UDP:
        1. converte o conteúdo recebido em float
        2. escreve esse valor no campo apropriado do objeto shared_state
    """

    def __init__(self, shared_state, field_name, host="127.0.0.1", port=12345):
        # Inicializa a thread como daemon=True para encerrar com o programa
        super().__init__(daemon=True)

        # Referência ao objeto partilhado onde os valores serão guardados
        self.shared_state = shared_state

        # Nome do atributo a atualizar no shared_state
        # Ex.: "stim_code" ou "stim_trigger"
        self.field_name = str(field_name)

        # Host local onde o socket UDP vai escutar
        self.host = str(host)

        # Porta UDP a escutar
        self.port = int(port)

        # Flag de execução da thread
        self.running = True

        # Cria socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Permite reutilizar rapidamente a porta caso a aplicação reinicie
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Associa o socket ao host e porta indicados
        self.sock.bind((self.host, self.port))

        # Define timeout para que recvfrom não bloqueie indefinidamente
        self.sock.settimeout(0.5)

    def stop(self):
        """
        Pede paragem da thread e fecha o socket.
        """
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass

    def run(self):
        """
        Corpo principal da thread.

        Enquanto running=True:
            - espera por mensagens UDP
            - tenta converter o conteúdo para float
            - se conseguir, atualiza o campo correspondente no shared_state
        """
        while self.running:
            try:
                # Recebe até 1024 bytes do socket
                data, _ = self.sock.recvfrom(1024)
            except socket.timeout:
                # Timeout normal: continua à espera
                continue
            except OSError:
                # Socket fechado: sai da thread
                break
            except Exception:
                # Qualquer outro erro: termina
                break

            try:
                # Converte bytes recebidos em string UTF-8 e depois em float
                value = float(data.decode("utf-8").strip())
            except Exception:
                # Se a conversão falhar, ignora a mensagem
                continue

            # Atualização protegida por lock
            with self.shared_state.lock:
                setattr(self.shared_state, self.field_name, value)


# Import repetido no código original.
# Não é estritamente necessário porque já foi importado acima,
# mas foi mantido para preservar a estrutura original.
from gpype.common.constants import Constants


class AppendLatestEventChannels(IONode):
    """
    Nó customizado gpype que recebe blocos EEG e acrescenta 2 canais extra:
        - Ch09 = último stim_code recebido
        - Ch10 = último stim_trigger recebido

    A ideia é transformar os eventos UDP em canais contínuos com formato igual
    ao EEG, para poder visualizar e gravar tudo junto.

    Entrada:
        EEG com 8 canais

    Saída:
        EEG com 10 canais:
            Ch01..Ch08 = EEG
            Ch09       = stim_code
            Ch10       = stim_trigger
    """

    def __init__(self, shared_events, eeg_channel_count=8):
        # target=None porque este nó não precisa de widget nem backend especial
        super().__init__(target=None)

        # Referência ao estado partilhado com os eventos mais recentes
        self.shared_events = shared_events

        # Número de canais EEG de entrada esperados
        self.eeg_channel_count = int(eeg_channel_count)

    def setup(self, data, port_context_in):
        """
        Método chamado na fase de setup do nó.

        Aqui alteramos o contexto de saída para informar o restante pipeline
        de que a saída já não terá 8 canais, mas sim 10.
        """
        # Setup base do IONode
        port_context_out = super().setup(data, port_context_in)

        # Define explicitamente que a saída terá EEG_CHANNEL_COUNT + 2 canais
        port_context_out[PORT_OUT][Constants.Keys.CHANNEL_COUNT] = self.eeg_channel_count + 2

        return port_context_out

    def _normalize_to_samples_channels(self, arr):
        """
        Normaliza a forma do array para o formato:
            [n_samples, n_channels]

        O gpype por vezes pode fornecer dados em diferentes orientações,
        então este método tenta corrigir isso.

        Casos tratados:
            - vetor 1D
            - matriz [samples, channels]
            - matriz [channels, samples]
        """
        # Garante conversão para array NumPy
        arr = np.asarray(arr)

        # Se vier um vetor 1D
        if arr.ndim == 1:
            # Se o tamanho corresponder ao número de canais,
            # assume-se que é uma única amostra com vários canais
            if arr.size == self.eeg_channel_count:
                arr = arr.reshape(1, -1)
            else:
                # Caso contrário, assume-se um único canal com várias amostras
                arr = arr.reshape(-1, 1)

        # Se não ficou 2D, formato inválido
        if arr.ndim != 2:
            return None

        # Caso normal: colunas = canais
        if arr.shape[1] == self.eeg_channel_count:
            return arr

        # Caso invertido: linhas = canais -> transpõe
        if arr.shape[0] == self.eeg_channel_count:
            return arr.T

        # Se nada bate certo, devolve None
        return None

    def step(self, data):
        """
        Executado em cada bloco de dados do pipeline.

        Fluxo:
            1. lê EEG
            2. normaliza a forma
            3. lê últimos valores de evento
            4. cria duas colunas constantes com esses valores
            5. junta tudo horizontalmente
            6. devolve bloco com 10 canais
        """
        # Verifica se existe entrada na porta padrão
        if PORT_IN not in data:
            return None

        # Normaliza o EEG para [samples, channels]
        eeg = self._normalize_to_samples_channels(data[PORT_IN])
        if eeg is None:
            return None

        # Lê os últimos valores partilhados com proteção por lock
        with self.shared_events.lock:
            stim_code = float(self.shared_events.stim_code)
            stim_trigger = float(self.shared_events.stim_trigger)

        # Número de amostras no bloco atual
        n_samples = eeg.shape[0]

        # Cria uma coluna constante com o código do estímulo repetido
        # para todas as amostras do bloco
        code_col = np.full((n_samples, 1), stim_code, dtype=float)

        # Cria uma coluna constante com o trigger repetido
        trigger_col = np.full((n_samples, 1), stim_trigger, dtype=float)

        # Junta EEG + Ch09 + Ch10
        merged = np.hstack((eeg, code_col, trigger_col))

        # Devolve na porta de saída do nó
        return {PORT_OUT: merged}


class CsvWriterWithTimestamp(IONode):
    """
    Nó customizado para gravar um CSV com colunas:
        Time, Timestamp, Ch01..Ch10

    Comportamento:
        - Só começa a gravar quando recebe START_CSV
        - Pára quando recebe STOP_CSV

    Isto permite que o CSV contenha apenas a parte útil do ensaio.
    """

    def __init__(self, file_name: str, sampling_rate: int, channel_count: int = 10):
        # Nó sem target específico
        super().__init__(target=None)

        # Nome do ficheiro a gravar
        self.file_name = str(file_name)

        # Taxa de amostragem usada para calcular o tempo de cada amostra
        self.sampling_rate = int(sampling_rate)

        # Número total de canais a gravar
        self.channel_count = int(channel_count)

        # Índice global da amostra atual no ficheiro
        self.sample_idx = 0

        # Instante de início da gravação
        self.start_dt = None

        # File handle do CSV
        self._fh = None

        # Objeto csv.writer
        self._writer = None

        # True enquanto deve escrever amostras
        self.is_recording = False

        # True se o ficheiro estiver aberto
        self.file_opened = False

    def _open_file(self):
        """
        Cria/abre o CSV e escreve o cabeçalho.
        Reinicia também o contador temporal.
        """
        # Define o instante real de início da gravação
        self.start_dt = datetime.now()

        # Reinicia o índice de amostras
        self.sample_idx = 0

        # Abre o ficheiro em modo escrita
        self._fh = open(self.file_name, "w", newline="", encoding="utf-8")

        # Cria writer CSV
        self._writer = csv.writer(self._fh)

        # Escreve cabeçalho:
        # Time -> tempo relativo em segundos
        # Timestamp -> data/hora absoluta
        # Ch01..Ch10 -> canais
        self._writer.writerow(
            ["Time", "Timestamp"] + [f"Ch{i:02d}" for i in range(1, self.channel_count + 1)]
        )

        # Marca estado do ficheiro como aberto
        self.file_opened = True

        # Ativa gravação
        self.is_recording = True

        print(f"[INFO] CSV iniciado: {self.file_name}")

    def _close_file(self):
        """
        Fecha o ficheiro CSV e atualiza o estado interno.
        """
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass

        # Limpa referências
        self._fh = None
        self._writer = None

        # Atualiza flags
        self.file_opened = False
        self.is_recording = False

        print("[INFO] CSV terminado.")

    def _normalize_to_samples_channels(self, arr):
        """
        Garante formato [n_samples, n_channels] antes de gravar.
        """
        arr = np.asarray(arr)

        if arr.ndim == 1:
            if arr.size == self.channel_count:
                arr = arr.reshape(1, -1)
            else:
                arr = arr.reshape(-1, 1)

        if arr.ndim != 2:
            return None

        if arr.shape[1] == self.channel_count:
            return arr

        if arr.shape[0] == self.channel_count:
            return arr.T

        return None

    def step(self, data):
        """
        Executado para cada bloco de dados que chega ao writer.

        Só escreve no CSV se:
            - houver dados em PORT_IN
            - o array tiver a forma certa
            - a gravação estiver ativa
        """
        # Se não existir entrada, não faz nada
        if PORT_IN not in data:
            return

        # Normaliza os dados
        arr = self._normalize_to_samples_channels(data[PORT_IN])
        if arr is None:
            return

        # Se não estiver em modo de gravação, ignora o bloco
        if not self.is_recording:
            return

        # Percorre amostra a amostra dentro do bloco
        for row in arr:
            # Tempo relativo em segundos desde o início do CSV
            time_s = self.sample_idx / self.sampling_rate

            # Timestamp absoluto calculado a partir do instante inicial
            ts = self.start_dt + timedelta(seconds=time_s)

            # Formatação do timestamp em string
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")

            # Escreve uma linha:
            # tempo relativo + timestamp absoluto + valores de canais
            self._writer.writerow(
                [f"{time_s:.3f}", ts_str] + [f"{float(v):.6f}" for v in row]
            )

            # Incrementa índice global de amostra
            self.sample_idx += 1

        # Força escrita imediata no disco
        if self._fh is not None:
            self._fh.flush()

    def start_recording(self):
        """
        Inicia gravação.

        Se o ficheiro ainda não existe:
            - cria o ficheiro
        Caso já exista:
            - apenas volta a ativar escrita
        """
        if not self.file_opened:
            self._open_file()
        else:
            self.is_recording = True

    def stop_recording(self):
        """
        Termina a gravação e fecha o ficheiro.
        """
        if self.file_opened:
            self._close_file()

    def __del__(self):
        """
        Segurança adicional:
        tenta fechar o ficheiro quando o objeto for destruído.
        """
        try:
            self._close_file()
        except Exception:
            pass


class RecordingControlListener(threading.Thread):
    """
    Thread que escuta comandos de controlo por UDP.

    Comandos aceites:
        1 -> START_CSV
        2 -> STOP_CSV

    Estes comandos são enviados pelo controller do paradigma.
    """

    def __init__(self, writer, host="127.0.0.1", port=12347):
        # daemon=True para terminar automaticamente com a app
        super().__init__(daemon=True)

        # Referência ao writer que será controlado
        self.writer = writer

        # Host e porta de escuta
        self.host = str(host)
        self.port = int(port)

        # Flag de execução
        self.running = True

        # Criação do socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Permite reuso da porta
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind à porta de controlo
        self.sock.bind((self.host, self.port))

        # Timeout para evitar bloqueio infinito
        self.sock.settimeout(0.5)

    def stop(self):
        """
        Pára a thread e fecha o socket.
        """
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass

    def run(self):
        """
        Loop principal da thread:
            - recebe mensagens UDP
            - converte em inteiro
            - executa ação no writer
        """
        while self.running:
            try:
                data, _ = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                break

            try:
                # Aceita tanto "1" como "1.0", por isso usa float -> int
                cmd = int(float(data.decode("utf-8").strip()))
            except Exception:
                continue

            # Interpretação dos comandos
            if cmd == 1:
                self.writer.start_recording()
            elif cmd == 2:
                self.writer.stop_recording()


def main():
    """
    Função principal.

    Monta toda a aplicação:
        - cria app e pipeline gpype
        - escolhe fonte EEG
        - cria filtros
        - cria listeners UDP
        - cria nó que acrescenta Ch09/Ch10
        - cria writer CSV
        - cria scopes
        - liga tudo na pipeline
        - arranca execução
    """

    # Cria a aplicação principal gpype (UI)
    app = gp.MainApp()

    # Cria a pipeline de processamento
    pipeline = gp.Pipeline()

    # Escolha da fonte EEG:
    # - gerador sintético para testes
    # - BCICore8 para aquisição real
    if USE_GENERATOR:
        amp = gp.Generator(
            sampling_rate=SAMPLING_RATE,      # 250 Hz
            channel_count=EEG_CHANNEL_COUNT,  # 8 canais
            signal_frequency=10,              # senoide a 10 Hz
            signal_amplitude=15,              # amplitude do sinal útil
            signal_shape="sine",              # forma do sinal
            noise_amplitude=10,               # ruído adicional
        )
        print("[INFO] Fonte EEG: Generator")
    else:
        amp = gp.BCICore8()
        print("[INFO] Fonte EEG: BCICore8")

    # Filtro passa-banda para manter apenas frequências EEG relevantes
    bandpass = gp.Bandpass(f_lo=1, f_hi=30)

    # Notch para remover ruído da rede elétrica a 50 Hz
    notch50 = gp.Bandstop(f_lo=48, f_hi=52)

    # Notch para remover possível componente a 60 Hz
    notch60 = gp.Bandstop(f_lo=58, f_hi=62)

    # Estado partilhado com os eventos mais recentes
    shared_events = SharedEventChannels()

    # Listener para receber continuamente o código do estímulo (Ch09)
    code_listener = ContinuousUDPValueListener(
        shared_state=shared_events,
        field_name="stim_code",
        host="127.0.0.1",
        port=UDP_PORT_CODE,
    )

    # Listener para receber continuamente o trigger binário (Ch10)
    trigger_listener = ContinuousUDPValueListener(
        shared_state=shared_events,
        field_name="stim_trigger",
        host="127.0.0.1",
        port=UDP_PORT_TRIGGER,
    )

    # Nó que acrescenta Ch09 e Ch10 ao sinal EEG
    merge_events = AppendLatestEventChannels(
        shared_events=shared_events,
        eeg_channel_count=EEG_CHANNEL_COUNT,
    )

    # Writer CSV final
    writer = CsvWriterWithTimestamp(
        file_name=CSV_FILE,
        sampling_rate=SAMPLING_RATE,
        channel_count=10,  # 8 EEG + 2 eventos
    )

    # Listener para iniciar/parar gravação do CSV
    control_listener = RecordingControlListener(
        writer=writer,
        host="127.0.0.1",
        port=UDP_PORT_CONTROL,
    )

    # Scope para mostrar apenas EEG:
    # hidden_channels=[8, 9] esconde os índices 8 e 9,
    # ou seja, Ch09 e Ch10 (indexação começa em 0)
    scope_eeg = gp.TimeSeriesScope(
        amplitude_limit=50,
        time_window=10,
        hidden_channels=[8, 9],
    )

    # Scope para mostrar apenas os canais de evento:
    # esconde os 8 primeiros canais EEG
    scope_events = gp.TimeSeriesScope(
        amplitude_limit=12,
        time_window=10,
        hidden_channels=[0, 1, 2, 3, 4, 5, 6, 7],
    )

    # Arranca as threads de escuta UDP antes de iniciar pipeline
    code_listener.start()
    trigger_listener.start()
    control_listener.start()

    # Ligações da pipeline:
    # fonte -> bandpass -> notch50 -> notch60 -> merge_events
    pipeline.connect(amp, bandpass)
    pipeline.connect(bandpass, notch50)
    pipeline.connect(notch50, notch60)
    pipeline.connect(notch60, merge_events)

    # A saída do merge_events alimenta:
    # - scope EEG
    # - scope de eventos
    # - writer CSV
    pipeline.connect(merge_events, scope_eeg)
    pipeline.connect(merge_events, scope_events)
    pipeline.connect(merge_events, writer)

    # Adiciona widgets à app
    app.add_widget(scope_eeg)
    app.add_widget(scope_events)

    # Informação de arranque no terminal
    print("[INFO] Pipeline pronta.")
    print(f"[INFO] Porta Ch09 (stim_code): {UDP_PORT_CODE}")
    print(f"[INFO] Porta Ch10 (stim_trigger): {UDP_PORT_TRIGGER}")
    print(f"[INFO] Porta controlo CSV: {UDP_PORT_CONTROL}")
    print("[INFO] Ch09 = 0..9 (sinal contínuo)")
    print("[INFO] Ch10 = 0/1 (sinal contínuo)")
    print("[INFO] CSV só será criado após START_CSV vindo do controller.")

    try:
        # Inicia processamento da pipeline
        pipeline.start()

        # Inicia loop gráfico / aplicação
        app.run()
    finally:
        # Garante paragem limpa mesmo se houver erro ou fecho da app
        pipeline.stop()

        # Pede paragem das threads
        control_listener.stop()
        code_listener.stop()
        trigger_listener.stop()

        # Aguarda um pouco pelo encerramento das threads
        control_listener.join(timeout=1.0)
        code_listener.join(timeout=1.0)
        trigger_listener.join(timeout=1.0)


# Garante que main() só corre se este ficheiro for executado diretamente
if __name__ == "__main__":
    main()