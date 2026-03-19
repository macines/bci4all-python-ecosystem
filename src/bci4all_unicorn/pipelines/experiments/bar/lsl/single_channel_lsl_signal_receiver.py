"""
Nome do ficheiro: single_channel_lsl_signal_receiver.py

Descrição:
    Receiver LSL para biofeedback EEG.
    Procura na rede um stream LSL com o nome "AlphaFiltered",
    recebe continuamente o sinal EEG de um único canal já filtrado
    na banda alfa e calcula localmente o valor RMS numa janela
    temporal de 1 segundo.

    Além da barra de feedback e do valor numérico RMS, esta versão
    apresenta também o sinal recebido em tempo real num gráfico,
    permitindo visualizar diretamente a forma de onda do canal EEG
    filtrado.

Fluxo:
    LSL (AlphaFiltered) -> buffer do sinal -> cálculo RMS
    -> atualização da barra gráfica + gráfico temporal

Função principal:
    Visualizar em tempo real a intensidade da atividade alfa
    do canal EEG selecionado no sender.
"""

import sys
import time
import numpy as np

from collections import deque
from pylsl import StreamInlet, resolve_byprop

from PySide6.QtCore import Qt, QThread, Signal, QPointF
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QProgressBar,
    QDoubleSpinBox,
    QHBoxLayout,
)
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis


# ---------------------------
# THREAD PARA RECEBER SINAL E CALCULAR RMS
# ---------------------------
class LSLWorker(QThread):
    data = Signal(float)           # RMS
    signal_data = Signal(list)     # sinal para gráfico
    status = Signal(str)

    def __init__(self, fs=250, window_seconds=1.0, display_seconds=2.0):
        super().__init__()
        self.running = True

        self.fs = int(fs)
        self.window_seconds = float(window_seconds)
        self.display_seconds = float(display_seconds)

        self.window_size = max(1, int(self.fs * self.window_seconds))
        self.display_size = max(1, int(self.fs * self.display_seconds))

        self.rms_buffer = deque(maxlen=self.window_size)
        self.display_buffer = deque(maxlen=self.display_size)

        self._plot_counter = 0

    def run(self):
        self.status.emit("À procura de stream LSL AlphaFiltered...")

        inlet = None

        while self.running and inlet is None:
            try:
                streams = resolve_byprop("name", "AlphaFiltered", timeout=1.0)

                if streams:
                    inlet = StreamInlet(streams[0])
                    info = inlet.info()

                    self.status.emit(
                        f"Ligado a {info.name()} | {info.type()} | {info.channel_count()} canal"
                    )
                else:
                    time.sleep(1.0)

            except Exception as e:
                self.status.emit(f"Erro na descoberta LSL: {e}")
                time.sleep(1.0)

        while self.running and inlet is not None:
            try:
                sample, _timestamp = inlet.pull_sample(timeout=0.5)

                if sample is not None and len(sample) > 0:
                    x = float(sample[0])

                    self.rms_buffer.append(x)
                    self.display_buffer.append(x)

                    # calcula RMS quando a janela estiver completa
                    if len(self.rms_buffer) == self.window_size:
                        arr = np.asarray(self.rms_buffer, dtype=float)
                        rms = float(np.sqrt(np.mean(arr ** 2)))
                        self.data.emit(rms)

                    # atualiza gráfico de forma mais leve
                    self._plot_counter += 1
                    if self._plot_counter >= 5:
                        self._plot_counter = 0
                        self.signal_data.emit(list(self.display_buffer))

            except Exception as e:
                self.status.emit(f"Erro de receção: {e}")
                time.sleep(1.0)

    def stop(self):
        self.running = False
        self.wait()


# ---------------------------
# INTERFACE GRÁFICA
# ---------------------------
class LSLBarApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("BCI Alpha Feedback - LSL Receiver")
        self.resize(700, 700)

        self.vmin = 0.0
        self.vmax = 10.0
        self.last_value = 0.0

        # ---------------------------
        # TÍTULO
        # ---------------------------
        self.title = QLabel("ALPHA RMS FEEDBACK")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size:24px;font-weight:bold;")

        self.status_label = QLabel("A iniciar...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size:14px;color:gray;")

        # ---------------------------
        # CONTROLO DE ESCALA DA BARRA
        # ---------------------------
        self.scale_label = QLabel("Escala máxima RMS:")

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.1, 100.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(self.vmax)
        self.scale_spin.valueChanged.connect(self.on_scale_changed)

        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_label)
        scale_row.addWidget(self.scale_spin)

        # ---------------------------
        # VALOR RMS
        # ---------------------------
        self.value = QLabel("0.00")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet("font-size:40px;color:#00AEEF;font-weight:bold;")

        # ---------------------------
        # BARRA VERTICAL
        # ---------------------------
        self.bar = QProgressBar()
        self.bar.setMinimum(0)
        self.bar.setMaximum(400)
        self.bar.setOrientation(Qt.Vertical)
        self.bar.setTextVisible(False)
        self.bar.setMinimumHeight(260)
        self.bar.setMaximumWidth(100)

        self.bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 6px;
                background: white;
                padding: 2px;
            }
            QProgressBar::chunk {
                background-color: #00AEEF;
                border-radius: 4px;
            }
        """)

        # ---------------------------
        # GRÁFICO DO SINAL
        # ---------------------------
        self.signal_title = QLabel("SINAL ALFA FILTRADO")
        self.signal_title.setAlignment(Qt.AlignCenter)
        self.signal_title.setStyleSheet("font-size:16px;font-weight:bold;")

        self.series = QLineSeries()

        self.chart = QChart()
        self.chart.addSeries(self.series)
        self.chart.legend().hide()
        self.chart.setTitle("Visualização temporal do sinal recebido")

        self.axis_x = QValueAxis()
        self.axis_x.setTitleText("Amostras")
        self.axis_x.setRange(0, 500)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("Amplitude")
        self.axis_y.setRange(-50, 50)

        self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignLeft)

        self.series.attachAxis(self.axis_x)
        self.series.attachAxis(self.axis_y)

        self.chart_view = QChartView(self.chart)
        self.chart_view.setMinimumHeight(300)

        # ---------------------------
        # LAYOUT CENTRAL: gráfico + barra
        # ---------------------------
        center_row = QHBoxLayout()
        center_row.addWidget(self.chart_view, stretch=4)
        center_row.addWidget(self.bar, stretch=1)

        # ---------------------------
        # LAYOUT PRINCIPAL
        # ---------------------------
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.status_label)
        layout.addLayout(scale_row)
        layout.addWidget(self.value)
        layout.addWidget(self.signal_title)
        layout.addLayout(center_row)

        # ---------------------------
        # WORKER
        # ---------------------------
        self.worker = LSLWorker(fs=250, window_seconds=1.0, display_seconds=2.0)
        self.worker.data.connect(self.update_value)
        self.worker.signal_data.connect(self.update_plot)
        self.worker.status.connect(self.status_label.setText)
        self.worker.start()

    def on_scale_changed(self, val):
        self.vmax = float(val)
        self.refresh_display()

    def update_value(self, val):
        self.last_value = float(val)
        self.refresh_display()

    def refresh_display(self):
        val = self.last_value
        self.value.setText(f"{val:.2f}")

        denom = self.vmax - self.vmin
        pct = 0.0 if denom <= 0 else (val - self.vmin) / denom
        pct = max(0.0, min(1.0, pct))

        self.bar.setValue(int(pct * 400))

    def update_plot(self, samples):
        if not samples:
            return

        points = [QPointF(i, float(v)) for i, v in enumerate(samples)]
        self.series.replace(points)

        # ajusta eixo X ao tamanho real do buffer
        self.axis_x.setRange(0, max(1, len(samples) - 1))

        # ajusta eixo Y dinamicamente
        ymin = min(samples)
        ymax = max(samples)

        if abs(ymax - ymin) < 1e-6:
            ymin -= 1.0
            ymax += 1.0
        else:
            margin = 0.2 * (ymax - ymin)
            ymin -= margin
            ymax += margin

        self.axis_y.setRange(ymin, ymax)

    def closeEvent(self, event):
        self.worker.stop()
        super().closeEvent(event)


# ---------------------------
# MAIN
# ---------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LSLBarApp()
    w.show()
    sys.exit(app.exec())