import sys
import time

from pylsl import StreamInlet, resolve_byprop
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QProgressBar,
    QDoubleSpinBox,
    QHBoxLayout,
)


class LSLWorker(QThread):
    data = Signal(float)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        self.status.emit("À procura de stream LSL AlphaRMS...")

        inlet = None

        while self.running and inlet is None:
            try:
                streams = resolve_byprop("name", "AlphaRMS", timeout=1.0)

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
                    self.data.emit(float(sample[0]))
            except Exception as e:
                self.status.emit(f"Erro de receção: {e}")
                time.sleep(1.0)

    def stop(self):
        self.running = False
        self.wait()


class LSLBarApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("BCI Alpha Feedback - LSL")
        self.resize(320, 540)

        self.vmin = 0.0
        self.vmax = 10.0
        self.last_value = 0.0

        self.title = QLabel("ALPHA RMS FEEDBACK")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size:24px;font-weight:bold;")

        self.status_label = QLabel("A iniciar...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size:14px;color:gray;")

        self.scale_label = QLabel("Escala máxima:")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.1, 100.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(self.vmax)
        self.scale_spin.valueChanged.connect(self.on_scale_changed)

        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_label)
        scale_row.addWidget(self.scale_spin)

        self.value = QLabel("0.00")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet("font-size:40px;color:#00AEEF;font-weight:bold;")

        self.bar = QProgressBar()
        self.bar.setMinimum(0)
        self.bar.setMaximum(400)
        self.bar.setOrientation(Qt.Vertical)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet("""
            QProgressBar {
                border:2px solid grey;
                border-radius:6px;
                background:white;
                padding:2px;
            }
            QProgressBar::chunk {
                background-color:#00AEEF;
                border-radius:4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.status_label)
        layout.addLayout(scale_row)
        layout.addWidget(self.value)
        layout.addWidget(self.bar)

        self.worker = LSLWorker()
        self.worker.data.connect(self.update_value)
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

    def closeEvent(self, event):
        self.worker.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LSLBarApp()
    w.show()
    sys.exit(app.exec())