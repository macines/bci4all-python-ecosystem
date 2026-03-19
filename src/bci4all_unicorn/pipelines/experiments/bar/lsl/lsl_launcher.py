"""
Nome do ficheiro: lsl_launcher.py

Descrição:
    Janela principal para lançar e controlar o sender e o receiver LSL.
    Cada aplicação é executada em processo separado, permitindo iniciar
    e fechar cada uma de forma independente através de botões.

Vantagens:
    - Evita correr manualmente os dois ficheiros no terminal.
    - Mantém sender e receiver isolados, o que reduz conflitos entre UIs.
    - Permite abrir apenas o sender, apenas o receiver, ou ambos.

Funcionamento:
    - Botão "Iniciar Sender" -> abre o ficheiro do sender.
    - Botão "Iniciar Receiver" -> abre o ficheiro do receiver.
    - Botão "Iniciar Ambos" -> abre os dois.
    - Botões "Fechar ..." -> terminam os processos respetivos.
"""

import sys
import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
)


class LSLLauncher(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("BCI4ALL - LSL Launcher")
        self.resize(420, 260)

        # Processos
        self.sender_process = None
        self.receiver_process = None

        # Caminhos dos ficheiros
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.sender_file = os.path.join(base_dir, "single_channel_lsl_metric_sender.py")
        self.receiver_file = os.path.join(base_dir, "single_channel_lsl_metric_receiver.py")

        # UI
        self.title = QLabel("MENU PRINCIPAL LSL")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 22px; font-weight: bold;")

        self.status = QLabel("Pronto.")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("font-size: 13px; color: gray;")

        self.btn_start_sender = QPushButton("Iniciar Sender")
        self.btn_start_receiver = QPushButton("Iniciar Receiver")
        self.btn_start_both = QPushButton("Iniciar Ambos")

        self.btn_stop_sender = QPushButton("Fechar Sender")
        self.btn_stop_receiver = QPushButton("Fechar Receiver")
        self.btn_stop_both = QPushButton("Fechar Ambos")

        self.btn_start_sender.clicked.connect(self.start_sender)
        self.btn_start_receiver.clicked.connect(self.start_receiver)
        self.btn_start_both.clicked.connect(self.start_both)

        self.btn_stop_sender.clicked.connect(self.stop_sender)
        self.btn_stop_receiver.clicked.connect(self.stop_receiver)
        self.btn_stop_both.clicked.connect(self.stop_both)

        row1 = QHBoxLayout()
        row1.addWidget(self.btn_start_sender)
        row1.addWidget(self.btn_start_receiver)

        row2 = QHBoxLayout()
        row2.addWidget(self.btn_stop_sender)
        row2.addWidget(self.btn_stop_receiver)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addSpacing(10)
        layout.addLayout(row1)
        layout.addWidget(self.btn_start_both)
        layout.addSpacing(10)
        layout.addLayout(row2)
        layout.addWidget(self.btn_stop_both)

    def is_running(self, proc):
        return proc is not None and proc.poll() is None

    def start_sender(self):
        if not os.path.exists(self.sender_file):
            QMessageBox.critical(self, "Erro", f"Ficheiro não encontrado:\n{self.sender_file}")
            return

        if self.is_running(self.sender_process):
            self.status.setText("Sender já está em execução.")
            return

        self.sender_process = subprocess.Popen([sys.executable, self.sender_file])
        self.status.setText("Sender iniciado.")

    def start_receiver(self):
        if not os.path.exists(self.receiver_file):
            QMessageBox.critical(self, "Erro", f"Ficheiro não encontrado:\n{self.receiver_file}")
            return

        if self.is_running(self.receiver_process):
            self.status.setText("Receiver já está em execução.")
            return

        self.receiver_process = subprocess.Popen([sys.executable, self.receiver_file])
        self.status.setText("Receiver iniciado.")

    def start_both(self):
        self.start_sender()
        self.start_receiver()
        self.status.setText("Sender e Receiver iniciados.")

    def stop_sender(self):
        if self.is_running(self.sender_process):
            self.sender_process.terminate()
            self.sender_process = None
            self.status.setText("Sender fechado.")
        else:
            self.status.setText("Sender não estava em execução.")

    def stop_receiver(self):
        if self.is_running(self.receiver_process):
            self.receiver_process.terminate()
            self.receiver_process = None
            self.status.setText("Receiver fechado.")
        else:
            self.status.setText("Receiver não estava em execução.")

    def stop_both(self):
        self.stop_sender()
        self.stop_receiver()
        self.status.setText("Todos os processos foram fechados.")

    def closeEvent(self, event):
        # Fecha processos ao encerrar launcher
        if self.is_running(self.sender_process):
            self.sender_process.terminate()
        if self.is_running(self.receiver_process):
            self.receiver_process.terminate()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LSLLauncher()
    w.show()
    sys.exit(app.exec())