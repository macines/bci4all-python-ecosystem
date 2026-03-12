# Módulo para trabalhar com tempo
# Aqui é usado para manter o programa vivo com pequenas pausas no ciclo principal
import time

# Módulo para converter dicionários Python em JSON
import json

# Módulo para comunicação em rede via sockets UDP
import socket

# Biblioteca NumPy para manipulação de arrays numéricos
import numpy as np

# Biblioteca principal do g.Pype
import gpype as gp

# Classe base para criar nós personalizados no pipeline
from gpype.backend.core.i_node import INode


# ==========================================
# Sink UDP
# ==========================================
class UdpOnlySink(INode):
    """
    Nó personalizado do pipeline g.Pype que recebe valores processados,
    aplica suavização exponencial e envia o resultado por UDP em formato JSON.

    Este nó funciona como um "sink", ou seja, recebe dados no fim do pipeline
    e não produz nova saída para outros blocos.
    """

    def __init__(
        self,
        host="127.0.0.1",
        port=5005,
        alpha=0.25,
        channel=7,
        warmup_packets=10,
        print_every=10,
        **kwargs
    ):
        """
        Construtor do nó UDP.

        Parâmetros:
        - host: endereço IP de destino
        - port: porto UDP de destino
        - alpha: fator de suavização exponencial
        - channel: canal EEG associado ao valor enviado
        - warmup_packets: número de pacotes iniciais a ignorar
        - print_every: frequência de impressão no terminal
        - **kwargs: argumentos adicionais herdados do INode
        """
        # Inicializa a classe base do INode
        super().__init__(**kwargs)

        # Guarda o IP de destino como string
        self.host = str(host)

        # Guarda o porto de destino como inteiro
        self.port = int(port)

        # Guarda o fator de suavização exponencial
        self.alpha = float(alpha)

        # Guarda o canal EEG associado à métrica
        self.channel = int(channel)

        # Número de pacotes iniciais a ignorar para estabilização
        self.warmup_packets = int(warmup_packets)

        # Define de quantos em quantos pacotes será feita uma impressão no terminal
        self.print_every = int(print_every)

        # Variável para guardar o valor suavizado atual
        # Inicialmente ainda não existe valor anterior
        self._smooth = None

        # Contador de quantos blocos/pacotes já passaram pelo nó
        self.counter = 0

        # Cria um socket UDP para envio de mensagens
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def step(self, data):
        """
        Método chamado automaticamente pelo pipeline sempre que chegam novos dados.

        Fluxo:
        1. Obtém os dados da entrada "in"
        2. Extrai o último valor
        3. Aplica suavização exponencial
        4. Ignora os primeiros pacotes (warmup)
        5. Envia o valor por UDP em JSON
        6. Faz logs periódicos no terminal

        Retorna sempre um dicionário vazio porque este nó não tem saída.
        """
        try:
            # Obtém a entrada chamada "in"
            # Se não existir, devolve None
            x = data.get("in", None)

            # Se não houver entrada válida, não faz nada
            if x is None:
                return {}

            # Garante que os dados ficam num array NumPy
            x = np.asarray(x)

            # Extrai o último valor disponível
            # Se for array 2D, usa a última linha da primeira coluna
            # Se for 1D, usa o último elemento
            v = float(x[-1, 0] if x.ndim == 2 else x[-1])

            # ------------------------------------------
            # Suavização exponencial
            # ------------------------------------------
            # Se ainda não existir valor anterior, inicializa com o atual
            if self._smooth is None:
                self._smooth = v
            else:
                # Fórmula da suavização exponencial:
                # novo_suavizado = (1 - alpha) * anterior + alpha * atual
                self._smooth = (1.0 - self.alpha) * self._smooth + self.alpha * v

            # Incrementa o contador de pacotes processados
            self.counter += 1

            # ------------------------------------------
            # Warmup inicial
            # ------------------------------------------
            # Ignora os primeiros pacotes enquanto o pipeline estabiliza
            if self.counter <= self.warmup_packets:
                # Imprime apenas no primeiro e no último pacote do warmup
                if self.counter == 1 or self.counter == self.warmup_packets:
                    print(f"[UDP SENDER] Warmup {self.counter}/{self.warmup_packets} value={self._smooth:.3f}")
                return {}

            # ------------------------------------------
            # Construção da mensagem a enviar
            # ------------------------------------------
            payload = {
                # Nome da métrica enviada
                "metric": "alpha_rms",

                # Canal a que a métrica diz respeito
                "channel": self.channel,

                # Valor suavizado atual
                "value": float(self._smooth)
            }

            # Converte o dicionário para JSON e depois para bytes UTF-8
            msg = json.dumps(payload).encode("utf-8")

            # Envia a mensagem por UDP para o host/porto definidos
            self.sock.sendto(msg, (self.host, self.port))

            # ------------------------------------------
            # Logging periódico
            # ------------------------------------------
            # Se print_every > 0, imprime uma mensagem a cada N pacotes
            if self.print_every > 0 and self.counter % self.print_every == 0:
                print(f"[UDP SENDER] value={self._smooth:.3f} -> {self.host}:{self.port}")

        except Exception as e:
            # Captura qualquer erro durante o processamento e mostra no terminal
            print("[UDP SENDER ERROR]", repr(e))

        # Este nó não devolve nada ao pipeline
        return {}


# ==========================================
# MAIN
# ==========================================
def main():
    """
    Função principal do programa.

    Cria e configura um pipeline g.Pype para:
    - adquirir um canal EEG
    - filtrar a banda alfa
    - calcular o RMS da alfa
    - reduzir para 1 valor por segundo
    - enviar esse valor por UDP
    """

    # Frequência de amostragem do sinal EEG
    fs = 250

    # Tamanho da janela da média móvel
    # Aqui, como N = fs, a janela corresponde a 1 segundo
    N = fs

    # Canal EEG selecionado
    selected_channel = 7

    # Mensagens iniciais de arranque
    print("[INFO] Starting UDP alpha RMS sender...")
    print(f"[INFO] Source channel: {selected_channel}")
    print("[INFO] Target UDP: 127.0.0.1:5005")

    # Cria o pipeline principal
    p = gp.Pipeline()

    # ------------------------------------------
    # SOURCE
    # ------------------------------------------
    # Fonte de dados EEG a partir do dispositivo BCICore8
    source = gp.BCICore8()

    # Seleciona apenas o canal desejado
    select_ch = gp.Router(input_channels=[[selected_channel]])

    # ------------------------------------------
    # BRANCH ALPHA
    # ------------------------------------------
    # Filtro passa-banda para extrair apenas a banda alfa (8-12 Hz)
    alpha_bp = gp.Bandpass(f_lo=8, f_hi=12)

    # ------------------------------------------
    # RMS = sqrt(moving_average(x^2))
    # ------------------------------------------
    # Eleva o sinal ao quadrado
    sq = gp.Equation("in**2")

    # Calcula média móvel de 1 segundo do sinal ao quadrado
    pwr_1s = gp.MovingAverage(window_size=N)

    # Aplica raiz quadrada ao resultado para obter o RMS
    rms = gp.Equation("sqrt(in)")

    # Reduz a taxa de saída para 1 valor por segundo
    one_per_sec = gp.Decimator(decimation_factor=fs)

    # ------------------------------------------
    # Sink UDP
    # ------------------------------------------
    # Nó final que envia o RMS da alfa por UDP
    udp_sink = UdpOnlySink(
        host="127.0.0.1",
        port=5005,
        alpha=0.25,
        channel=selected_channel,
        warmup_packets=10,
        print_every=10
    )

    # ------------------------------------------
    # Ligações do pipeline
    # ------------------------------------------
    # source -> seleção de canal
    p.connect(source, select_ch)

    # seleção de canal -> filtro alfa
    p.connect(select_ch, alpha_bp)

    # alfa -> quadrado
    p.connect(alpha_bp, sq)

    # quadrado -> média móvel
    p.connect(sq, pwr_1s)

    # média móvel -> raiz quadrada
    p.connect(pwr_1s, rms)

    # RMS -> decimador (1 valor por segundo)
    p.connect(rms, one_per_sec)

    # valor final -> envio por UDP
    p.connect(one_per_sec, udp_sink)

    # ------------------------------------------
    # Arranque do pipeline
    # ------------------------------------------
    p.start()
    print("[INFO] Pipeline started. Sending alpha RMS via UDP...")

    try:
        # Mantém o programa em execução continuamente
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        # Permite parar o programa com Ctrl+C
        print("[INFO] Stopping sender...")

    finally:
        # Garante tentativa de paragem do pipeline, mesmo em caso de erro/interrupção
        try:
            p.stop()
        except Exception as e:
            print("[INFO] Error while stopping pipeline:", repr(e))


# ==========================================
# Ponto de entrada do programa
# ==========================================
if __name__ == "__main__":
    # Executa a função principal apenas se este ficheiro
    # for executado diretamente
    main()