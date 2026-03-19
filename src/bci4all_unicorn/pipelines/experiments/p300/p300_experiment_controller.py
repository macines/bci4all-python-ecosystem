"""
Nome do ficheiro:
    p300_experiment_controller.py

Descrição:
    Camada 2 do protótipo P300.
    Controla a experiência em cima da grid visual:
    - define o target
    - inicia/termina a sequência
    - conta estímulos
    - regista eventos em CSV
    - envia triggers UDP (1=target, 2=non-target)

Dependências:
    - p300_single_cell_grid.py
    - PySide6
    - gpype

Notas:
    - Esta versão ainda não faz aquisição EEG.
    - Serve para validar a lógica experimental antes de ligar ao gpype pipeline.
"""

import csv
import socket
import sys
import time
from pathlib import Path

import gpype as gp
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget, QHBoxLayout, QMessageBox
from gpype.frontend.widgets.base.widget import Widget

from p300_single_cell_grid import P300SingleCellGrid


class P300ExperimentController(Widget):
    """
    Controlador experimental para uma grid P300 single-cell.

    Responsabilidades:
    - gerir target atual
    - iniciar/parar a experiência
    - receber eventos da grid
    - converter em triggers target/non-target
    - guardar log experimental
    """

    def __init__(
        self,
        labels,
        rows,
        cols,
        title="P300 Experiment Controller",
        flash_ms=150,
        isi_ms=150,
        target_idx=0,
        total_flashes=60,
        udp_host="127.0.0.1",
        udp_port=12345,
        send_udp=True,
        save_csv=True,
        csv_path="p300_experiment_log.csv",
    ):
        container = QWidget()
        super().__init__(widget=container, name=title)

        self.labels = list(labels)
        self.rows = int(rows)
        self.cols = int(cols)

        self.flash_ms = int(flash_ms)
        self.isi_ms = int(isi_ms)

        self.target_idx = int(target_idx)
        self.total_flashes = int(total_flashes)

        self.udp_host = str(udp_host)
        self.udp_port = int(udp_port)
        self.send_udp = bool(send_udp)

        self.save_csv = bool(save_csv)
        self.csv_path = Path(csv_path)

        self.running = False
        self.flash_count = 0
        self.target_count = 0
        self.nontarget_count = 0
        self.start_time = None

        self.sock = None
        if self.send_udp:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._build_ui()

        self.grid_widget = P300SingleCellGrid(
            labels=self.labels,
            rows=self.rows,
            cols=self.cols,
            flash_ms=self.flash_ms,
            isi_ms=self.isi_ms,
            title="P300 Single-Cell Grid",
            target_idx=self.target_idx,
            show_target_hint=True,
        )

        self.grid_widget.on_stimulus = self._on_stimulus
        self._layout.addWidget(self.grid_widget.widget)

        if self.save_csv:
            self._init_csv()

        self._refresh_status()

    def _build_ui(self):
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; padding: 6px;"
        )

        self.stats_label = QLabel()
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setStyleSheet("font-size: 14px; padding: 4px;")

        self.start_button = QPushButton("Iniciar")
        self.stop_button = QPushButton("Parar")
        self.next_target_button = QPushButton("Próximo target")

        self.start_button.clicked.connect(self.start_experiment)
        self.stop_button.clicked.connect(self.stop_experiment)
        self.next_target_button.clicked.connect(self.next_target)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addWidget(self.next_target_button)

        self._layout.addWidget(self.info_label)
        self._layout.addWidget(self.stats_label)
        self._layout.addLayout(button_row)

    def _init_csv(self):
        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "flash_number",
                "timestamp",
                "elapsed_s",
                "cell_idx",
                "cell_label",
                "is_target",
                "trigger_value",
                "target_label",
            ])

    def _write_csv(self, row):
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def _send_udp_trigger(self, trigger_value: int):
        if not self.send_udp or self.sock is None:
            return

        payload = str(int(trigger_value)).encode("utf-8")
        self.sock.sendto(payload, (self.udp_host, self.udp_port))

    def _refresh_status(self):
        target_label = self.labels[self.target_idx]

        self.info_label.setText(
            f"Target atual: <b>{target_label}</b> &nbsp;&nbsp; "
            f"(índice {self.target_idx})"
        )

        self.stats_label.setText(
            f"Flashes: {self.flash_count}/{self.total_flashes} | "
            f"Target: {self.target_count} | "
            f"Non-target: {self.nontarget_count} | "
            f"Estado: {'A correr' if self.running else 'Parado'}"
        )

    def start_experiment(self):
        if self.running:
            return

        self.running = True
        self.flash_count = 0
        self.target_count = 0
        self.nontarget_count = 0
        self.start_time = time.time()

        self.grid_widget.set_target(self.target_idx)
        self.grid_widget.start()
        self._refresh_status()

    def stop_experiment(self):
        if not self.running:
            return

        self.running = False
        self.grid_widget.stop()
        self._refresh_status()

    def next_target(self):
        if self.running:
            QMessageBox.information(
                self.widget,
                "Experiência a decorrer",
                "Pára primeiro a experiência antes de mudar o target."
            )
            return

        self.target_idx = (self.target_idx + 1) % len(self.labels)
        self.grid_widget.set_target(self.target_idx)
        self._refresh_status()

    def _on_stimulus(self, idx, timestamp, is_target, label):
        if not self.running:
            return

        self.flash_count += 1

        trigger_value = 1 if is_target else 2

        if is_target:
            self.target_count += 1
        else:
            self.nontarget_count += 1

        elapsed_s = 0.0 if self.start_time is None else (timestamp - self.start_time)

        print(
            f"[{timestamp:.3f}] "
            f"flash={self.flash_count} "
            f"idx={idx} "
            f"label={label} "
            f"is_target={is_target} "
            f"trigger={trigger_value}"
        )

        self._send_udp_trigger(trigger_value)

        if self.save_csv:
            self._write_csv([
                self.flash_count,
                f"{timestamp:.6f}",
                f"{elapsed_s:.6f}",
                idx,
                label,
                int(is_target),
                trigger_value,
                self.labels[self.target_idx],
            ])

        self._refresh_status()

        if self.flash_count >= self.total_flashes:
            self.stop_experiment()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            if self.running:
                self.stop_experiment()
            else:
                self.start_experiment()
        else:
            super().keyPressEvent(event)


def main():
    app = gp.MainApp()

    labels = [
        "NÃO", "SONO", "SIM",
        "STOP", "AJUDA", "TOSSE"
    ]

    controller = P300ExperimentController(
        labels=labels,
        rows=2,
        cols=3,
        title="P300 Experiment Controller",
        flash_ms=300,
        isi_ms=300,
        target_idx=2,              # ex.: "SIM"
        total_flashes=50,
        udp_host="127.0.0.1",
        udp_port=12345,
        send_udp=True,
        save_csv=True,
        csv_path="p300_experiment_log.csv",
    )

    app.add_widget(controller)
    app.run()


if __name__ == "__main__":
    main()