"""
Nome do ficheiro: single_channel_lsl_signal_sender.py

Descrição:
    Sender LSL para feedback EEG com Unicorn BCI Core-8.
    Recebe os canais EEG do dispositivo, permite selecionar
    dinamicamente o canal na interface gráfica durante a execução,
    aplica pré-processamento ao sinal e isola a banda alfa.

    Este sender publica via LSL o sinal EEG do canal selecionado já filtrado na banda
    alfa (8–12 Hz), permitindo que o cálculo de métricas como RMS
    seja efetuado no receiver.

Fluxo:
    BCICore8 -> seletor dinâmico de canal -> clean (1–30 Hz)
    -> notch (48–52 Hz) -> alfa (8–12 Hz) -> LSL

Stream publicado:
    Nome: AlphaFiltered
    Tipo: EEG
    Canais: 1
    Formato: float32
"""

# Biblioteca numérica para arrays
import numpy as np

# Framework de pipelines (gpype)
import gpype as gp

# Lock para evitar conflitos entre threads
from threading import Lock

# Biblioteca LSL (streaming)
from pylsl import StreamInfo, StreamOutlet

# Interfaces base dos nós gpype
from gpype.backend.core.i_node import INode
from gpype.backend.core.io_node import IONode

# Classe base para widgets
from gpype.frontend.widgets.base.widget import Widget

# Constantes do gpype (portos de entrada/saída)
from gpype.common.constants import Constants

# Componentes gráficos (Qt)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt

# Definição dos portos padrão
PORT_IN = Constants.Defaults.PORT_IN
PORT_OUT = Constants.Defaults.PORT_OUT


# -------------------------------------------------
# NÓ: SELETOR DINÂMICO DE CANAL EEG
# -------------------------------------------------
class DynamicChannelSelector(IONode):

    def __init__(self, initial_channel=7):
        super().__init__()

        # canal atualmente selecionado
        self._channel = int(initial_channel)

        # lock para evitar problemas entre threads
        self._lock = Lock()

    # altera o canal
    def set_channel(self, ch):
        with self._lock:
            self._channel = int(ch)
        print(f"[CHANNEL SELECTOR] Canal alterado para {ch}")

    # devolve canal atual
    def get_channel(self):
        with self._lock:
            return self._channel

    # configuração inicial do nó (contexto dos dados)
    def setup(self, data, port_context_in):

        # copia contexto de entrada
        ctx_in = dict(port_context_in.get(PORT_IN, {}))
        ctx_out = dict(ctx_in)

        # força saída para 1 canal
        if "channels" in ctx_out:
            ctx_out["channels"] = 1

        if "channel_count" in ctx_out:
            ctx_out["channel_count"] = 1

        if "n_channels" in ctx_out:
            ctx_out["n_channels"] = 1

        # canal selecionado
        ch = self.get_channel()

        # ajustar nomes dos canais
        if "channel_names" in ctx_out:
            names = list(ctx_out["channel_names"])

            # escolhe o nome correspondente ao canal
            ctx_out["channel_names"] = [names[ch]] if 0 <= ch < len(names) else names[:1]

        # ajustar labels
        if "labels" in ctx_out:
            labels = list(ctx_out["labels"])
            ctx_out["labels"] = [labels[ch]] if 0 <= ch < len(labels) else labels[:1]

        print(f"[CHANNEL SELECTOR] setup -> {ctx_out}")

        # devolve contexto atualizado
        return {PORT_OUT: ctx_out}

    # processamento dos dados
    def step(self, data):
        try:
            # converter para array numpy
            arr = np.asarray(data[PORT_IN], dtype=float)

            # caso 1D (um único canal já)
            if arr.ndim == 1:
                out = arr.reshape(-1, 1)

            # caso normal (samples x canais)
            elif arr.ndim == 2:
                ch = self.get_channel()

                # validação do canal
                if ch >= arr.shape[1]:
                    print("[CHANNEL SELECTOR] Canal inválido")
                    return None

                # extrai apenas o canal selecionado
                out = arr[:, ch].reshape(-1, 1)

            else:
                print("[CHANNEL SELECTOR] Formato inesperado")
                return None

            # devolve dados filtrados
            return {PORT_OUT: out}

        except Exception as e:
            print(f"[CHANNEL SELECTOR] Erro: {e}")
            return None


# -------------------------------------------------
# NÓ: ENVIO DO SINAL VIA LSL
# -------------------------------------------------
class LSLSignalSender(INode):

    def __init__(
        self,
        stream_name="AlphaFiltered",   # nome do stream
        stream_type="EEG",             # tipo
        source_id="alpha_filtered_channel",  # identificador único
        nominal_srate=250.0,           # frequência de amostragem
    ):
        super().__init__()

        # definição do stream LSL
        info = StreamInfo(
            name=stream_name,
            type=stream_type,
            channel_count=1,            # apenas 1 canal
            nominal_srate=float(nominal_srate),
            channel_format="float32",
            source_id=source_id,
        )

        # criação do outlet (envio)
        self.outlet = StreamOutlet(info)

        print(f"[LSL SENDER] Stream criado: {stream_name}")

    # envio de dados
    def step(self, chunk=None):
        if chunk is None:
            return None

        try:
            # converter para numpy
            arr = np.asarray(chunk["in"], dtype=float)

            # valor escalar
            if arr.ndim == 0:
                self.outlet.push_sample([float(arr)])

            # vetor
            elif arr.ndim == 1:
                for v in arr:
                    self.outlet.push_sample([float(v)])

            # matriz (samples x 1 canal)
            elif arr.ndim == 2:
                for row in arr:
                    self.outlet.push_sample([float(row[0])])

            else:
                print("[LSL SENDER] Formato inesperado")

        except Exception as e:
            print(f"[LSL SENDER] Erro: {e}")

        return chunk


# -------------------------------------------------
# WIDGET: ESCOLHA DO CANAL
# -------------------------------------------------
class ChannelSelectorWidget(Widget):

    def __init__(self, selector_node, n_channels=8):

        # referência ao nó (backend)
        self.selector_node = selector_node

        # container gráfico
        container = QWidget()
        layout = QVBoxLayout(container)

        # título
        title = QLabel("SELEÇÃO DE CANAL EEG")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:bold;")

        # dropdown de seleção
        self.combo = QComboBox()

        # adiciona canais (0 a 7)
        for ch in range(n_channels):
            self.combo.addItem(f"Canal {ch}", ch)

        # define canal inicial
        self.combo.setCurrentIndex(selector_node.get_channel())

        # evento quando muda
        self.combo.currentIndexChanged.connect(self.on_channel_changed)

        # label com canal atual
        self.current_label = QLabel(f"Canal atual: {selector_node.get_channel()}")
        self.current_label.setAlignment(Qt.AlignCenter)

        # layout
        layout.addWidget(title)
        layout.addWidget(self.combo)
        layout.addWidget(self.current_label)

        # inicialização do widget gpype
        super().__init__(widget=container, name="Canal EEG")

    # callback quando utilizador muda canal
    def on_channel_changed(self, _index):
        ch = self.combo.currentData()

        # atualiza nó backend
        self.selector_node.set_channel(ch)

        # atualiza texto
        self.current_label.setText(f"Canal atual: {ch}")


# -------------------------------------------------
# FUNÇÃO PRINCIPAL
# -------------------------------------------------
def main():

    fs = 250                # frequência de amostragem
    initial_channel = 7     # canal inicial

    # aplicação gráfica gpype
    app = gp.MainApp()

    # pipeline
    p = gp.Pipeline()

    # fonte EEG (Unicorn)
    source = gp.BCICore8()

    # seletor de canal
    select = DynamicChannelSelector(initial_channel=initial_channel)
    p.connect(source, select)

    # filtros
    clean_bp = gp.Bandpass(f_lo=1, f_hi=30)   # limpa ruído
    notch = gp.Bandstop(f_lo=48, f_hi=52, order=4)     # remove 50Hz
    alpha_bp = gp.Bandpass(f_lo=8, f_hi=12)   # banda alfa

    # liga pipeline
    p.connect(select, clean_bp)
    p.connect(clean_bp, notch)
    p.connect(notch, alpha_bp)

    # sender LSL
    lsl_sender = LSLSignalSender(
        stream_name="AlphaFiltered",
        stream_type="EEG",
        source_id="alpha_filtered_channel",
        nominal_srate=fs,
    )

    # ligação final
    p.connect(alpha_bp, lsl_sender)

    # widget UI
    channel_widget = ChannelSelectorWidget(select, n_channels=8)
    app.add_widget(channel_widget)

    # inicia pipeline
    p.start()

    # corre interface
    app.run()

    # para pipeline
    p.stop()


# ponto de entrada
if __name__ == "__main__":
    main()