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

import gpype as gp        # Framework principal (gestão da app e widgets)
import random             # Para gerar sequência aleatória de flashes
import time               # Para timestamps dos estímulos

from PySide6.QtWidgets import QWidget, QPushButton, QGridLayout  # Elementos UI
from PySide6.QtCore import Qt, QTimer  # Constantes UI e temporizadores
from gpype.frontend.widgets.base.widget import Widget  # Classe base gpype


class P300SingleCellGrid(Widget):
    def __init__(
        self,
        labels,                    # Lista de textos nas células
        rows,                      # Número de linhas
        cols,                      # Número de colunas
        title="P300 Single-Cell",  # Título da janela
        flash_ms=150,              # Duração do flash (ms)
        isi_ms=150,                # Intervalo entre estímulos (ms)
        rng_seed=None,             # Seed para aleatoriedade (reprodutibilidade)
        avoid_immediate_repeat=True,  # Evita repetir mesma célula seguida
        target_idx=0,              # Índice da célula alvo
        show_target_hint=True,     # Mostrar dica visual do target
    ):
        container = QWidget()  # Widget base Qt
        super().__init__(widget=container, name=title)  # Inicialização gpype

        # --- Configuração da grid ---
        self.rows = int(rows)
        self.cols = int(cols)
        self.flash_ms = int(flash_ms)
        self.isi_ms = int(isi_ms)
        self.avoid_immediate_repeat = bool(avoid_immediate_repeat)

        # --- Gerador aleatório ---
        self._rng = random.Random(rng_seed)  # Permite controlo da sequência
        self._last_idx = None               # Guarda último índice mostrado
        self._pending_off = False           # Indica se há flash ativo
        self._running = False               # Estado da grid

        # --- Target ---
        self.target_idx = int(target_idx)   # Índice da célula alvo
        self.show_target_hint = bool(show_target_hint)  # Mostrar hint visual

        # --- Callback externo ---
        # Esperado: on_stimulus(idx, timestamp, is_target, label)
        self.on_stimulus = None

        # --- Layout da grid ---
        self.grid = QGridLayout()
        self.grid.setSpacing(8)  # Espaçamento entre botões
        self._layout.addLayout(self.grid)

        # --- Criação dos botões ---
        self.buttons = []
        for i, txt in enumerate(labels):
            btn = QPushButton(txt)  # Cria botão com texto
            btn.setMinimumSize(240, 180)  # Tamanho mínimo
            btn.setFocusPolicy(Qt.NoFocus)  # Remove foco teclado
            btn.setEnabled(False)  # Desativa interação do utilizador

            # Define estilo inicial
            btn.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))
            self.buttons.append(btn)

            # Calcula posição (linha, coluna)
            r, c = divmod(i, self.cols)
            self.grid.addWidget(btn, r, c)  # Adiciona à grid

        # --- Timer principal ---
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)  # Chama _tick a cada intervalo

    def _style(self, active: bool, is_target: bool):
        # Define estilo visual dos botões

        if not active:
            # Estado "apagado"
            if is_target and self.show_target_hint:
                return """
                QPushButton {
                    background: #7f7f7f;
                    color: white;
                    font-size: 52px;
                    border: 5px solid #ffd54f;   /* Destaque do target */
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
            # Estado "ativo" (flash)
            if is_target and self.show_target_hint:
                return """
                QPushButton {
                    background: #d9d9d9;
                    color: black;
                    font-size: 52px;
                    border: 10px solid #ffd54f;  /* Flash + destaque */
                    border-radius: 10px;
                }"""
            else:
                return """
                QPushButton {
                    background: #b0b0b0;
                    color: black;
                    font-size: 52px;
                    border: 10px solid #ffffff;  /* Flash normal */
                    border-radius: 10px;
                }"""

    def set_target(self, idx: int):
        self.target_idx = int(idx)  # Atualiza target
        self._clear_all()           # Atualiza estilos

    def _clear_all(self):
        # Apaga todos os flashes (estado base)
        for i, b in enumerate(self.buttons):
            b.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))

    def _pick_next_idx(self):
        # Escolhe próxima célula aleatória
        n = len(self.buttons)
        idx = self._rng.randrange(n)

        # Evita repetição imediata
        if self.avoid_immediate_repeat and self._last_idx is not None and n > 1:
            while idx == self._last_idx:
                idx = self._rng.randrange(n)

        self._last_idx = idx
        return idx

    def start(self):
        # Inicia sequência de flashes
        self._clear_all()
        self._pending_off = False
        self._running = True
        self._timer.start(self.isi_ms)  # Timer baseado no ISI

    def stop(self):
        # Para sequência
        self._timer.stop()
        self._clear_all()
        self._running = False

    def _tick(self):
        # Chamado a cada ciclo do timer
        if not self._running:
            return

        if self._pending_off:
            return  # Espera terminar flash anterior

        idx = self._pick_next_idx()  # Escolhe célula
        is_target = idx == self.target_idx  # Verifica se é target

        # Ativa visualmente
        self.buttons[idx].setStyleSheet(self._style(active=True, is_target=is_target))

        # Callback externo (ex: controlador)
        if callable(self.on_stimulus):
            self.on_stimulus(
                idx,
                time.time(),
                is_target,
                self.buttons[idx].text()
            )

        # Agenda desligar flash
        self._pending_off = True
        QTimer.singleShot(self.flash_ms, self._flash_off)

    def _flash_off(self):
        # Desliga flash atual
        self._clear_all()
        self._pending_off = False


def main():
    app = gp.MainApp()  # Inicializa app

    labels = [
        "NÃO", "SONO", "SIM",
        "STOP", "AJUDA", "TOSSE"
    ]

    # Criação da grid
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

    # Função callback para logging
    def stimulus_logger(idx, timestamp, is_target, label):
        kind = "TARGET" if is_target else "NONTARGET"
        print(f"[{timestamp:.3f}] idx={idx} label={label} tipo={kind}")

    grid.on_stimulus = stimulus_logger  # Liga callback

    app.add_widget(grid)  # Adiciona à app
    grid.start()          # Inicia flashes
    app.run()             # Loop principal
    grid.stop()           # Garante paragem no fim


if __name__ == "__main__":
    main()  # Entry point
