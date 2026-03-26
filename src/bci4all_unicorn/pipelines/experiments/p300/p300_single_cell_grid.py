"""
Nome do ficheiro:
    p300_single_cell_grid.py

Descrição:
    Grid visual inicial para paradigma P300 single-cell.
    Uma célula de cada vez faz flash. O widget identifica se o flash atual
    corresponde ou não à célula target e expõe essa informação por callback.

Objetivo:
    Servir como base escalável para experiências P300 com gpype, sem
    depender do Paradigm Presenter.
"""

import gpype as gp
import random
import time

from PySide6.QtWidgets import QWidget, QPushButton, QGridLayout
from PySide6.QtCore import Qt, QTimer
from gpype.frontend.widgets.base.widget import Widget


class P300SingleCellGrid(Widget):
    def __init__(
        self,
        labels,
        rows,
        cols,
        title="P300 Single-Cell",
        flash_ms=150,
        isi_ms=150,
        rng_seed=None,
        avoid_immediate_repeat=True,
        target_idx=0,
        show_target_hint=True,
    ):
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
        self._running = False

        # índice da célula que o utilizador deve focar
        self.target_idx = int(target_idx)
        self.show_target_hint = bool(show_target_hint)

        # callback externo:
        # on_stimulus(idx, timestamp, is_target, label)
        self.on_stimulus = None

        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self._layout.addLayout(self.grid)

        self.buttons = []
        for i, txt in enumerate(labels):
            btn = QPushButton(txt)
            btn.setMinimumSize(240, 180)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setEnabled(False)
            btn.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))
            self.buttons.append(btn)

            r, c = divmod(i, self.cols)
            self.grid.addWidget(btn, r, c)

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)

    def _style(self, active: bool, is_target: bool):
        # estilo base
        if not active:
            if is_target and self.show_target_hint:
                return """
                QPushButton {
                    background: #7f7f7f;
                    color: white;
                    font-size: 52px;
                    border: 5px solid #ffd54f;
                    border-radius: 10px;
                }"""
            else:
                return """
                QPushButton {
                    background: #7f7f7f;
                    color: white;
                    font-size: 52px;
                    border: 3px solid #4a4a4a;
                    border-radius: 10px;
                }"""
        else:
            if is_target and self.show_target_hint:
                return """
                QPushButton {
                    background: #d9d9d9;
                    color: black;
                    font-size: 52px;
                    border: 10px solid #ffd54f;
                    border-radius: 10px;
                }"""
            else:
                return """
                QPushButton {
                    background: #b0b0b0;
                    color: black;
                    font-size: 52px;
                    border: 10px solid #ffffff;
                    border-radius: 10px;
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
        self._clear_all()
        self._pending_off = False
        self._running = True
        self._timer.start(self.isi_ms)

    def stop(self):
        self._timer.stop()
        self._clear_all()
        self._running = False

    def _tick(self):
        if not self._running:
            return

        if self._pending_off:
            return

        idx = self._pick_next_idx()
        is_target = idx == self.target_idx

        self.buttons[idx].setStyleSheet(self._style(active=True, is_target=is_target))

        if callable(self.on_stimulus):
            self.on_stimulus(
                idx,
                time.time(),
                is_target,
                self.buttons[idx].text()
            )

        self._pending_off = True
        QTimer.singleShot(self.flash_ms, self._flash_off)

    def _flash_off(self):
        self._clear_all()
        self._pending_off = False


def main():
    app = gp.MainApp()

    labels = [
        "NÃO", "SONO", "SIM",
        "STOP", "AJUDA", "TOSSE"
    ]

    grid = P300SingleCellGrid( 
    labels=labels,          # Lista de símbolos/textos que vão aparecer na grelha (ex: ["SIM", "NÃO", ...])
    rows=2,                 # Número de linhas da grelha (aqui: 2 linhas)
    cols=3,                 # Número de colunas da grelha (aqui: 3 colunas → total = 2x3 = 6 células)
    flash_ms=300,           # Tempo (em milissegundos) que cada célula fica "acesa" (flash)
    isi_ms=300,             # Intervalo entre flashes (Inter-Stimulus Interval), também em milissegundos
    title="P300 Single-Cell",  # Título da interface/janela apresentada ao utilizador
    target_idx=2,           # Índice do alvo (target) na lista labels (ex: 2 → terceiro elemento, "SIM")
    show_target_hint=True,  # Se True, mostra ao utilizador qual é o alvo a focar (útil em treino)
    )

    def stimulus_logger(idx, timestamp, is_target, label):
        kind = "TARGET" if is_target else "NONTARGET"
        print(f"[{timestamp:.3f}] idx={idx} label={label} tipo={kind}")

    grid.on_stimulus = stimulus_logger

    app.add_widget(grid)
    grid.start()
    app.run()
    grid.stop()


if __name__ == "__main__":
    main()
