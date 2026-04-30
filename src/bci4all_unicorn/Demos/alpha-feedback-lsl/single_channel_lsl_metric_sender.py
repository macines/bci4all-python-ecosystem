"""
Nome do ficheiro: single_channel_lsl_metric_sender.py

Descrição:
    Sender LSL para feedback EEG com Unicorn BCI Core-8.
    Recebe todos os canais EEG, permite selecionar dinamicamente
    o canal na interface gráfica durante a execução, extrai a
    banda alfa, calcula o RMS alfa e publica esse valor num
    stream LSL explícito via pylsl.

Fluxo:
    BCICore8 -> seletor dinâmico de canal -> clean -> alfa -> RMS -> LSL
"""

# Importa a biblioteca NumPy para manipulação de arrays numéricos.
import numpy as np

# Importa o gpype com o alias gp.
# É a biblioteca principal usada para construir o pipeline BCI.
import gpype as gp

# Importa Lock para proteger o acesso à variável do canal selecionado,
# evitando problemas caso seja alterada enquanto o pipeline está a correr.
from threading import Lock

# Importa:
# - StreamInfo: define as características do stream LSL
# - StreamOutlet: cria e publica o stream LSL
from pylsl import StreamInfo, StreamOutlet

# Importa INode, usado para criar nós de entrada/sink,
# neste caso para enviar a métrica RMS por LSL.
from gpype.backend.core.i_node import INode

# Importa a classe base Widget para criar widgets personalizados na interface do gpype.
from gpype.frontend.widgets.base.widget import Widget

# Importa widgets Qt usados na interface gráfica.
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox

# Importa constantes de alinhamento do Qt.
from PySide6.QtCore import Qt


# Importa novamente numpy.
# Neste caso está repetido e pode ser removido.
import numpy as np

# Importa novamente Lock.
# Também está repetido e pode ser removido.
from threading import Lock

# Importa IONode, usado para criar nós intermédios com entrada e saída.
# Este será usado no seletor dinâmico de canal.
from gpype.backend.core.io_node import IONode

# Importa Constants, que contém os nomes padrão das portas de entrada e saída.
from gpype.common.constants import Constants

# Guarda o nome padrão da porta de entrada do gpype.
PORT_IN = Constants.Defaults.PORT_IN

# Guarda o nome padrão da porta de saída do gpype.
PORT_OUT = Constants.Defaults.PORT_OUT


# Define uma classe de nó intermédio que recebe todos os canais
# e deixa passar apenas o canal selecionado.
class DynamicChannelSelector(IONode):
    """
    Nó intermédio com input e output.
    Recebe todos os canais e deixa passar apenas
    o canal atualmente selecionado.
    """

    # Construtor do seletor dinâmico.
    def __init__(self, initial_channel=7):
        # Chama o construtor da classe base IONode.
        super().__init__()

        # Guarda o canal inicial selecionado.
        self._channel = int(initial_channel)

        # Cria um lock para acesso seguro à variável do canal.
        self._lock = Lock()

    # Método para alterar o canal selecionado.
    def set_channel(self, ch):
        # Garante acesso exclusivo durante a escrita.
        with self._lock:
            self._channel = int(ch)

        # Mostra no terminal o novo canal selecionado.
        print(f"[CHANNEL SELECTOR] Canal alterado para {ch}")

    # Método para obter o canal atualmente selecionado.
    def get_channel(self):
        # Garante acesso seguro durante a leitura.
        with self._lock:
            return self._channel

    # Método de configuração inicial do nó.
    # Ajusta o contexto do output para dizer ao pipeline
    # que a saída terá apenas 1 canal.
    def setup(self, data, port_context_in):
        """
        Propaga o contexto do input para o output,
        mas forçando a saída para 1 canal.
        """

        # Copia o contexto da porta de entrada.
        ctx_in = dict(port_context_in.get(PORT_IN, {}))

        # Cria uma cópia que será usada como contexto de saída.
        ctx_out = dict(ctx_in)

        # Se existir a chave "channels", força-a para 1.
        if "channels" in ctx_out:
            ctx_out["channels"] = 1

        # Se existir a chave "channel_count", força-a para 1.
        if "channel_count" in ctx_out:
            ctx_out["channel_count"] = 1

        # Se existir a chave "n_channels", força-a para 1.
        if "n_channels" in ctx_out:
            ctx_out["n_channels"] = 1

        # Se existirem nomes de canais, reduz a lista para apenas o canal selecionado.
        if "channel_names" in ctx_out and isinstance(ctx_out["channel_names"], (list, tuple)):
            ch = self.get_channel()
            names = list(ctx_out["channel_names"])

            if 0 <= ch < len(names):
                ctx_out["channel_names"] = [names[ch]]
            else:
                ctx_out["channel_names"] = names[:1]

        # Se existirem labels de canais, reduz igualmente para 1.
        if "labels" in ctx_out and isinstance(ctx_out["labels"], (list, tuple)):
            ch = self.get_channel()
            labels = list(ctx_out["labels"])

            if 0 <= ch < len(labels):
                ctx_out["labels"] = [labels[ch]]
            else:
                ctx_out["labels"] = labels[:1]

        # Mostra no terminal o contexto final de saída.
        print(f"[CHANNEL SELECTOR] setup -> output context: {ctx_out}")

        # Devolve o contexto para a porta de saída.
        return {PORT_OUT: ctx_out}

    # Método executado a cada chunk de dados recebido.
    def step(self, data):
        try:
            # Converte os dados de entrada num array NumPy de floats.
            arr = np.asarray(data[PORT_IN], dtype=float)

            # Caso os dados venham em 1 dimensão, reorganiza para coluna única.
            if arr.ndim == 1:
                out = arr.reshape(-1, 1)

            # Caso os dados venham em 2 dimensões: (n_amostras, n_canais)
            elif arr.ndim == 2:
                # Obtém o canal atualmente selecionado.
                ch = self.get_channel()

                # Verifica se o canal é válido.
                if ch < 0 or ch >= arr.shape[1]:
                    print(f"[CHANNEL SELECTOR] Canal inválido {ch} para shape {arr.shape}")
                    return None

                # Seleciona apenas a coluna correspondente ao canal escolhido.
                out = arr[:, ch].reshape(-1, 1)

            # Se os dados vierem com outra forma inesperada, mostra erro.
            else:
                print(f"[CHANNEL SELECTOR] shape inesperado: {arr.shape}")
                return None

            # Devolve os dados filtrados para a porta de saída.
            return {PORT_OUT: out}

        except Exception as e:
            # Em caso de erro, mostra a mensagem.
            print(f"[CHANNEL SELECTOR] Erro: {e}")
            return None


# Define um nó sink que recebe a métrica RMS
# e a publica como stream LSL.
class LSLMetricSender(INode):
    """
    Nó que recebe a métrica RMS e publica por LSL.
    """

    # Construtor do nó LSL.
    def __init__(self, stream_name="AlphaRMS", stream_type="METRIC", source_id="alpha_rms_dynamic_channel"):
        # Chama o construtor da classe base INode.
        super().__init__()

        # Cria a descrição do stream LSL.
        info = StreamInfo(
            name=stream_name,           # Nome do stream
            type=stream_type,           # Tipo do stream
            channel_count=1,            # Apenas 1 canal
            nominal_srate=0.0,          # Taxa nominal 0.0 = envio irregular/event-like
            channel_format="float32",   # Tipo de dados do stream
            source_id=source_id         # Identificador único da fonte
        )

        # Cria o outlet LSL que vai publicar os dados.
        self.outlet = StreamOutlet(info)

        # Mostra no terminal a confirmação da criação do stream.
        print(f"[LSL SENDER] Stream criado: name={stream_name}, type={stream_type}, source_id={source_id}")

    # Método chamado sempre que chega um novo chunk ao nó.
    def step(self, chunk=None):
        # Se não houver dados, termina.
        if chunk is None:
            return None

        try:
            # Converte os dados recebidos num array NumPy.
            arr = np.asarray(chunk["in"], dtype=float)

            # Se for um valor escalar, envia-o como uma amostra LSL.
            if arr.ndim == 0:
                self.outlet.push_sample([float(arr)])

            # Se for um vetor 1D, envia cada valor como uma amostra.
            elif arr.ndim == 1:
                for v in arr:
                    self.outlet.push_sample([float(v)])

            # Se for uma matriz 2D, envia a primeira coluna de cada linha.
            elif arr.ndim == 2:
                for row in arr:
                    self.outlet.push_sample([float(row[0])])

            # Se tiver outro formato inesperado, mostra mensagem.
            else:
                print(f"[LSL SENDER] shape inesperado: {arr.shape}")

        except Exception as e:
            # Em caso de erro, mostra a mensagem.
            print(f"[LSL SENDER] Erro ao enviar chunk: {e}")

        # Devolve o chunk original.
        return chunk


# Define o widget gráfico para seleção dinâmica do canal EEG.
class ChannelSelectorWidget(Widget):
    """
    Widget para seleção dinâmica do canal EEG.
    """

    # Construtor do widget.
    def __init__(self, selector_node, n_channels=8):
        # Guarda a referência ao nó seletor para poder alterar o canal.
        self.selector_node = selector_node

        # Cria o contentor base do widget.
        container = QWidget()

        # Cria um layout vertical para organizar os elementos.
        layout = QVBoxLayout(container)

        # Cria o título do widget.
        title = QLabel("SELEÇÃO DE CANAL EEG")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:bold;")

        # Cria um subtítulo explicativo.
        subtitle = QLabel("Escolhe o canal a processar e enviar por LSL")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size:12px;color:gray;")

        # Cria a etiqueta do seletor.
        label = QLabel("Canal EEG:")
        label.setAlignment(Qt.AlignCenter)

        # Cria a caixa de seleção dos canais.
        self.combo = QComboBox()

        # Adiciona os canais 0 a 7 ao dropdown.
        for ch in range(n_channels):
            self.combo.addItem(f"Canal {ch}", ch)

        # Define como seleção inicial o canal atualmente configurado.
        self.combo.setCurrentIndex(selector_node.get_channel())

        # Liga a mudança de seleção ao método on_channel_changed.
        self.combo.currentIndexChanged.connect(self.on_channel_changed)

        # Cria uma etiqueta para mostrar o canal atual.
        self.current_label = QLabel(f"Canal atual: {selector_node.get_channel()}")
        self.current_label.setAlignment(Qt.AlignCenter)
        self.current_label.setStyleSheet("font-size:14px;color:#00AEEF;font-weight:bold;")

        # Adiciona todos os elementos ao layout.
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(label)
        layout.addWidget(self.combo)
        layout.addWidget(self.current_label)

        # Inicializa o widget personalizado do gpype.
        super().__init__(widget=container, name="Canal EEG")

    # Método chamado quando o utilizador muda o canal na combo box.
    def on_channel_changed(self, _index):
        # Obtém o canal selecionado.
        ch = self.combo.currentData()

        # Atualiza o nó seletor com o novo canal.
        self.selector_node.set_channel(ch)

        # Atualiza o texto apresentado na interface.
        self.current_label.setText(f"Canal atual: {ch}")


# Função principal do programa.
def main():
    # Frequência de amostragem do dispositivo.
    fs = 250

    # Número de amostras usado na janela do RMS.
    N = fs

    # Canal inicial selecionado.
    initial_channel = 5

    # Cria a aplicação principal do gpype.
    app = gp.MainApp()

    # Cria o pipeline principal.
    p = gp.Pipeline()

    # Cria a fonte de aquisição do Unicorn BCI Core-8.
    source = gp.BCICore8()

    # --------------------------------------
    # SELETOR DINÂMICO DE CANAL
    # --------------------------------------

    # Cria o nó seletor dinâmico.
    select = DynamicChannelSelector(initial_channel=initial_channel)

    # Liga a fonte ao seletor dinâmico.
    p.connect(source, select)

    # --------------------------------------
    # CLEAN SIGNAL
    # --------------------------------------

    # Cria um filtro passa-banda de 1 a 30 Hz para limpeza geral do sinal.
    clean_bp = gp.Bandpass(f_lo=1, f_hi=30)

    # Cria um filtro notch/bandstop para remover a componente de 50 Hz.
    notch = gp.Bandstop(f_lo=48, f_hi=52, order=4)

    # Cria um osciloscópio temporal para visualizar o sinal limpo.
    clean_scope = gp.TimeSeriesScope(
        name="Clean Selected Channel (1-30 Hz)",
        amplitude_limit=50,
        time_window=10
    )

    # Liga o seletor ao filtro passa-banda.
    p.connect(select, clean_bp)

    # Liga o passa-banda ao notch.
    p.connect(clean_bp, notch)

    # Liga o notch ao scope do sinal limpo.
    p.connect(notch, clean_scope)

    # --------------------------------------
    # ALPHA BAND
    # --------------------------------------

    # Cria o filtro passa-banda da banda alfa (8-12 Hz).
    alpha_bp = gp.Bandpass(f_lo=8, f_hi=12)

    # Cria um scope temporal para visualizar apenas a banda alfa.
    alpha_scope = gp.TimeSeriesScope(
        name="Alpha Selected Channel (8-12 Hz)",
        amplitude_limit=20,
        time_window=10
    )

    # Liga o sinal limpo ao filtro alfa.
    p.connect(notch, alpha_bp)

    # Liga o filtro alfa ao respetivo scope.
    p.connect(alpha_bp, alpha_scope)

    # --------------------------------------
    # RMS ALFA
    # --------------------------------------

    # Cria um bloco que eleva o sinal ao quadrado.
    sq = gp.Equation("in**2")

    # Cria uma média móvel com janela de 1 segundo.
    pwr = gp.MovingAverage(window_size=N)

    # Cria um bloco que calcula a raiz quadrada da média,
    # obtendo assim o RMS.
    rms = gp.Equation("sqrt(in)")

    # Cria um scope para visualizar a evolução do RMS alfa.
    rms_scope = gp.TimeSeriesScope(
        name="RMS Alpha Selected Channel",
        amplitude_limit=10,
        time_window=10
    )

    # Liga a banda alfa ao bloco de quadrado.
    p.connect(alpha_bp, sq)

    # Liga o quadrado à média móvel.
    p.connect(sq, pwr)

    # Liga a média móvel ao cálculo da raiz quadrada.
    p.connect(pwr, rms)

    # Liga o RMS ao scope respetivo.
    p.connect(rms, rms_scope)

    # --------------------------------------
    # LSL OUTPUT
    # --------------------------------------

    # Cria o nó responsável por publicar o RMS por LSL.
    lsl_sender = LSLMetricSender(
        stream_name="AlphaRMS",
        stream_type="METRIC",
        source_id="alpha_rms_dynamic_channel"
    )

    # Liga o RMS ao nó de envio LSL.
    p.connect(rms, lsl_sender)

    # --------------------------------------
    # WIDGET DE CONTROLO
    # --------------------------------------

    # Cria o widget para controlo do canal EEG.
    channel_widget = ChannelSelectorWidget(selector_node=select, n_channels=8)

    # --------------------------------------
    # UI
    # --------------------------------------

    # Adiciona o widget de seleção de canal à interface.
    app.add_widget(channel_widget)

    # Adiciona o scope do sinal limpo.
    app.add_widget(clean_scope)

    # Adiciona o scope da banda alfa.
    app.add_widget(alpha_scope)

    # Adiciona o scope do RMS alfa.
    app.add_widget(rms_scope)

    # --------------------------------------
    # RUN
    # --------------------------------------

    # Mostra no terminal a mensagem de arranque.
    print(f"[SENDER] A iniciar pipeline com canal inicial {initial_channel}")

    # Inicia o pipeline.
    p.start()

    # Inicia a interface gráfica.
    app.run()

    # Para o pipeline quando a interface for encerrada.
    p.stop()


# Este bloco apenas corre quando o ficheiro é executado diretamente.
if __name__ == "__main__":
    # Chama a função principal.
    main()