import numpy as np
import gpype as gp

from PySide6.QtWidgets import QWidget, QLabel, QProgressBar
from gpype.frontend.widgets.base.widget import Widget
from gpype.backend.core.i_node import INode
from PySide6.QtCore import Qt

# ==========================================
# Bloco 2 – Widget da barra de potência
# ==========================================
class PowerBarWidget(Widget):
    def __init__(self, title="Alpha RMS (1s)", vmin=0.0, vmax=50.0):
        self.vmin = float(vmin)
        self.vmax = float(vmax)
        self.last_value = 0.0

        container = QWidget()
        super().__init__(widget=container, name=title)

        self.label = QLabel("0.000")
        self.label.setAlignment(Qt.AlignCenter)

        self.bar = QProgressBar()
        self.bar.setMinimum(0)
        self.bar.setMaximum(1000)
        self.bar.setOrientation(Qt.Vertical)  # vertical
        self.bar.setInvertedAppearance(False) # cresce de baixo para cima
        self.bar.setMinimumWidth(60)
        self.bar.setMinimumHeight(250)

        self._layout.addWidget(self.label)
        self._layout.addWidget(self.bar)

    def _update(self):
        # Atualiza a barra e o rótulo com o valor suavizado
        v = float(self.last_value)
        self.label.setText(f"{v:.3f}")
        pct = 0.0 if self.vmax <= self.vmin else (v - self.vmin) / (self.vmax - self.vmin)
        pct = max(0.0, min(1.0, pct))
        self.bar.setValue(int(pct * 1000))

# ==========================================
# Bloco 3 – Nó de sink para atualizar a barra
# ==========================================
class ScalarSink(INode):
    """Recebe um valor escalar do pipeline e atualiza o widget (com smoothing)."""
    def __init__(self, widget: PowerBarWidget, alpha=0.2, **kwargs):
        super().__init__(**kwargs)
        self.widget = widget
        self.alpha = float(alpha)
        self._smooth = None

    def step(self, data):
        # Recebe o último valor do sinal
        x = data.get("in", None)
        if x is None:
            return {}

        x = np.asarray(x)
        v = float(x[-1, 0] if x.ndim == 2 else x[-1])

        # Suavização exponencial
        if self._smooth is None:
            self._smooth = v
        else:
            self._smooth = (1 - self.alpha) * self._smooth + self.alpha * v

        self.widget.last_value = self._smooth
        return {}



# ==========================================
# Bloco 4 – Função principal
# ==========================================
def main():
    fs = 250        # taxa de amostragem
    N = fs          # 1 segundo de janela
    app = gp.MainApp()
    p = gp.Pipeline()


    # ------------------------------------------
    # Geradores de sinal simulados original
    # ------------------------------------------
    g6  = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=6,  signal_amplitude=15, noise_amplitude=0)
    g10 = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=10, signal_amplitude=25, noise_amplitude=6)
    g20 = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=20, signal_amplitude=10, noise_amplitude=0)
   


    # modulação lenta na componente alfa
    mod = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=0.2, signal_amplitude=0.6, noise_amplitude=0)

    # mistura dos sinais: a + b*(1+m) + c
   
    mix = gp.Equation("a + b*(1+m) + c")
    p.connect(g6,  mix["a"])
    p.connect(g10, mix["b"])
    p.connect(g20, mix["c"])
    p.connect(mod, mix["m"])


    # ------------------------------------------
    # Geradores de sinal simulados
    # ------------------------------------------
    #g6  = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=6,  signal_amplitude=15, noise_amplitude=0)
    #g10 = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=10, signal_amplitude=25, noise_amplitude=0)
    #g20 = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=20, signal_amplitude=10, noise_amplitude=0)
    """
    n = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=0, signal_amplitude=0, noise_amplitude=5)


    # modulação lenta na componente alfa
    mod = gp.Generator(sampling_rate=fs, channel_count=1, signal_frequency=0.2, signal_amplitude=0.6, noise_amplitude=0)

    # mistura dos sinais: a + b*(1+m) + c
   
    #mix = gp.Equation("a + b*(1+m) + c")
    mix = gp.Equation("a+d+b")
    p.connect(g6,  mix["a"])
    p.connect(n,  mix["d"])
    p.connect(g10, mix["b"])
    #p.connect(g20, mix["c"])
    #p.connect(mod, mix["m"])
   """
    # ------------------------------------------
    # Visualização em tempo real
    # ------------------------------------------
    raw_scope = gp.TimeSeriesScope(name="Raw")
    p.connect(mix, raw_scope)

    bp = gp.Bandpass(f_lo=8, f_hi=12)
    filt_scope = gp.TimeSeriesScope(name="Filtered (8–12 Hz)")
    
    p.connect(mix, bp)
    p.connect(bp, filt_scope)


    # ------------------------------------------
    # Cálculo RMS para a barra
    # ------------------------------------------
    sq = gp.Equation("in**2")             # potência instantânea
    pwr_1s = gp.MovingAverage(window_size=N)  # média móvel de 1s
    rms = gp.Equation("sqrt(in)")         # raiz quadrada = RMS
    one_per_sec = gp.Decimator(decimation_factor=1)  # atualiza 1 vez por segundo

    bar = PowerBarWidget(title="Alpha RMS (1s)", vmin=0.0, vmax=40.0)
    sink = ScalarSink(bar, alpha=0.25)

    # conecta os nós do pipeline
    p.connect(bp, sq)
    p.connect(sq, pwr_1s)
    p.connect(pwr_1s, rms)
    p.connect(rms, one_per_sec)
    p.connect(one_per_sec, sink)

    # ------------------------------------------
    # Adiciona widgets à aplicação
    # ------------------------------------------
    app.add_widget(raw_scope)
    app.add_widget(filt_scope)
    app.add_widget(bar)

    # ------------------------------------------
    # Executa pipeline e GUI
    # ------------------------------------------
    p.start()
    app.run()
    p.stop()

    # ==========================================
    # Entrada principal
    # ==========================================
if __name__ == "__main__":
        main()
