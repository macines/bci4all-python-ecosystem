import gpype as gp
import numpy as np

from PySide6.QtWidgets import QWidget, QLabel, QProgressBar
from gpype.frontend.widgets.base.widget import Widget
from gpype.backend.core.i_node import INode
from PySide6.QtCore import Qt


# ==========================================
# Widget da barra de potência
# ==========================================
class PowerBarWidget(Widget):
    def __init__(self, title="Alpha RMS (1s)", vmin=0.0, vmax=20.0):
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
        self.bar.setOrientation(Qt.Vertical)
        self.bar.setInvertedAppearance(False)
        self.bar.setMinimumWidth(60)
        self.bar.setMinimumHeight(250)

        self._layout.addWidget(self.label)
        self._layout.addWidget(self.bar)

    def _update(self):
        v = float(self.last_value)
        self.label.setText(f"{v:.3f}")

        if self.vmax <= self.vmin:
            pct = 0.0
        else:
            pct = (v - self.vmin) / (self.vmax - self.vmin)

        pct = max(0.0, min(1.0, pct))
        self.bar.setValue(int(pct * 1000))


# ==========================================
# Nó sink para atualizar a barra
# ==========================================
class ScalarSink(INode):
    """Recebe um valor escalar do pipeline e atualiza o widget com smoothing."""
    def __init__(self, widget: PowerBarWidget, alpha=0.25, **kwargs):
        super().__init__(**kwargs)
        self.widget = widget
        self.alpha = float(alpha)
        self._smooth = None

    def step(self, data):
        x = data.get("in", None)
        if x is None:
            return {}

        x = np.asarray(x)

        if x.ndim == 2:
            v = float(x[-1, 0])
        else:
            v = float(x[-1])

        if self._smooth is None:
            self._smooth = v
        else:
            self._smooth = (1.0 - self.alpha) * self._smooth + self.alpha * v

        self.widget.last_value = self._smooth
        return {}


# ==========================================
# Função principal
# ==========================================
def main():
    fs = 250
    N = fs  # 1 segundo

    app = gp.MainApp()
    p = gp.Pipeline()

    # ======================================
    # SOURCE
    # ======================================
    source = gp.BCICore8()

    # Ajusta o canal se necessário
    # Mantive o teu canal 7, mas confirma se corresponde mesmo ao POz na tua montagem
    select_poz = gp.Router(input_channels=[[7]])
    p.connect(source, select_poz)

    # ======================================
    # VISUALIZAÇÃO DO SINAL BRUTO
    # ======================================
    # Escala típica de EEG bruto em g.Pype: amplitude_limit=50
    raw_scope = gp.TimeSeriesScope(
        name="Raw POz",
        amplitude_limit=80,
        time_window=10
    )
    p.connect(select_poz, raw_scope)

    # ======================================
    # BRANCH DE LIMPEZA GERAL DO SINAL
    # ======================================
    # Esta branch é útil se quiseres ver o sinal limpo de forma mais geral
    clean_bp = gp.Bandpass(f_lo=1, f_hi=30)
    notch50 = gp.Bandstop(f_lo=48, f_hi=52)


    clean_scope = gp.TimeSeriesScope(
        name="Clean POz (1-30 Hz)",
        amplitude_limit=30,
        time_window=10
    )

    p.connect(select_poz, clean_bp)
    p.connect(clean_bp, notch50)
    p.connect(notch50, clean_scope)

    # ======================================
    # BRANCH ESPECÍFICA PARA ALPHA
    # ======================================
    # Aqui filtramos só a banda alpha para a veres melhor no scope
    # Não apliquei notch depois do 8-12 Hz porque essa banda já exclui os 50 Hz
    alpha_bp = gp.Bandpass(f_lo=8, f_hi=12, order=4)

    alpha_scope = gp.TimeSeriesScope(
        name="Alpha POz (8-12 Hz)",
        amplitude_limit=15,
        time_window=10
    )

    p.connect(select_poz, alpha_bp)
    p.connect(alpha_bp, alpha_scope)

    # ======================================
    # POTÊNCIA / RMS DA BANDA ALPHA
    # ======================================
    sq = gp.Equation("in**2")
    pwr_1s = gp.MovingAverage(window_size=N)
    rms = gp.Equation("sqrt(in)")
    one_per_sec = gp.Decimator(decimation_factor=fs)

    bar = PowerBarWidget(title="Alpha RMS (1s)", vmin=0.0, vmax=20.0)
    sink = ScalarSink(bar, alpha=0.25)

    p.connect(alpha_bp, sq)
    p.connect(sq, pwr_1s)
    p.connect(pwr_1s, rms)
    p.connect(rms, one_per_sec)
    p.connect(one_per_sec, sink)

    # ======================================
    # WIDGETS
    # ======================================
    app.add_widget(raw_scope)
    app.add_widget(clean_scope)
    app.add_widget(alpha_scope)
    app.add_widget(bar)

    # ======================================
    # RUN
    # ======================================
    p.start()
    app.run()
    p.stop()


if __name__ == "__main__":
    main()
