# Módulo para trabalhar com tempo
# Neste código foi importado, mas não está a ser utilizado diretamente
import time

# Módulo para converter estruturas Python em JSON e vice-versa
import json

# Módulo para comunicação em rede via sockets UDP
import socket

# Biblioteca NumPy para manipulação de arrays e operações numéricas
import numpy as np

# Biblioteca principal do g.Pype
import gpype as gp

# Interface base para criar nós personalizados no pipeline
from gpype.backend.core.i_node import INode


# ==========================================
# UDP SINK
# ==========================================
class UdpOnlySink(INode):
    """
    Nó personalizado do pipeline g.Pype.

    Recebe valores processados no pipeline, aplica suavização exponencial
    e envia o resultado por UDP em formato JSON.
    """

    def __init__(self, host="127.0.0.1", port=5005, alpha=0.25, channel=7, **kwargs):
        """
        Construtor do nó.

        Parâmetros:
        - host: IP de destino para envio UDP
        - port: porto de destino para envio UDP
        - alpha: fator de suavização exponencial
        - channel: canal EEG associado ao valor enviado
        - **kwargs: argumentos adicionais herdados do INode
        """
        super().__init__(**kwargs)

        # Endereço IP para onde os dados vão ser enviados
        self.host = host

        # Porto UDP de destino
        self.port = port

        # Fator de suavização exponencial
        # Quanto maior, mais rápido reage às mudanças
        self.alpha = alpha

        # Canal EEG associado ao processamento
        self.channel = channel

        # Guarda o último valor suavizado
        # Inicialmente ainda não existe
        self._smooth = None

        # Cria um socket UDP para envio de mensagens
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def step(self, data):
        """
        Método chamado automaticamente pelo pipeline a cada novo bloco de dados.

        Recebe os dados do input "in", extrai o último valor,
        aplica suavização exponencial e envia o valor por UDP em JSON.

        Parâmetros:
        - data: dicionário com os inputs recebidos pelo nó

        Retorna:
        - dicionário vazio, porque este nó atua apenas como sink/output
        """

        # Obtém o valor associado à entrada "in"
        # Se não existir, devolve None
        x = data.get("in", None)

        # Se não houver dados de entrada, não faz nada
        if x is None:
            return {}

        # Garante que os dados ficam num array NumPy
        x = np.asarray(x)

        # Extrai o último valor recebido
        # Se o array for 2D, usa a última linha da primeira coluna
        # Se for 1D, usa simplesmente o último elemento
        v = float(x[-1, 0] if x.ndim == 2 else x[-1])

        # Se ainda não houver histórico, inicializa a suavização com o valor atual
        if self._smooth is None:
            self._smooth = v
        else:
            # Suavização exponencial:
            # novo = (1 - alpha) * anterior + alpha * atual
            self._smooth = (1 - self.alpha) * self._smooth + self.alpha * v

        # Estrutura da mensagem a enviar por UDP
        payload = {
            "metric": "alpha_rms",
            "channel": self.channel,
            "value": float(self._smooth)
        }

        # Converte o dicionário para string JSON e depois para bytes UTF-8
        msg = json.dumps(payload).encode("utf-8")

        # Envia a mensagem UDP para o destino definido
        self.sock.sendto(msg, (self.host, self.port))

        # Este nó não produz saída para o pipeline
        return {}


# ==========================================
# MAIN
# ==========================================
def main():
    """
    Função principal da aplicação.

    Cria o pipeline g.Pype, configura a aquisição do sinal EEG,
    faz a visualização em diferentes etapas de processamento,
    calcula o RMS da banda alfa e envia esse valor por UDP.
    """

    # Frequência de amostragem do sinal EEG
    fs = 250

    # Tamanho da janela para média móvel
    # Aqui usa-se 1 segundo de dados: 250 amostras
    N = fs

    # Canal EEG a usar
    channel = 7

    # Cria a aplicação principal do g.Pype
    app = gp.MainApp()

    # Cria o pipeline onde os blocos serão ligados
    p = gp.Pipeline()

    # Fonte de dados EEG proveniente do Unicorn / BCICore8
    source = gp.BCICore8()

    # Seleciona apenas o canal pretendido
    # input_channels=[[channel]] significa que vai encaminhar esse canal específico
    select = gp.Router(input_channels=[[channel]])

    # Liga a fonte ao bloco de seleção de canal
    p.connect(source, select)

    # -----------------------------
    # RAW SIGNAL
    # -----------------------------
    # Scope para visualizar o sinal bruto do canal escolhido
    raw_scope = gp.TimeSeriesScope(
        name=f"Raw CH{channel}",
        amplitude_limit=100,
        time_window=10
    )

    # Liga o sinal selecionado diretamente ao scope do sinal bruto
    p.connect(select, raw_scope)

    # -----------------------------
    # CLEAN SIGNAL
    # -----------------------------
    # Filtro passa-banda entre 1 e 30 Hz
    # Remove deriva lenta e componentes de frequência alta
    clean_bp = gp.Bandpass(f_lo=1, f_hi=30)

    # Filtro rejeita-banda entre 48 e 52 Hz
    # Serve para remover interferência da rede elétrica (~50 Hz)
    notch = gp.Bandstop(f_lo=48, f_hi=52)

    # Scope para visualizar o sinal já limpo
    clean_scope = gp.TimeSeriesScope(
        name="Clean EEG (1–30 Hz)",
        amplitude_limit=50,
        time_window=10
    )

    # Liga o canal selecionado ao passa-banda
    p.connect(select, clean_bp)

    # Liga o passa-banda ao notch
    p.connect(clean_bp, notch)

    # Liga o sinal limpo ao scope
    p.connect(notch, clean_scope)

    # -----------------------------
    # ALPHA BAND
    # -----------------------------
    # Filtro passa-banda da banda alfa: 8 a 12 Hz
    alpha_bp = gp.Bandpass(f_lo=8, f_hi=12)

    # Scope para visualizar apenas a componente alfa
    alpha_scope = gp.TimeSeriesScope(
        name="Alpha (8–12 Hz)",
        amplitude_limit=20,
        time_window=10
    )

    # Liga o canal selecionado ao filtro alfa
    p.connect(select, alpha_bp)

    # Liga a saída alfa ao respetivo scope
    p.connect(alpha_bp, alpha_scope)

    # -----------------------------
    # RMS CALCULATION
    # -----------------------------
    # Eleva o sinal ao quadrado
    sq = gp.Equation("in**2")

    # Faz média móvel sobre 1 segundo
    # Isto calcula a potência média do sinal ao quadrado
    pwr = gp.MovingAverage(window_size=N)

    # Aplica raiz quadrada à média da potência
    # Resultado: RMS do sinal
    rms = gp.Equation("sqrt(in)")

    # Reduz a taxa de amostragem do resultado final
    # Com decimation_factor=fs, passa a sair 1 valor por segundo
    dec = gp.Decimator(decimation_factor=1)

    # Liga os blocos da cadeia RMS:
    # alfa -> quadrado -> média móvel -> raiz -> decimação
    p.connect(alpha_bp, sq)
    p.connect(sq, pwr)
    p.connect(pwr, rms)
    p.connect(rms, dec)

    # -----------------------------
    # UDP OUTPUT
    # -----------------------------
    # Cria o nó personalizado que envia o RMS por UDP
    udp = UdpOnlySink(channel=channel)

    # Liga o valor RMS decimado ao nó UDP
    p.connect(dec, udp)

    # -----------------------------
    # UI
    # -----------------------------
    # Adiciona os scopes à interface gráfica do g.Pype
    app.add_widget(raw_scope)
    app.add_widget(clean_scope)
    app.add_widget(alpha_scope)

    # Inicia a execução do pipeline
    p.start()

    # Inicia a interface gráfica / loop da aplicação
    app.run()

    # Quando a aplicação terminar, para o pipeline
    p.stop()


# ==========================================
# Ponto de entrada do programa
# ==========================================
if __name__ == "__main__":
    # Executa a função principal apenas se o ficheiro
    # for corrido diretamente
    main()