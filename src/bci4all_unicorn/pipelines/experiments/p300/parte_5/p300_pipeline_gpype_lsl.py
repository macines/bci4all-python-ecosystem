"""
Pipeline P300 com leitura de stream LSL contínuo de eventos.

Streams LSL:
- P300_Events  -> contínuo, 2 canais [code, trigger]
- P300_Control -> irregular, START_CSV / STOP_CSV

Saída:
- EEG 8 canais + Ch09(code) + Ch10(trigger)

Notas:
- O pipeline recebe o EEG, junta-lhe os 2 canais de eventos contínuos
  e apresenta o resultado em dois scopes:
    1) scope EEG
    2) scope de eventos
- O CSV é guardado em formato transposto.
- A lógica funcional foi mantida.
- Foi apenas acrescentada uma função para distinguir os títulos das
  janelas dos scopes e melhorada a documentação/comentários.

Clock único LSL:
- Todos os timestamps do CSV são derivados de local_clock(), o mesmo
  relógio usado pelo controller para carimbar os eventos LSL.
- No início de cada gravação (START_CSV) calcula-se uma única vez o
  offset entre local_clock() e datetime.now(), guardado em lsl_epoch.
- Cada amostra recebe: timestamp_absoluto = lsl_epoch + local_clock()
  no momento em que é processada pelo step().
- Isto elimina a deriva acumulada do método anterior (sample_idx / fs)
  e garante que eventos LSL e amostras EEG partilham o mesmo referencial
  temporal.
"""

# ---------------------------------------------------------
# Imports standard e utilitários
# ---------------------------------------------------------
# csv        -> escrita do ficheiro CSV final
# os         -> leitura de variáveis de ambiente
# threading  -> execução concorrente dos listeners LSL
# datetime   -> construção de timestamps absolutos para o CSV
# pathlib    -> manipulação robusta de paths e diretórios
import csv
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------
# Imports científicos / framework experimental
# ---------------------------------------------------------
# numpy  -> manipulação matricial dos blocos de sinal
# gpype  -> framework de processamento em pipeline
# pylsl  -> receção de streams LSL
# PySide6 -> suporte Qt para aplicação e timers
import numpy as np
import gpype as gp
from pylsl import resolve_byprop, StreamInlet, local_clock
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------
# Imports internos do gpype
# ---------------------------------------------------------
# IONode     -> base para nós personalizados do pipeline
# Constants  -> constantes de contexto e portos do gpype
from gpype.backend.core.io_node import IONode
from gpype.common.constants import Constants

# ---------------------------------------------------------
# Portos padrão de comunicação entre nós do gpype
# ---------------------------------------------------------
# PORT_IN  -> porto de entrada esperado nos nós
# PORT_OUT -> porto de saída produzido pelos nós
PORT_IN = Constants.Defaults.PORT_IN
PORT_OUT = Constants.Defaults.PORT_OUT

# ---------------------------------------------------------
# Parâmetros estruturais do pipeline
# ---------------------------------------------------------
# SAMPLING_RATE      -> frequência de amostragem do EEG
# EEG_CHANNEL_COUNT  -> número de canais EEG
# EVENT_CHANNEL_COUNT-> número de canais adicionais de evento
# TOTAL_CHANNEL_COUNT-> total de canais do fluxo final
SAMPLING_RATE = 250
EEG_CHANNEL_COUNT = 8
EVENT_CHANNEL_COUNT = 2
TOTAL_CHANNEL_COUNT = EEG_CHANNEL_COUNT + EVENT_CHANNEL_COUNT

# Nome por defeito do CSV caso não seja especificado externamente
DEFAULT_CSV_FILE = "p300_full_output_lsl.csv"

# Se True, usa gerador sintético de sinal.
# Se False, usa o dispositivo real BCICore8.
USE_GENERATOR = False


def resolve_output_file():
    """
    Resolve o ficheiro de saída do CSV.

    Prioridade:
    1) variável de ambiente BCI4ALL_OUTPUT_FILE
    2) fallback local DEFAULT_CSV_FILE

    Esta função desacopla o controller do pipeline:
    o controller pode preparar o nome final do ficheiro e o pipeline
    limita-se a consumi-lo, mantendo a sua lógica interna simples.
    """
    env_output = os.environ.get("BCI4ALL_OUTPUT_FILE", "").strip()

    if env_output:
        output_path = Path(env_output)

        # Garante que a diretoria existe antes de tentar escrever o ficheiro
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return str(output_path)

    return DEFAULT_CSV_FILE


class SharedEventBuffer:
    """
    Estrutura simples de estado partilhado entre threads.

    Esta classe funciona como uma pequena memória partilhada que guarda
    continuamente o estado mais recente do stream P300_Events.

    Campos:
    - lock:
        mecanismo de exclusão mútua para evitar condições de corrida
        entre leitura e escrita concorrentes.
    - current_code:
        valor atual do canal de código do estímulo.
    - current_trigger:
        valor atual do canal de trigger (tipicamente target/non-target).
    - current_lsl_ts:
        timestamp LSL (local_clock) da última amostra recebida.
        Permite rastrear quando cada evento chegou no referencial LSL.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.current_code = 0.0
        self.current_trigger = 0.0
        self.current_lsl_ts = 0.0


class ContinuousEventListener(threading.Thread):
    """
    Thread que lê o stream contínuo P300_Events.

    O stream esperado possui 2 canais:
    - canal 1 -> code
    - canal 2 -> trigger

    Finalidade:
    - manter atualizado o estado mais recente dos eventos;
    - disponibilizar esse estado ao nó de fusão EEG+eventos.

    Estratégia:
    - tenta localizar o stream pelo nome;
    - se ainda não estiver disponível, continua a tentar;
    - quando recebe uma amostra válida, atualiza o SharedEventBuffer.
    """

    def __init__(self, shared_state, stream_name="P300_Events"):
        super().__init__(daemon=True)

        # shared_state é a instância de SharedEventBuffer usada por este listener
        self.shared_state = shared_state

        # stream_name define o nome do stream LSL a procurar
        self.stream_name = str(stream_name)

        # running controla o ciclo de vida da thread
        self.running = True

        # inlet será preenchido apenas quando o stream for encontrado
        self.inlet = None

    def stop(self):
        """Sinaliza à thread que deve terminar."""
        self.running = False

    def run(self):
        """
        Loop principal da thread.

        Enquanto running=True:
        - tenta ligar ao stream, caso ainda não exista inlet;
        - lê amostras do stream;
        - atualiza o estado partilhado;
        - em caso de falha, volta ao estado de procura.
        """
        while self.running:
            try:
                # Se ainda não houver inlet ativo, tenta descobrir o stream LSL
                if self.inlet is None:
                    print(f"[INFO] À procura do stream LSL '{self.stream_name}'...")
                    streams = resolve_byprop("name", self.stream_name, timeout=2)

                    # Se não encontrar streams, recomeça o ciclo
                    if not streams:
                        continue

                    # Liga ao primeiro stream encontrado com esse nome
                    self.inlet = StreamInlet(streams[0], max_buflen=5)
                    print(f"[INFO] Stream LSL '{self.stream_name}' ligado.")

                # Tenta obter uma amostra do stream.
                # pull_sample devolve (sample, timestamp) onde timestamp
                # é o local_clock() do momento em que a amostra foi publicada.
                sample, lsl_ts = self.inlet.pull_sample(timeout=0.2)

                if sample is None:
                    continue

                # Garante que existem pelo menos 2 canais como esperado
                if len(sample) < 2:
                    continue

                code = float(sample[0])
                trigger = float(sample[1])

                # Atualiza o estado partilhado de forma protegida por lock.
                # lsl_ts é o timestamp LSL real da amostra — usado pelo writer
                # para garantir que todos os timestamps ficam no mesmo relógio.
                with self.shared_state.lock:
                    self.shared_state.current_code = code
                    self.shared_state.current_trigger = trigger
                    self.shared_state.current_lsl_ts = float(lsl_ts) if lsl_ts else local_clock()

            except Exception as e:
                # Em caso de erro, invalida a ligação atual e tenta novamente
                print(f"[WARN] ContinuousEventListener perdeu ligação: {e}")
                self.inlet = None


class CsvWriterWithTimestamp(IONode):
    """
    Nó de escrita de CSV em formato transposto.

    O formato transposto significa que:
    - cada linha representa uma variável/canal;
    - cada coluna subsequente representa uma amostra temporal.

    Estrutura final:
        Time,      t1,   t2,   t3,   ...   <- segundos LSL relativos ao início
        Timestamp, ts1,  ts2,  ts3,  ...   <- datetime absoluto (derivado do LSL)
        Ch01,      v1,   v2,   v3,   ...
        ...
        Ch10,      v1,   v2,   v3,   ...

    Clock único LSL:
    - Em start_recording() calcula-se UMA ÚNICA VEZ o offset entre
      local_clock() e datetime.now(). Este offset (lsl_epoch) é estável
      durante toda a sessão.
    - Em cada step(), chama-se local_clock() para obter o tempo real da
      amostra. O timestamp absoluto é: lsl_epoch + timedelta(seconds=lsl_ts).
    - O tempo relativo no CSV é: lsl_ts - lsl_t0  (segundos desde START_CSV).
    - Desta forma, eventos LSL e amostras EEG partilham exactamente o
      mesmo referencial temporal, sem deriva acumulada.

    Opção de implementação:
    - os dados são acumulados em memória ao longo da gravação;
    - o ficheiro é escrito apenas no final, quando STOP_CSV é recebido.
    """

    def __init__(self, file_name: str, sampling_rate: int, channel_count: int = 10):
        super().__init__(target=None)

        # file_name -> caminho final do CSV
        self.file_name = str(file_name)

        # sampling_rate -> mantido para compatibilidade (não usado no clock)
        self.sampling_rate = int(sampling_rate)

        # channel_count -> número total de canais no sinal final
        self.channel_count = int(channel_count)

        # is_recording -> indica se a acumulação de dados está ativa
        self.is_recording = False

        # lsl_t0 -> valor de local_clock() no momento do START_CSV.
        # Usado para calcular o tempo relativo de cada amostra.
        self.lsl_t0 = 0.0

        # lsl_epoch -> datetime correspondente ao local_clock() = 0.
        # Calculado uma única vez em start_recording() como:
        #   lsl_epoch = datetime.now() - timedelta(seconds=local_clock())
        # Permite converter qualquer local_clock() em datetime absoluto.
        self.lsl_epoch = None

        # Buffers em memória:
        # time_values      -> vetor dos tempos relativos (s desde START_CSV)
        # timestamp_values -> vetor dos timestamps absolutos (datetime)
        # channel_rows     -> uma lista por canal, contendo os seus valores
        self.time_values = []
        self.timestamp_values = []
        self.channel_rows = [[] for _ in range(self.channel_count)]

    def _reset_buffers(self):
        """
        Reinicializa o estado interno para uma nova gravação.

        Chamado quando chega o comando START_CSV.

        O offset lsl_epoch é calculado aqui uma única vez:
        - local_clock() dá o tempo LSL actual;
        - datetime.now() dá o tempo de parede actual;
        - a diferença é o offset para converter qualquer timestamp LSL
          em datetime legível.
        """
        t_lsl = local_clock()
        t_wall = datetime.now()

        # lsl_t0 é o instante LSL de referência (t=0 do CSV)
        self.lsl_t0 = t_lsl

        # lsl_epoch é o datetime correspondente a local_clock() == 0
        # Fórmula: epoch = wall - lsl  →  wall = epoch + lsl
        self.lsl_epoch = t_wall - timedelta(seconds=t_lsl)

        self.time_values = []
        self.timestamp_values = []
        self.channel_rows = [[] for _ in range(self.channel_count)]

        print(
            f"[INFO] Clock LSL sincronizado: lsl_t0={self.lsl_t0:.6f}s | "
            f"wall={t_wall.strftime('%H:%M:%S.%f')}"
        )

    def _normalize_to_samples_channels(self, arr):
        """
        Normaliza a forma dos dados para o formato:
            [n_samples, n_channels]

        Este método existe porque diferentes nós podem entregar arrays
        com orientação distinta, e o writer precisa de um formato unificado.
        """
        arr = np.asarray(arr)

        # Caso o array seja unidimensional, tenta inferir a orientação
        if arr.ndim == 1:
            if arr.size == self.channel_count:
                arr = arr.reshape(1, -1)
            else:
                arr = arr.reshape(-1, 1)

        # Se não ficar 2D, não é utilizável neste contexto
        if arr.ndim != 2:
            return None

        # Caso já esteja no formato esperado
        if arr.shape[1] == self.channel_count:
            return arr

        # Caso esteja transposto, corrige
        if arr.shape[0] == self.channel_count:
            return arr.T

        return None

    def step(self, data):
        """
        Método chamado pelo pipeline para cada bloco recebido.

        Se a gravação estiver ativa:
        - normaliza o bloco;
        - obtém o timestamp LSL actual com local_clock();
        - distribui esse timestamp uniformemente pelas amostras do bloco,
          fazendo retropolação: a última amostra tem o timestamp actual,
          as anteriores são espaçadas de 1/sampling_rate;
        - acrescenta os valores aos buffers.

        Nota sobre a distribuição dos timestamps dentro do bloco:
        - local_clock() é chamado uma vez por bloco (momento de chegada);
        - as amostras dentro do bloco são retropoladas para trás com
          passo dt = 1/sampling_rate;
        - isto é uma aproximação válida para blocos pequenos, e muito
          melhor do que usar um contador global.
        """
        if PORT_IN not in data:
            return

        arr = self._normalize_to_samples_channels(data[PORT_IN])
        if arr is None:
            return

        if not self.is_recording:
            return

        n_samples = arr.shape[0]

        # Timestamp LSL do momento de chegada deste bloco
        t_arrival = local_clock()

        # Passo temporal entre amostras consecutivas
        dt = 1.0 / self.sampling_rate

        for i, row in enumerate(arr):
            # Retropolação: a última amostra tem t_arrival,
            # as anteriores recuam de dt por posição
            lsl_ts = t_arrival - (n_samples - 1 - i) * dt

            # Tempo relativo ao início da gravação (segundos desde START_CSV)
            time_s = lsl_ts - self.lsl_t0

            # Timestamp absoluto: lsl_epoch + lsl_ts
            ts_abs = self.lsl_epoch + timedelta(seconds=lsl_ts)
            ts_str = ts_abs.strftime("%Y-%m-%d %H:%M:%S.%f")

            self.time_values.append(f"{time_s:.6f}")
            self.timestamp_values.append(ts_str)

            # Guarda cada valor na linha correspondente ao respetivo canal
            for ch in range(self.channel_count):
                self.channel_rows[ch].append(f"{float(row[ch]):.6f}")

    def _write_transposed_csv(self):
        """
        Escreve o CSV final em disco.

        Nesta fase, os buffers já contêm todos os dados acumulados da sessão.
        """
        with open(self.file_name, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)

            # Primeiras duas linhas: tempo relativo e timestamp absoluto
            writer.writerow(["Time"] + self.time_values)
            writer.writerow(["Timestamp"] + self.timestamp_values)

            # Linhas seguintes: um canal por linha
            for i in range(self.channel_count):
                writer.writerow([f"Ch{i+1:02d}"] + self.channel_rows[i])

        print(f"[INFO] CSV transposto gravado: {self.file_name}")

    def start_recording(self):
        """
        Ativa uma nova sessão de gravação.

        Reinicializa os buffers, sincroniza o clock LSL uma única vez,
        e marca o writer como ativo.
        """
        self._reset_buffers()
        self.is_recording = True
        print(f"[INFO] Gravação iniciada: {self.file_name}")

    def stop_recording(self):
        """
        Finaliza a gravação.

        Se a gravação estiver ativa:
        - desativa o modo de gravação;
        - escreve o ficheiro em disco.
        """
        if not self.is_recording:
            return

        self.is_recording = False
        self._write_transposed_csv()
        print("[INFO] Gravação terminada.")

    def __del__(self):
        """
        Salvaguarda final.

        Caso o objeto seja destruído enquanto ainda está em modo de gravação,
        tenta terminar e escrever o ficheiro.
        """
        try:
            if self.is_recording:
                self.stop_recording()
        except Exception:
            pass


class MergeContinuousEvents(IONode):
    """
    Nó responsável pela fusão entre EEG e canais de evento.

    Entrada:
    - sinal EEG com 8 canais

    Saída:
    - sinal expandido com 10 canais:
        Ch01..Ch08 -> EEG
        Ch09       -> code
        Ch10       -> trigger

    Estratégia:
    - lê o bloco EEG recebido;
    - lê o último estado conhecido dos eventos;
    - replica esse estado ao longo de todo o bloco;
    - concatena EEG e eventos num único array.
    """

    def __init__(self, shared_events, eeg_channel_count=EEG_CHANNEL_COUNT):
        super().__init__(target=None)

        # shared_events -> referência ao buffer partilhado dos eventos contínuos
        self.shared_events = shared_events

        # eeg_channel_count -> número esperado de canais EEG
        self.eeg_channel_count = int(eeg_channel_count)

    def setup(self, data, port_context_in):
        """
        Método de configuração do nó.

        Atualiza o contexto de saída para indicar que este nó produz
        eeg_channel_count + 2 canais.
        """
        port_context_out = super().setup(data, port_context_in)
        port_context_out[PORT_OUT][Constants.Keys.CHANNEL_COUNT] = self.eeg_channel_count + 2
        return port_context_out

    def _normalize_to_samples_channels(self, arr):
        """
        Normaliza os dados EEG para o formato:
            [n_samples, n_channels]
        """
        arr = np.asarray(arr)

        if arr.ndim == 1:
            if arr.size == self.eeg_channel_count:
                arr = arr.reshape(1, -1)
            else:
                arr = arr.reshape(-1, 1)

        if arr.ndim != 2:
            return None

        if arr.shape[1] == self.eeg_channel_count:
            return arr

        if arr.shape[0] == self.eeg_channel_count:
            return arr.T

        return None

    def step(self, data):
        """
        Processa cada bloco EEG recebido.

        O procedimento consiste em:
        1) validar e normalizar o bloco EEG;
        2) ler o estado mais recente [code, trigger];
        3) replicar esse estado para todas as amostras do bloco;
        4) concatenar as colunas de evento ao EEG.
        """
        if PORT_IN not in data:
            return None

        eeg = self._normalize_to_samples_channels(data[PORT_IN])
        if eeg is None:
            return None

        n_samples = eeg.shape[0]

        # Lê o último estado conhecido do stream de eventos
        with self.shared_events.lock:
            code = float(self.shared_events.current_code)
            trigger = float(self.shared_events.current_trigger)

        # Constrói colunas constantes ao longo do bloco
        code_col = np.full((n_samples, 1), code, dtype=float)
        trigger_col = np.full((n_samples, 1), trigger, dtype=float)

        # Junta EEG + eventos num único array
        merged = np.hstack((eeg, code_col, trigger_col))
        return {PORT_OUT: merged}


class LSLControlListener(threading.Thread):
    """
    Thread responsável por escutar o stream de controlo P300_Control.

    Comandos esperados:
    - START_CSV
    - STOP_CSV

    Papel funcional:
    - quando recebe START_CSV, ativa a gravação;
    - quando recebe STOP_CSV, termina a gravação e encerra a aplicação.
    """

    def __init__(self, writer, stream_name="P300_Control"):
        super().__init__(daemon=True)

        # writer -> instância de CsvWriterWithTimestamp a controlar
        self.writer = writer

        # stream_name -> nome do stream LSL de controlo
        self.stream_name = str(stream_name)

        # running -> controla o ciclo de vida da thread
        self.running = True

        # inlet será preenchido quando o stream for encontrado
        self.inlet = None

    def stop(self):
        """Sinaliza à thread que deve terminar."""
        self.running = False

    def run(self):
        """
        Loop principal da thread.

        Enquanto running=True:
        - tenta ligar ao stream de controlo;
        - lê comandos;
        - executa a ação correspondente.
        """
        while self.running:
            try:
                if self.inlet is None:
                    print(f"[INFO] À procura do stream LSL '{self.stream_name}'...")
                    streams = resolve_byprop("name", self.stream_name, timeout=2)

                    if not streams:
                        continue

                    self.inlet = StreamInlet(streams[0], max_buflen=5)
                    print(f"[INFO] Stream LSL '{self.stream_name}' ligado.")

                sample, _ = self.inlet.pull_sample(timeout=0.2)

                if sample is None:
                    continue

                cmd = str(sample[0]).strip().upper()
                print(f"[DEBUG][CONTROL] cmd recebido: {cmd}")

                if cmd == "START_CSV":
                    self.writer.start_recording()

                elif cmd == "STOP_CSV":
                    self.writer.stop_recording()
                    self.running = False
                    QCoreApplication.quit()

            except Exception as e:
                # Em caso de erro, força nova tentativa de descoberta do stream
                print(f"[WARN] LSLControlListener perdeu ligação: {e}")
                self.inlet = None


def rename_scope_windows():
    """
    Renomeia janelas top-level associadas aos scopes.

    Esta operação é feita com atraso porque, no momento da criação da app,
    as janelas/elementos gráficos ainda podem não estar totalmente materializados.

    Critério:
    - ignora janelas já com nome explícito;
    - renomeia janelas vazias ou com título padrão contendo 'gtec'.
    """
    qt_app = QApplication.instance()
    if qt_app is None:
        return

    renamed = 0

    for widget in qt_app.topLevelWidgets():
        title = widget.windowTitle().strip()

        # Mantém janelas que já estejam nomeadas corretamente
        if "Projeto Final BCI4ALL" in title:
            continue

        # Renomeia apenas títulos genéricos
        if title == "" or "gtec" in title.lower():
            if renamed == 0:
                widget.setWindowTitle("Projeto Final BCI4ALL - Scope EEG")
            elif renamed == 1:
                widget.setWindowTitle("Projeto Final BCI4ALL - Scope Eventos")

            renamed += 1


def main():
    """
    Função principal do pipeline.

    Fluxo de execução:
    1) cria a aplicação gráfica;
    2) define o título da janela principal;
    3) aplica o tema gráfico;
    4) resolve o caminho do CSV;
    5) cria a fonte EEG e os nós do pipeline;
    6) inicia listeners auxiliares;
    7) liga todos os nós;
    8) arranca o processamento e a interface;
    9) fecha recursos no final.
    """
    # Cria a aplicação principal do gpype
    app = gp.MainApp()

    # Definição de titulo 
    def rename_main_window():
        """
        Renomeia a janela principal da aplicação gpype.

        Esta operação é adiada ligeiramente para garantir que a janela
        top-level já existe no momento da alteração do título.
        """
        qt_app = QApplication.instance()
        if qt_app is not None:
            for widget in qt_app.topLevelWidgets():
                widget.setWindowTitle("Projeto Final BCI4ALL - Monitorização")

    QTimer.singleShot(200, rename_main_window)

    # Obtém a app Qt subjacente para aplicar estilo
    qt_app = QApplication.instance()
    if qt_app is not None:
        qt_app.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                color: #000000;
            }

            QLabel {
                color: #000000;
            }
        """)

    # Resolve o caminho final do CSV
    pipeline = gp.Pipeline()
    csv_file = resolve_output_file()

    # Seleção da fonte EEG:
    # - Generator para testes/simulação
    # - BCICore8 para aquisição real
    if USE_GENERATOR:
        amp = gp.Generator(
            sampling_rate=SAMPLING_RATE,
            channel_count=EEG_CHANNEL_COUNT,
            signal_frequency=10,
            signal_amplitude=15,
            signal_shape="sine",
            noise_amplitude=10,
        )
        print("[INFO] Fonte EEG: Generator")
    else:
        amp = gp.BCICore8()
        print("[INFO] Fonte EEG: BCICore8")

    # Cadeia de filtragem do EEG:
    # 1) bandpass 1-30 Hz
    # 2) notch ~50 Hz
    # 3) notch ~60 Hz
    bandpass = gp.Bandpass(f_lo=1, f_hi=30)
    notch50 = gp.Bandstop(f_lo=48, f_hi=52)
    notch60 = gp.Bandstop(f_lo=58, f_hi=62)

    # Estado partilhado dos eventos contínuos
    shared_events = SharedEventBuffer()

    # Listener do stream contínuo de eventos
    event_listener = ContinuousEventListener(
        shared_state=shared_events,
        stream_name="P300_Events",
    )

    # Nó que funde EEG com code/trigger
    merge_events = MergeContinuousEvents(
        shared_events=shared_events,
        eeg_channel_count=EEG_CHANNEL_COUNT,
    )

    # Writer responsável pela gravação final em CSV transposto
    writer = CsvWriterWithTimestamp(
        file_name=csv_file,
        sampling_rate=SAMPLING_RATE,
        channel_count=TOTAL_CHANNEL_COUNT,
    )

    # Listener do stream de controlo START_CSV / STOP_CSV
    control_listener = LSLControlListener(
        writer=writer,
        stream_name="P300_Control",
    )

    # Scope do EEG:
    # esconde os canais de evento Ch09 e Ch10
    scope_eeg = gp.TimeSeriesScope(
        name="Monitor EEG",
        amplitude_limit=50,
        time_window=10,
        hidden_channels=[8, 9],
    )

    # Scope dos eventos:
    # esconde os canais EEG Ch01..Ch08
    scope_events = gp.TimeSeriesScope(
        name="Monitor Eventos e Target",
        amplitude_limit=12,
        time_window=10,
        hidden_channels=[0, 1, 2, 3, 4, 5, 6, 7],
    )

    # Arranque das threads auxiliares antes do arranque do pipeline
    event_listener.start()
    control_listener.start()

    # Ligações do pipeline:
    # fonte -> filtros -> fusão -> scopes + writer
    pipeline.connect(amp, bandpass)
    pipeline.connect(bandpass, notch50)
    pipeline.connect(notch50, notch60)
    pipeline.connect(notch60, merge_events)

    pipeline.connect(merge_events, scope_eeg)
    pipeline.connect(merge_events, scope_events)
    pipeline.connect(merge_events, writer)

    # Adiciona os widgets gráficos à aplicação
    app.add_widget(scope_eeg)
    app.add_widget(scope_events)

    # Renomeia as janelas dos scopes após ligeiro atraso
    QTimer.singleShot(300, rename_scope_windows)

    print("[INFO] Pipeline pronta.")
    print("[INFO] Event stream: P300_Events")
    print("[INFO] Control stream: P300_Control")
    print("[INFO] Ch09 = code")
    print("[INFO] Ch10 = trigger")
    print(f"[INFO] CSV output file: {csv_file}")

    try:
        # Arranque do pipeline e entrada no ciclo gráfico principal
        pipeline.start()
        app.run()
    finally:
        # Encerramento controlado dos recursos
        pipeline.stop()

        control_listener.stop()
        event_listener.stop()

        control_listener.join(timeout=1.0)
        event_listener.join(timeout=1.0)
        writer.stop_recording()


if __name__ == "__main__":
    main()