"""
Nome do ficheiro:
    p300_single_cell_grid.py

Descrição:
    Camada 1 do protótipo P300.

    Este ficheiro implementa o widget visual do paradigma P300:
    - uma grelha 3x3
    - cada célula pode fazer flash individualmente
    - existe uma célula alvo (target)
    - o widget apenas trata da apresentação visual

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

# Biblioteca para geração pseudoaleatória da próxima célula a fazer flash
import random

# Biblioteca usada para obter timestamps em segundos
import time

# Componentes do Qt
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QPushButton, QGridLayout

# Classe base Widget do gpype, usada para integrar este componente na UI gpype
from gpype.frontend.widgets.base.widget import Widget


class P300SingleCellGrid(Widget):
    """
    Widget visual para um paradigma P300 de célula única.

    Ideia:
        - existe uma grelha com várias células (botões)
        - apenas uma célula de cada vez "pisca"
        - a célula alvo pode ser destacada visualmente
        - o widget avisa o exterior quando o flash começa e termina

    O controller externo é responsável por:
        - iniciar/parar a sequência
        - receber os callbacks
        - enviar triggers / eventos
        - controlar a lógica experimental
    """

    def __init__(
        self,
        labels,                     # lista de textos a mostrar nas células
        rows,                       # número de linhas da grelha
        cols,                       # número de colunas da grelha
        title="P300 Single-Cell Grid",   # nome da janela/widget
        flash_ms=200,               # duração do flash ON em milissegundos
        isi_ms=100,                 # intervalo OFF entre flashes em milissegundos
        rng_seed=None,              # seed opcional para reproduzir sequência pseudoaleatória
        avoid_immediate_repeat=True, # evita que a mesma célula repita logo a seguir
        target_idx=0,               # índice da célula alvo
        show_target_hint=True,      # se True, o target aparece destacado mesmo fora do flash
    ):
        # Cria um container base Qt que será o conteúdo gráfico do Widget gpype
        container = QWidget()

        # Inicializa a classe Widget do gpype
        # widget=container -> o conteúdo gráfico
        # name=title       -> nome/título do widget
        super().__init__(widget=container, name=title)

        # Guarda a lista de labels
        self.labels = list(labels)

        # Guarda nº de linhas e colunas como inteiros
        self.rows = int(rows)
        self.cols = int(cols)

        # Guarda os tempos de flash e intervalo em milissegundos
        self.flash_ms = int(flash_ms)
        self.isi_ms = int(isi_ms)

        # Define se devemos impedir repetição imediata da mesma célula
        self.avoid_immediate_repeat = bool(avoid_immediate_repeat)

        # Gerador pseudoaleatório próprio do widget
        # usar random.Random permite ter controlo via seed
        self._rng = random.Random(rng_seed)

        # Índice da última célula que fez flash
        # serve para evitar repetição imediata, se ativado
        self._last_idx = None

        # Flag interna que indica se a sequência está a correr
        self._running = False

        # Índice da célula atualmente ativa (em flash)
        self._current_idx = None

        # Índice da célula alvo
        self.target_idx = int(target_idx)

        # Define se o alvo deve ser visualmente assinalado
        self.show_target_hint = bool(show_target_hint)

        # -------------------------
        # CALLBACKS EXTERNOS
        # -------------------------
        # Estes atributos podem ser definidos pelo controller externo.
        #
        # on_stimulus_start(idx, timestamp, is_target, label)
        #   -> chamado quando um flash começa
        #
        # on_stimulus_end(timestamp)
        #   -> chamado quando um flash termina
        self.on_stimulus_start = None
        self.on_stimulus_end = None

        # Cria layout em grelha para organizar os botões
        self.grid = QGridLayout()

        # Espaçamento entre células
        self.grid.setSpacing(8)

        # Adiciona a grelha ao layout principal do widget gpype
        # self._layout vem da classe base Widget
        self._layout.addLayout(self.grid)

        # Lista que vai guardar os botões da grelha
        self.buttons = []

        # Criação de uma célula/botão por cada label
        for i, txt in enumerate(self.labels):
            # Cria o botão com o texto da célula
            btn = QPushButton(str(txt))

            # Define tamanho mínimo do botão
            btn.setMinimumSize(220, 140)

            # Remove foco por teclado para não ficar com highlight estranho
            btn.setFocusPolicy(Qt.NoFocus)

            # Desativa o botão: ele serve apenas como elemento visual
            btn.setEnabled(False)

            # Aplica o estilo inicial (estado OFF)
            # se esta célula for target, o estilo pode refletir isso
            btn.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))

            # Guarda o botão na lista
            self.buttons.append(btn)

            # Calcula linha e coluna na grelha a partir do índice linear
            r, c = divmod(i, self.cols)

            # Adiciona o botão à grelha
            self.grid.addWidget(btn, r, c)

        # -------------------------
        # TIMERS
        # -------------------------
        # _flash_timer:
        #   usado para esperar o intervalo OFF (isi_ms) antes de ligar novo flash
        self._flash_timer = QTimer()
        self._flash_timer.setSingleShot(True)  # dispara só uma vez
        self._flash_timer.timeout.connect(self._flash_on)

        # _off_timer:
        #   usado para manter o flash ligado durante flash_ms e depois desligá-lo
        self._off_timer = QTimer()
        self._off_timer.setSingleShot(True)  # dispara só uma vez
        self._off_timer.timeout.connect(self._flash_off)

    def _style(self, active: bool, is_target: bool):
        """
        Gera a stylesheet CSS do botão consoante:
            - active: se a célula está em flash
            - is_target: se a célula é a célula alvo

        Existem quatro casos principais:
            1. OFF normal
            2. OFF target
            3. ON normal
            4. ON target
        """

        # Estado OFF (sem flash)
        if not active:
            # Se for target e quisermos mostrar hint visual
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
            # Estado OFF normal
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

        # Estado ON (flash ativo)
        else:
            # Se for target e houver hint, realça ainda mais
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
            # Estado ON normal
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
        """
        Define qual é a célula alvo.

        Isto permite ao controller alterar dinamicamente o target.
        Depois de mudar o target, o widget volta a desenhar tudo em estado OFF.
        """
        self.target_idx = int(idx)
        self._clear_all()

    def _clear_all(self):
        """
        Coloca todas as células no estado OFF.

        Se show_target_hint estiver ativo, o target continua visualmente destacado,
        mas não em estado de flash.
        """
        for i, b in enumerate(self.buttons):
            b.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))

    def _pick_next_idx(self):
        """
        Escolhe o próximo índice a fazer flash.

        Regras:
            - escolhe aleatoriamente entre todas as células
            - se avoid_immediate_repeat=True, evita repetir a mesma célula
              logo a seguir à anterior
        """
        # Número total de botões/células
        n = len(self.buttons)

        # Escolha aleatória inicial
        idx = self._rng.randrange(n)

        # Se queremos evitar repetição imediata, e houver pelo menos 2 células,
        # sorteia novamente enquanto calhar o mesmo índice da anterior
        if self.avoid_immediate_repeat and self._last_idx is not None and n > 1:
            while idx == self._last_idx:
                idx = self._rng.randrange(n)

        # Guarda o último índice escolhido
        self._last_idx = idx

        return idx

    def start(self):
        """
        Inicia a sequência de flashes.

        Fluxo:
            1. garante que qualquer estado anterior é parado/resetado
            2. ativa a flag _running
            3. limpa a grelha
            4. espera primeiro isi_ms
            5. depois começa o primeiro flash

        Nota:
            o primeiro flash não aparece imediatamente;
            primeiro respeita-se o intervalo OFF.
        """
        self.stop()                  # limpa qualquer execução anterior
        self._running = True         # ativa a sequência
        self._current_idx = None     # nenhuma célula ativa neste momento
        self._clear_all()            # repõe todas as células em OFF

        # espera o primeiro intervalo OFF antes do primeiro flash
        self._flash_timer.start(self.isi_ms)

    def stop(self):
        """
        Pára completamente a sequência de flashes.

        Efeitos:
            - desativa running
            - remove célula atual
            - pára ambos os timers
            - limpa visualmente a grelha
        """
        self._running = False
        self._current_idx = None
        self._flash_timer.stop()
        self._off_timer.stop()
        self._clear_all()

    def _flash_on(self):
        """
        Liga o flash de uma célula.

        Este método é chamado automaticamente quando o _flash_timer expira.

        Passos:
            1. verifica se ainda estamos em execução
            2. escolhe próxima célula
            3. ativa o estilo ON dessa célula
            4. chama callback de início
            5. arma o timer para desligar após flash_ms
        """
        if not self._running:
            return

        # Escolhe qual célula vai piscar agora
        idx = self._pick_next_idx()
        self._current_idx = idx

        # Verifica se esta célula é o target
        is_target = idx == self.target_idx

        # Aplica estilo visual de flash ON
        self.buttons[idx].setStyleSheet(self._style(active=True, is_target=is_target))

        # Força atualização visual imediata
        # útil para minimizar atraso visual antes do callback/timestamp
        self.buttons[idx].repaint()

        # Timestamp de início do estímulo
        ts = time.time()

        # Se existir callback externo, chama-o
        # envia:
        #   idx       -> índice da célula
        #   ts        -> timestamp do início
        #   is_target -> se é target
        #   label     -> texto da célula
        if callable(self.on_stimulus_start):
            self.on_stimulus_start(
                idx,
                ts,
                is_target,
                self.buttons[idx].text()
            )

        # Agenda o fim do flash após flash_ms
        self._off_timer.start(self.flash_ms)

    def _flash_off(self):
        """
        Desliga o flash atual.

        Este método é chamado automaticamente quando o _off_timer expira.

        Passos:
            1. apaga visualmente a célula ativa
            2. chama callback de fim
            3. limpa _current_idx
            4. se ainda estiver a correr, agenda o próximo flash após isi_ms
        """
        # Se existir célula ativa, limpa a grelha
        if self._current_idx is not None:
            self._clear_all()

        # Timestamp de fim do estímulo
        ts = time.time()

        # Se existir callback externo, chama-o
        if callable(self.on_stimulus_end):
            self.on_stimulus_end(ts)

        # Já não há célula ativa
        self._current_idx = None

        # Se o widget continuar a correr, agenda o próximo ciclo
        if self._running:
            self._flash_timer.start(self.isi_ms)

    def keyPressEvent(self, event):
        """
        Reencaminha eventos de teclado para a classe base.

        Neste momento não há lógica personalizada para teclas,
        mas o método foi mantido para possível expansão futura,
        por exemplo:
            - tecla para start/stop
            - tecla para trocar target
            - tecla de emergência para abortar
        """
        super().keyPressEvent(event)