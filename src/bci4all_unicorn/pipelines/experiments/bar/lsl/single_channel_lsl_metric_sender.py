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

import numpy as np
import gpype as gp

from threading import Lock
from pylsl import StreamInfo, StreamOutlet
from gpype.backend.core.i_node import INode
from gpype.frontend.widgets.base.widget import Widget

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt


import numpy as np
from threading import Lock

from gpype.backend.core.io_node import IONode
from gpype.common.constants import Constants

PORT_IN = Constants.Defaults.PORT_IN
PORT_OUT = Constants.Defaults.PORT_OUT


class DynamicChannelSelector(IONode):
    """
    Nó intermédio com input e output.
    Recebe todos os canais e deixa passar apenas
    o canal atualmente selecionado.
    """

    def __init__(self, initial_channel=7):
        super().__init__()
        self._channel = int(initial_channel)
        self._lock = Lock()

    def set_channel(self, ch):
        with self._lock:
            self._channel = int(ch)
        print(f"[CHANNEL SELECTOR] Canal alterado para {ch}")

    def get_channel(self):
        with self._lock:
            return self._channel

    def setup(self, data, port_context_in):
        """
        Propaga o contexto do input para o output,
        mas forçando a saída para 1 canal.
        """
        ctx_in = dict(port_context_in.get(PORT_IN, {}))
        ctx_out = dict(ctx_in)

        # Ajustes mais prováveis usados pelos nós seguintes
        if "channels" in ctx_out:
            ctx_out["channels"] = 1
        if "channel_count" in ctx_out:
            ctx_out["channel_count"] = 1
        if "n_channels" in ctx_out:
            ctx_out["n_channels"] = 1

        # Se houver nomes/labels de canais, reduzir para 1
        if "channel_names" in ctx_out and isinstance(ctx_out["channel_names"], (list, tuple)):
            ch = self.get_channel()
            names = list(ctx_out["channel_names"])
            if 0 <= ch < len(names):
                ctx_out["channel_names"] = [names[ch]]
            else:
                ctx_out["channel_names"] = names[:1]

        if "labels" in ctx_out and isinstance(ctx_out["labels"], (list, tuple)):
            ch = self.get_channel()
            labels = list(ctx_out["labels"])
            if 0 <= ch < len(labels):
                ctx_out["labels"] = [labels[ch]]
            else:
                ctx_out["labels"] = labels[:1]

        print(f"[CHANNEL SELECTOR] setup -> output context: {ctx_out}")
        return {PORT_OUT: ctx_out}

    def step(self, data):
        try:
            arr = np.asarray(data[PORT_IN], dtype=float)

            # Esperado: (n_samples, n_channels)
            if arr.ndim == 1:
                out = arr.reshape(-1, 1)

            elif arr.ndim == 2:
                ch = self.get_channel()

                if ch < 0 or ch >= arr.shape[1]:
                    print(f"[CHANNEL SELECTOR] Canal inválido {ch} para shape {arr.shape}")
                    return None

                out = arr[:, ch].reshape(-1, 1)

            else:
                print(f"[CHANNEL SELECTOR] shape inesperado: {arr.shape}")
                return None

            return {PORT_OUT: out}

        except Exception as e:
            print(f"[CHANNEL SELECTOR] Erro: {e}")
            return None


class LSLMetricSender(INode):
    """
    Nó que recebe a métrica RMS e publica por LSL.
    """

    def __init__(self, stream_name="AlphaRMS", stream_type="METRIC", source_id="alpha_rms_dynamic_channel"):
        super().__init__()

        info = StreamInfo(
            name=stream_name,
            type=stream_type,
            channel_count=1,
            nominal_srate=0.0,
            channel_format="float32",
            source_id=source_id
        )

        self.outlet = StreamOutlet(info)
        print(f"[LSL SENDER] Stream criado: name={stream_name}, type={stream_type}, source_id={source_id}")

    def step(self, chunk=None):
        if chunk is None:
            return None

        try:
            arr = np.asarray(chunk["in"], dtype=float)

            if arr.ndim == 0:
                self.outlet.push_sample([float(arr)])

            elif arr.ndim == 1:
                for v in arr:
                    self.outlet.push_sample([float(v)])

            elif arr.ndim == 2:
                for row in arr:
                    self.outlet.push_sample([float(row[0])])

            else:
                print(f"[LSL SENDER] shape inesperado: {arr.shape}")

        except Exception as e:
            print(f"[LSL SENDER] Erro ao enviar chunk: {e}")

        return chunk


class ChannelSelectorWidget(Widget):
    """
    Widget para seleção dinâmica do canal EEG.
    """

    def __init__(self, selector_node, n_channels=8):
        self.selector_node = selector_node

        container = QWidget()
        layout = QVBoxLayout(container)

        title = QLabel("SELEÇÃO DE CANAL EEG")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:bold;")

        subtitle = QLabel("Escolhe o canal a processar e enviar por LSL")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size:12px;color:gray;")

        label = QLabel("Canal EEG:")
        label.setAlignment(Qt.AlignCenter)

        self.combo = QComboBox()
        for ch in range(n_channels):
            self.combo.addItem(f"Canal {ch}", ch)

        self.combo.setCurrentIndex(selector_node.get_channel())
        self.combo.currentIndexChanged.connect(self.on_channel_changed)

        self.current_label = QLabel(f"Canal atual: {selector_node.get_channel()}")
        self.current_label.setAlignment(Qt.AlignCenter)
        self.current_label.setStyleSheet("font-size:14px;color:#00AEEF;font-weight:bold;")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(label)
        layout.addWidget(self.combo)
        layout.addWidget(self.current_label)

        super().__init__(widget=container, name="Canal EEG")

    def on_channel_changed(self, _index):
        ch = self.combo.currentData()
        self.selector_node.set_channel(ch)
        self.current_label.setText(f"Canal atual: {ch}")


def main():
    fs = 250
    N = fs
    initial_channel = 7

    app = gp.MainApp()
    p = gp.Pipeline()

    source = gp.BCICore8()

    # --------------------------------------
    # SELETOR DINÂMICO DE CANAL
    # --------------------------------------
    select = DynamicChannelSelector(initial_channel=initial_channel)
    p.connect(source, select)

    # --------------------------------------
    # CLEAN SIGNAL
    # --------------------------------------
    clean_bp = gp.Bandpass(f_lo=1, f_hi=30)
    notch = gp.Bandstop(f_lo=48, f_hi=52, order=4)

    clean_scope = gp.TimeSeriesScope(
        name="Clean Selected Channel (1-30 Hz)",
        amplitude_limit=50,
        time_window=10
    )

    p.connect(select, clean_bp)
    p.connect(clean_bp, notch)
    p.connect(notch, clean_scope)

    # --------------------------------------
    # ALPHA BAND
    # --------------------------------------
    alpha_bp = gp.Bandpass(f_lo=8, f_hi=12)

    alpha_scope = gp.TimeSeriesScope(
        name="Alpha Selected Channel (8-12 Hz)",
        amplitude_limit=20,
        time_window=10
    )

    p.connect(notch, alpha_bp)
    p.connect(alpha_bp, alpha_scope)

    # --------------------------------------
    # RMS ALFA
    # --------------------------------------
    sq = gp.Equation("in**2")
    pwr = gp.MovingAverage(window_size=N)
    rms = gp.Equation("sqrt(in)")

    rms_scope = gp.TimeSeriesScope(
        name="RMS Alpha Selected Channel",
        amplitude_limit=10,
        time_window=10
    )

    p.connect(alpha_bp, sq)
    p.connect(sq, pwr)
    p.connect(pwr, rms)
    p.connect(rms, rms_scope)

    # --------------------------------------
    # LSL OUTPUT
    # --------------------------------------
    lsl_sender = LSLMetricSender(
        stream_name="AlphaRMS",
        stream_type="METRIC",
        source_id="alpha_rms_dynamic_channel"
    )
    p.connect(rms, lsl_sender)

    # --------------------------------------
    # WIDGET DE CONTROLO
    # --------------------------------------
    channel_widget = ChannelSelectorWidget(selector_node=select, n_channels=8)

    # --------------------------------------
    # UI
    # --------------------------------------
    app.add_widget(channel_widget)
    app.add_widget(clean_scope)
    app.add_widget(alpha_scope)
    app.add_widget(rms_scope)

    # --------------------------------------
    # RUN
    # --------------------------------------
    print(f"[SENDER] A iniciar pipeline com canal inicial {initial_channel}")
    p.start()
    app.run()
    p.stop()


if __name__ == "__main__":
    main()