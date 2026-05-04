"""
Filename: single_canal_lsl_metric_receiver.py
"""

import sys
import time
import threading
import numpy as np

from pylsl import StreamInlet, resolve_byprop

from PySide6.QtCore import Qt, QThread, Signal

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QProgressBar,
    QDoubleSpinBox,
    QSpinBox,
    QHBoxLayout,
    QFrame,
    QCheckBox,
)


def _play_beep_thread(frequency=220, duration=2.5, sample_rate=44100):
    try:
        import sounddevice as sd

        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

        # Decaimento exponencial — ressoa como um sino tibetano
        envelope = np.exp(-3 * t / duration)

        # Harmónicos sobrepostos para timbre rico e natural
        wave = (
            np.sin(2 * np.pi * frequency * t) * 0.50 +
            np.sin(2 * np.pi * frequency * 2.76 * t) * 0.15 +
            np.sin(2 * np.pi * frequency * 5.40 * t) * 0.05
        ) * envelope

        wave = (wave / np.max(np.abs(wave)) * 0.6).astype(np.float32)

        sd.play(wave, samplerate=sample_rate)
        sd.wait()

    except ImportError:
        import platform
        if platform.system() == "Windows":
            import winsound
            winsound.Beep(int(frequency), int(duration * 1000))
        elif platform.system() == "Darwin":
            import subprocess
            subprocess.call(["afplay", "/System/Library/Sounds/Glass.aiff"])
        else:
            try:
                import subprocess
                subprocess.call(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                print("\a", end="", flush=True)


def play_beep_async(frequency=220, duration=2.5):
    t = threading.Thread(target=_play_beep_thread, args=(frequency, duration), daemon=True)
    t.start()


class LSLWorker(QThread):
    data = Signal(float)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        self.status.emit("A procurar stream AlphaRMS...")
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
                self.status.emit(f"Erro LSL: {e}")
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

    BEEP_COOLDOWN = 2.0

    def __init__(self):
        super().__init__()

        self.setWindowTitle("BCI Alpha Feedback - LSL")
        self.resize(420, 780)

        self.vmin = 0.0
        self.vmax = 10.0
        self.last_value = 0.0

        self.sound_threshold = 1.5
        self.sound_enabled = False
        self.bowl_frequency = 220       # frequência do sino tibetano (Hz)
        self.bowl_duration = 2.5        # duração do sino (s)
        self._last_beep_time = 0.0
        self._above_threshold = False

        self.setStyleSheet("""
            QWidget {
                background-color: #F5F7FA;
                color: #1F2933;
                font-family: Segoe UI, Arial, sans-serif;
            }

            QLabel { color: #1F2933; }

            QFrame#Card {
                background-color: #FFFFFF;
                border: 1px solid #D9E2EC;
                border-radius: 18px;
            }

            QLabel#Title {
                font-size: 22px;
                font-weight: 700;
                color: #102A43;
                letter-spacing: 2px;
            }

            QLabel#Subtitle {
                font-size: 12px;
                color: #829AB1;
            }

            QLabel#Status {
                font-size: 12px;
                color: #486581;
                background-color: #EEF4FA;
                border: 1px solid #D9E2EC;
                border-radius: 10px;
                padding: 7px 12px;
            }

            QLabel#RowLabel {
                font-size: 12px;
                font-weight: 600;
                color: #627D98;
            }

            QDoubleSpinBox, QSpinBox {
                background-color: #FFFFFF;
                border: 1px solid #BCCCDC;
                border-radius: 8px;
                padding: 5px 8px;
                font-size: 12px;
                min-width: 80px;
                color: #1F2933;
            }

            QDoubleSpinBox:focus, QSpinBox:focus { border: 1px solid #00AEEF; }

            QLabel#MetricLabel {
                font-size: 11px;
                color: #829AB1;
                font-weight: 600;
                letter-spacing: 2px;
            }

            QLabel#MetricValue {
                font-size: 52px;
                color: #102A43;
                font-weight: 800;
            }

            QLabel#MetricUnit {
                font-size: 12px;
                color: #BCCCDC;
                letter-spacing: 1px;
            }

            QCheckBox {
                font-size: 12px;
                color: #627D98;
                spacing: 6px;
            }

            QProgressBar {
                border: 2px solid #D9E2EC;
                border-radius: 14px;
                background-color: #F0F4F8;
                padding: 4px;
            }

            QProgressBar::chunk {
                background-color: #74C69D;
                border-radius: 10px;
            }

            QProgressBar[relaxed="true"]::chunk {
                background-color: #1B4332;
            }

            QLabel#RelaxBadge {
                font-size: 11px;
                font-weight: 700;
                color: #FFFFFF;
                background-color: #2D6A4F;
                border-radius: 8px;
                padding: 5px 14px;
                letter-spacing: 1px;
            }

            QLabel#RelaxBadgeHidden {
                font-size: 11px;
                padding: 5px 14px;
                color: transparent;
                background-color: transparent;
            }

            QLabel#SectionDivider {
                font-size: 10px;
                font-weight: 700;
                color: #BCCCDC;
                letter-spacing: 3px;
            }
        """)

        # --- Header ---
        self.title = QLabel("FEEDBACK ALPHA RMS")
        self.title.setObjectName("Title")
        self.title.setAlignment(Qt.AlignCenter)

        self.subtitle = QLabel("Monitorização EEG em tempo real via LSL")
        self.subtitle.setObjectName("Subtitle")
        self.subtitle.setAlignment(Qt.AlignCenter)

        self.status_label = QLabel("A iniciar...")
        self.status_label.setObjectName("Status")
        self.status_label.setAlignment(Qt.AlignCenter)

        # --- Escala máxima ---
        self.scale_label = QLabel("Escala máxima")
        self.scale_label.setObjectName("RowLabel")

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.1, 100.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(self.vmax)
        self.scale_spin.valueChanged.connect(self.on_scale_changed)

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(12)
        scale_row.addStretch()
        scale_row.addWidget(self.scale_label)
        scale_row.addWidget(self.scale_spin)
        scale_row.addStretch()

        # --- Limiar do som ---
        self.threshold_label = QLabel("Limiar do som")
        self.threshold_label.setObjectName("RowLabel")

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 100.0)
        self.threshold_spin.setSingleStep(0.1)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(self.sound_threshold)
        self.threshold_spin.valueChanged.connect(self.on_threshold_changed)

        threshold_row = QHBoxLayout()
        threshold_row.setContentsMargins(0, 0, 0, 0)
        threshold_row.setSpacing(12)
        threshold_row.addStretch()
        threshold_row.addWidget(self.threshold_label)
        threshold_row.addWidget(self.threshold_spin)
        threshold_row.addStretch()

        self.sound_checkbox = QCheckBox("Alerta sonoro ativo")
        self.sound_checkbox.setChecked(self.sound_enabled)
        self.sound_checkbox.stateChanged.connect(self.on_sound_toggle)

        sound_row = QHBoxLayout()
        sound_row.setContentsMargins(0, 0, 0, 0)
        sound_row.addStretch()
        sound_row.addWidget(self.sound_checkbox)
        sound_row.addStretch()

        # --- Divisor sino ---
        bowl_divider = QLabel("● SINO TIBETANO")
        bowl_divider.setObjectName("SectionDivider")
        bowl_divider.setAlignment(Qt.AlignCenter)

        # --- Frequência do sino ---
        self.freq_label = QLabel("Frequência (Hz)")
        self.freq_label.setObjectName("RowLabel")

        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(60, 1200)
        self.freq_spin.setSingleStep(10)
        self.freq_spin.setValue(self.bowl_frequency)
        self.freq_spin.setToolTip(
            "Frequências típicas de sinos tibetanos:\n"
            "  60–110 Hz  — graves, muito profundos\n"
            " 110–220 Hz  — baixos, terra\n"
            " 220–440 Hz  — médios, equilíbrio (recomendado)\n"
            " 440–880 Hz  — agudos, clareza\n"
            " 880–1200 Hz — muito agudos"
        )
        self.freq_spin.valueChanged.connect(self.on_freq_changed)

        freq_row = QHBoxLayout()
        freq_row.setContentsMargins(0, 0, 0, 0)
        freq_row.setSpacing(12)
        freq_row.addStretch()
        freq_row.addWidget(self.freq_label)
        freq_row.addWidget(self.freq_spin)
        freq_row.addStretch()

        # --- Duração do sino ---
        self.dur_label = QLabel("Duração (s)")
        self.dur_label.setObjectName("RowLabel")

        self.dur_spin = QDoubleSpinBox()
        self.dur_spin.setRange(0.5, 6.0)
        self.dur_spin.setSingleStep(0.5)
        self.dur_spin.setDecimals(1)
        self.dur_spin.setValue(self.bowl_duration)
        self.dur_spin.valueChanged.connect(self.on_dur_changed)

        dur_row = QHBoxLayout()
        dur_row.setContentsMargins(0, 0, 0, 0)
        dur_row.setSpacing(12)
        dur_row.addStretch()
        dur_row.addWidget(self.dur_label)
        dur_row.addWidget(self.dur_spin)
        dur_row.addStretch()

        # --- Relax badge ---
        self.relax_badge = QLabel("✓ RELAXADO")
        self.relax_badge.setObjectName("RelaxBadgeHidden")
        self.relax_badge.setAlignment(Qt.AlignCenter)

        # --- Metric ---
        self.metric_label = QLabel("VALOR ATUAL")
        self.metric_label.setObjectName("MetricLabel")
        self.metric_label.setAlignment(Qt.AlignCenter)

        self.value = QLabel("0.00")
        self.value.setObjectName("MetricValue")
        self.value.setAlignment(Qt.AlignCenter)

        self.metric_unit = QLabel("Alfa RMS")
        self.metric_unit.setObjectName("MetricUnit")
        self.metric_unit.setAlignment(Qt.AlignCenter)

        # --- Bar ---
        self.bar = QProgressBar()
        self.bar.setMinimum(0)
        self.bar.setMaximum(400)
        self.bar.setOrientation(Qt.Vertical)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(90, 280)

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.addStretch()
        bar_row.addWidget(self.bar)
        bar_row.addStretch()

        # --- Card ---
        card = QFrame()
        card.setObjectName("Card")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(12)

        card_layout.addWidget(self.title)
        card_layout.addWidget(self.subtitle)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.status_label)
        card_layout.addSpacing(4)
        card_layout.addLayout(scale_row)
        card_layout.addLayout(threshold_row)
        card_layout.addLayout(sound_row)
        card_layout.addSpacing(4)
        card_layout.addWidget(bowl_divider)
        card_layout.addLayout(freq_row)
        card_layout.addLayout(dur_row)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.relax_badge)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.metric_label)
        card_layout.addWidget(self.value)
        card_layout.addWidget(self.metric_unit)
        card_layout.addSpacing(4)
        card_layout.addLayout(bar_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(0)
        layout.addStretch()
        layout.addWidget(card)
        layout.addStretch()

        self.worker = LSLWorker()
        self.worker.data.connect(self.update_value)
        self.worker.status.connect(self.status_label.setText)
        self.worker.start()

    def on_scale_changed(self, val):
        self.vmax = float(val)
        self.refresh_display()

    def on_threshold_changed(self, val):
        self.sound_threshold = float(val)
        self._above_threshold = False

    def on_sound_toggle(self, state):
        self.sound_enabled = bool(state)
        if not self.sound_enabled:
            self._above_threshold = False

    def on_freq_changed(self, val):
        self.bowl_frequency = int(val)

    def on_dur_changed(self, val):
        self.bowl_duration = float(val)

    def update_value(self, val):
        self.last_value = float(val)
        self._check_threshold(self.last_value)
        self.refresh_display()

    def _check_threshold(self, val):
        if not self.sound_enabled:
            return
        now = time.monotonic()
        is_above = val > self.sound_threshold
        if is_above and not self._above_threshold:
            if now - self._last_beep_time >= self.BEEP_COOLDOWN:
                play_beep_async(
                    frequency=self.bowl_frequency,
                    duration=self.bowl_duration,
                )
                self._last_beep_time = now
        self._above_threshold = is_above

    def refresh_display(self):
        val = self.last_value
        is_relaxed = val > self.sound_threshold

        self.value.setText(f"{val:.2f}")

        self.bar.setProperty("relaxed", "true" if is_relaxed else "false")
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)

        if is_relaxed:
            self.relax_badge.setObjectName("RelaxBadge")
        else:
            self.relax_badge.setObjectName("RelaxBadgeHidden")
        self.relax_badge.style().unpolish(self.relax_badge)
        self.relax_badge.style().polish(self.relax_badge)

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
