"""
Nome do ficheiro: multichannel_udp_metric_bar_sender.py

Descrição:
    Sender do sistema de feedback EEG multicanal com Unicorn BCI Core-8.
    Adquire os canais 6, 7 e 8, processa cada canal individualmente,
    extrai a banda alfa (8–12 Hz), calcula o RMS por canal, combina os
    três valores RMS e envia o valor agregado por UDP em formato JSON.

Fluxo:
    BCICore8 -> seleção de canal -> limpeza -> banda alfa -> RMS
    -> combinação dos 3 RMS -> soma e suavização -> envio UDP

Dependências:
    - gpype
    - numpy
    - socket
    - json

Execução:
    python multichannel_udp_metric_bar_sender.py
"""
# ==========================================
# IMPORTS
# ==========================================

import json
import socket
import numpy as np

import gpype as gp
from gpype.backend.core.i_node import INode


# ==========================================
# UDP SINK
# ==========================================
class UdpOnlySink(INode):
    """
    Nó final do pipeline.

    Recebe os 3 RMS combinados num único output,
    soma os canais, aplica suavização exponencial
    e envia o resultado por UDP em JSON.
    """

    def __init__(self, host="127.0.0.1", port=5005, alpha=0.25, channels=(5, 6, 7), **kwargs):
        super().__init__(**kwargs)

        self.host = host
        self.port = port
        self.alpha = alpha
        self.channels = list(channels)

        self._smooth = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def step(self, data):
        x = data.get("in", None)
        if x is None:
            return {}

        x = np.asarray(x)

        # Esperado: última amostra com 3 colunas (CH6, CH7, CH8)
        if x.ndim == 2:
            v = float(np.sum(x[-1, :]))
        elif x.ndim == 1:
            v = float(np.sum(x))
        else:
            return {}

        if self._smooth is None:
            self._smooth = v
        else:
            self._smooth = (1 - self.alpha) * self._smooth + self.alpha * v

        payload = {
            "metric": "alpha_rms_sum",
            "channels": self.channels,
            "value": float(self._smooth)
        }

        msg = json.dumps(payload).encode("utf-8")
        self.sock.sendto(msg, (self.host, self.port))

        return {}


# ==========================================
# AUXILIAR: cria ramo de 1 canal
# ==========================================
def build_channel_branch(pipeline, source, channel, fs):
    """
    Cria um ramo completo para 1 canal:
    seleção -> clean -> alpha -> RMS

    Retorna:
    - raw_scope
    - clean_scope
    - alpha_scope
    - rms_scope
    - rms node
    """

    N = fs

    # Seleção de apenas 1 canal
    select = gp.Router(input_channels=[[channel]])
    pipeline.connect(source, select)

    # -----------------------------
    # RAW
    # -----------------------------
    raw_scope = gp.TimeSeriesScope(
        name=f"Raw CH{channel}",
        amplitude_limit=100,
        time_window=10
    )
    pipeline.connect(select, raw_scope)

    # -----------------------------
    # CLEAN
    # -----------------------------
    clean_bp = gp.Bandpass(f_lo=1, f_hi=30)
    notch = gp.Bandstop(f_lo=48, f_hi=5, order=4)

    clean_scope = gp.TimeSeriesScope(
        name=f"Clean CH{channel} (1-30 Hz)",
        amplitude_limit=50,
        time_window=10
    )

    pipeline.connect(select, clean_bp)
    pipeline.connect(clean_bp, notch)
    pipeline.connect(notch, clean_scope)

    # -----------------------------
    # ALPHA
    # -----------------------------
    alpha_bp = gp.Bandpass(f_lo=8, f_hi=12)

    alpha_scope = gp.TimeSeriesScope(
        name=f"Alpha CH{channel} (8-12 Hz)",
        amplitude_limit=20,
        time_window=10
    )

    pipeline.connect(notch, alpha_bp)
    pipeline.connect(alpha_bp, alpha_scope)

    # -----------------------------
    # RMS
    # -----------------------------
    sq = gp.Equation("in**2")
    pwr = gp.MovingAverage(window_size=N)
    rms = gp.Equation("sqrt(in)")

    rms_scope = gp.TimeSeriesScope(
        name=f"RMS Alpha CH{channel}",
        amplitude_limit=10,
        time_window=10
    )

    pipeline.connect(alpha_bp, sq)
    pipeline.connect(sq, pwr)
    pipeline.connect(pwr, rms)
    pipeline.connect(rms, rms_scope)

    return raw_scope, clean_scope, alpha_scope, rms_scope, rms


# ==========================================
# MAIN
# ==========================================
def main():
    fs = 250
    channels = [5,6, 7]

    app = gp.MainApp()
    p = gp.Pipeline()

    source = gp.BCICore8()

    # -----------------------------
    # RAMOS INDIVIDUAIS
    # -----------------------------
    raw6, clean6, alpha6, rms_scope6, rms6 = build_channel_branch(p, source, 5, fs)
    raw7, clean7, alpha7, rms_scope7, rms7 = build_channel_branch(p, source, 6, fs)
    raw8, clean8, alpha8, rms_scope8, rms8 = build_channel_branch(p, source, 7, fs)

    # -----------------------------
    # COMBINADOR DOS 3 RMS
    # -----------------------------
    combiner = gp.Router(input_channels=[[0], [0], [0]])

    p.connect(rms6, combiner["in1"])
    p.connect(rms7, combiner["in2"])
    p.connect(rms8, combiner["in3"])

    rms_all_scope = gp.TimeSeriesScope(
        name="RMS Alpha Combined (CH6, CH7, CH8)",
        amplitude_limit=10,
        time_window=10
    )
    p.connect(combiner, rms_all_scope)

    # -----------------------------
    # UDP OUTPUT
    # -----------------------------
    udp = UdpOnlySink(
        host="127.0.0.1",
        port=5005,
        alpha=0.25,
        channels=channels
    )

    p.connect(combiner, udp)

    # -----------------------------
    # UI
    # -----------------------------
    #app.add_widget(clean6)
    app.add_widget(alpha6)
    #app.add_widget(rms_scope6)

    #app.add_widget(clean7)
    app.add_widget(alpha7)
    #app.add_widget(rms_scope7)

    #app.add_widget(clean8)
    app.add_widget(alpha8)
    #app.add_widget(rms_scope8)

    app.add_widget(rms_all_scope)

    # -----------------------------
    # RUN
    # -----------------------------
    p.start()
    app.run()
    p.stop()


# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    main()
