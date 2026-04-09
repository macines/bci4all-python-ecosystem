"""
Nome do ficheiro:
    p300_single_cell_grid.py

Descrição:
    Camada 1 do protótipo P300.
    Widget visual com grelha 3x3 em que uma célula de cada vez faz flash.

Funcionalidade:
    - grelha 3x3 com palavras
    - flash de duração configurável
    - intervalo OFF configurável
    - callback no início do flash
    - callback no fim do flash

Notas:
    - Esta camada só trata da interface visual.
    - A lógica experimental fica no controller.
    - A temporização foi ajustada para respeitar melhor o ciclo:
        flash_ms ON + isi_ms OFF
"""

import random
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QPushButton, QGridLayout
from gpype.frontend.widgets.base.widget import Widget


class P300SingleCellGrid(Widget):
    def __init__(
        self,
        labels,
        rows,
        cols,
        title="P300 Single-Cell Grid",
        flash_ms=200,
        isi_ms=100,
        rng_seed=None,
        avoid_immediate_repeat=True,
        target_idx=0,
        show_target_hint=True,
    ):
        container = QWidget()
        super().__init__(widget=container, name=title)

        self.labels = list(labels)
        self.rows = int(rows)
        self.cols = int(cols)
        self.flash_ms = int(flash_ms)
        self.isi_ms = int(isi_ms)
        self.avoid_immediate_repeat = bool(avoid_immediate_repeat)

        self._rng = random.Random(rng_seed)
        self._last_idx = None
        self._running = False
        self._current_idx = None

        self.target_idx = int(target_idx)
        self.show_target_hint = bool(show_target_hint)

        # callbacks externos
        # on_stimulus_start(idx, timestamp, is_target, label)
        self.on_stimulus_start = None
        # on_stimulus_end(timestamp)
        self.on_stimulus_end = None

        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self._layout.addLayout(self.grid)

        self.buttons = []
        for i, txt in enumerate(self.labels):
            btn = QPushButton(str(txt))
            btn.setMinimumSize(220, 140)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setEnabled(False)
            btn.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))
            self.buttons.append(btn)

            r, c = divmod(i, self.cols)
            self.grid.addWidget(btn, r, c)

        self._flash_timer = QTimer()
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._flash_on)

        self._off_timer = QTimer()
        self._off_timer.setSingleShot(True)
        self._off_timer.timeout.connect(self._flash_off)

    def _style(self, active: bool, is_target: bool):
        if not active:
            if is_target and self.show_target_hint:
                return """
                QPushButton {
                    background: #6e6e6e;
                    color: white;
                    font-size: 28px;
                    font-weight: bold;
                    border: 5px solid #ffd54f;
                    border-radius: 10px;
                    padding: 10px;
                    text-align: center;
                }"""
            return """
            QPushButton {
                background: #6e6e6e;
                color: white;
                font-size: 28px;
                font-weight: bold;
                border: 3px solid #404040;
                border-radius: 10px;
                padding: 10px;
                text-align: center;
            }"""
        else:
            if is_target and self.show_target_hint:
                return """
                QPushButton {
                    background: #f0f0f0;
                    color: black;
                    font-size: 28px;
                    font-weight: bold;
                    border: 10px solid #ffd54f;
                    border-radius: 10px;
                    padding: 10px;
                    text-align: center;
                }"""
            return """
            QPushButton {
                background: #f0f0f0;
                color: black;
                font-size: 28px;
                font-weight: bold;
                border: 10px solid #ffffff;
                border-radius: 10px;
                padding: 10px;
                text-align: center;
            }"""

    def set_target(self, idx: int):
        self.target_idx = int(idx)
        self._clear_all()

    def _clear_all(self):
        for i, b in enumerate(self.buttons):
            b.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))

    def _pick_next_idx(self):
        n = len(self.buttons)
        idx = self._rng.randrange(n)

        if self.avoid_immediate_repeat and self._last_idx is not None and n > 1:
            while idx == self._last_idx:
                idx = self._rng.randrange(n)

        self._last_idx = idx
        return idx

    def start(self):
        self.stop()
        self._running = True
        self._current_idx = None
        self._clear_all()

        # espera o primeiro intervalo OFF antes do primeiro flash
        self._flash_timer.start(self.isi_ms)

    def stop(self):
        self._running = False
        self._current_idx = None
        self._flash_timer.stop()
        self._off_timer.stop()
        self._clear_all()

    def _flash_on(self):
        if not self._running:
            return

        idx = self._pick_next_idx()
        self._current_idx = idx
        is_target = idx == self.target_idx

        self.buttons[idx].setStyleSheet(self._style(active=True, is_target=is_target))

        # força atualização visual o mais cedo possível
        self.buttons[idx].repaint()

        ts = time.time()
        if callable(self.on_stimulus_start):
            self.on_stimulus_start(
                idx,
                ts,
                is_target,
                self.buttons[idx].text()
            )

        self._off_timer.start(self.flash_ms)

    def _flash_off(self):
        if self._current_idx is not None:
            self._clear_all()

        ts = time.time()
        if callable(self.on_stimulus_end):
            self.on_stimulus_end(ts)

        self._current_idx = None

        if self._running:
            self._flash_timer.start(self.isi_ms)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)