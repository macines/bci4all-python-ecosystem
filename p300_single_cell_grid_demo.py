import gpype as gp
import random
import time

from PySide6.QtWidgets import QWidget, QPushButton, QGridLayout
from PySide6.QtCore import Qt, QTimer
from gpype.frontend.widgets.base.widget import Widget


class P300SingleCellGrid(Widget):
    def __init__(self, labels, rows, cols,
                 title="P300 Single-Cell",
                 flash_ms=150,
                 isi_ms=150,
                 rng_seed=None,
                 avoid_immediate_repeat=True):

        container = QWidget()
        super().__init__(widget=container, name=title)

        self.rows = int(rows)
        self.cols = int(cols)
        self.flash_ms = int(flash_ms)
        self.isi_ms = int(isi_ms)
        self.avoid_immediate_repeat = bool(avoid_immediate_repeat)

        self._rng = random.Random(rng_seed)
        self._last_idx = None
        self._pending_off = False

        self.on_stimulus = None

        # IMPORTANTE: usar o layout do gpype (self._layout)
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self._layout.addLayout(self.grid)

        self.buttons = []
        for i, txt in enumerate(labels):
            btn = QPushButton(txt)
            btn.setMinimumSize(240, 180)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet(self._style(active=False))
            self.buttons.append(btn)

            r, c = divmod(i, self.cols)
            self.grid.addWidget(btn, r, c)

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)

    def _style(self, active: bool):
        if not active:
            return """
            QPushButton {
                background: #7f7f7f;
                color: white;
                font-size: 52px;
                border: 3px solid #4a4a4a;
                border-radius: 10px;
            }"""
        else:
            return """
            QPushButton {
                background: #b0b0b0;
                color: white;
                font-size: 52px;
                border: 10px solid #ffffff;
                border-radius: 10px;
            }"""

    def _clear_all(self):
        for b in self.buttons:
            b.setStyleSheet(self._style(active=False))

    def _pick_next_idx(self):
        n = len(self.buttons)
        idx = self._rng.randrange(n)
        if self.avoid_immediate_repeat and self._last_idx is not None and n > 1:
            while idx == self._last_idx:
                idx = self._rng.randrange(n)
        self._last_idx = idx
        return idx

    def start(self):
        self._clear_all()
        self._pending_off = False
        self._timer.start(self.isi_ms)

    def stop(self):
        self._timer.stop()
        self._clear_all()

    def _tick(self):
        if self._pending_off:
            return

        idx = self._pick_next_idx()
        self.buttons[idx].setStyleSheet(self._style(active=True))

        if callable(self.on_stimulus):
            self.on_stimulus(idx, time.time())

        self._pending_off = True
        QTimer.singleShot(self.flash_ms, self._flash_off)

    def _flash_off(self):
        self._clear_all()
        self._pending_off = False


def main():
    app = gp.MainApp()

    labels = ["NÃO", "SONO", "SIM",
              "STOP", "AJUDA", "TOSSE"]

    grid = P300SingleCellGrid(labels, rows=2, cols=3, flash_ms=300, isi_ms=300, title="P300 Single-Cell")
    app.add_widget(grid)

    grid.start()
    app.run()
    grid.stop()


if __name__ == "__main__":
    main()