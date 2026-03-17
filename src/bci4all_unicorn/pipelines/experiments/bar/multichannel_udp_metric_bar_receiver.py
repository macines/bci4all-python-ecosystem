# ==========================================
# IMPORTS
# ==========================================

import sys
import json
import socket

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal


# ==========================================
# UDP WORKER
# ==========================================
class UdpWorker(QThread):
    """
    Thread que fica à escuta de mensagens UDP
    e envia os valores recebidos para a interface.
    """

    data = Signal(float)

    def __init__(self, host="127.0.0.1", port=5005):
        super().__init__()
        self.host = host
        self.port = port

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.host, self.port))

        print(f"[Receiver] listening on {self.host}:{self.port}")

        while True:
            packet, _ = sock.recvfrom(4096)
            msg = json.loads(packet.decode("utf-8"))
            value = float(msg.get("value", 0.0))
            self.data.emit(value)


# ==========================================
# UI
# ==========================================
class BarApp(QWidget):
    """
    Interface gráfica que apresenta:
    - título
    - valor numérico agregado
    - barra vertical de feedback
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("BCI Alpha Feedback - Sum of 3 Channels")
        self.resize(320, 520)

        # Intervalo esperado da soma dos 3 RMS
        # Ajusta depois em função dos valores reais observados
        self.vmin = 4.0
        self.vmax = 26.0

        # Título
        self.title = QLabel("ALPHA POWER\nCH6 + CH7 + CH8")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("""
            font-size:24px;
            font-weight:bold;
            color:#222;
        """)

        # Valor
        self.value = QLabel("0.00")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet("""
            font-size:40px;
            color:#00AEEF;
            font-weight:bold;
        """)

        # Barra vertical
        self.bar = QProgressBar()
        self.bar.setMinimum(0)
        self.bar.setMaximum(400)
        self.bar.setOrientation(Qt.Vertical)
        self.bar.setTextVisible(False)

        self.bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 8px;
                background: white;
                padding: 2px;
            }
            QProgressBar::chunk {
                background-color: #00AEEF;
                border-radius: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.bar)

        # Thread UDP
        self.worker = UdpWorker(host="127.0.0.1", port=5005)
        self.worker.data.connect(self.update_value)
        self.worker.start()

    def update_value(self, val):
        """
        Atualiza valor numérico e barra.
        """
        self.value.setText(f"{val:.2f}")

        pct = (val - self.vmin) / (self.vmax - self.vmin)
        pct = max(0.0, min(1.0, pct))

        self.bar.setValue(int(pct * 400))


# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = BarApp()
    w.show()
    sys.exit(app.exec())