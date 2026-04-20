import math

# Qt: Qt contém enums/flags; QTimer gere temporizações do flash
from PySide6.QtCore import Qt, QTimer

# Widgets usados para a interface:
# - QWidget: contentor base
# - QPushButton: cada célula da grelha
# - QGridLayout: layout da grelha
# - QLabel: texto do target atual no topo
from PySide6.QtWidgets import QWidget, QPushButton, QGridLayout, QLabel

# Widget base do gpype, para integrar esta interface na MainApp
from gpype.frontend.widgets.base.widget import Widget


class P300SingleCellGrid(Widget):
    """
    Grelha visual passiva do protótipo P300.

    Responsabilidade:
    - mostrar a grelha
    - mostrar o target atual no topo esquerdo
    - destacar o target
    - fazer o flash da célula indicada pelo controller

    Esta classe NÃO decide a sequência dos estímulos.
    O controller externo é que manda:
    - qual é o target atual
    - qual a célula que deve fazer flash
    - quando começar e terminar cada estímulo

    Portanto, esta camada é apenas visual.
    """

    def __init__(
        self,
        labels,
        title="P300 Single-Cell Grid",
        flash_ms=200,
        target_idx=0,
        show_target_hint=True,
    ):
        # Cria um contentor Qt base que será colocado dentro do Widget do gpype
        container = QWidget()

        # name=title define o nome/título interno deste widget no contexto do gpype
        super().__init__(widget=container, name=title)

        # labels:
        # lista de textos a mostrar nas células da grelha
        self.labels = list(labels)

        # flash_ms:
        # duração do estado ON de cada célula, em milissegundos
        self.flash_ms = int(flash_ms)

        # target_idx:
        # índice atual do target (base 0)
        self.target_idx = int(target_idx)

        # show_target_hint:
        # se True, o target fica visualmente destacado mesmo fora do flash
        self.show_target_hint = bool(show_target_hint)

        # Callbacks externos:
        # o controller pode atribuir funções a estes atributos
        # para ser notificado quando o estímulo começa e termina
        self.on_stimulus_start = None
        self.on_stimulus_end = None

        # Índice da célula atualmente em flash.
        # None significa que nenhuma célula está ativa no momento.
        self._current_idx = None

        # ---------------------------------------------------------
        # Label de texto do target atual
        # ---------------------------------------------------------
        # Esta label aparece no topo da interface e informa qual é o
        # target do trial atual.
        self.target_label = QLabel()
        self.target_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.target_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 22px;
                font-weight: bold;
                padding: 6px;
            }
        """)
        self._layout.addWidget(self.target_label)

        # ---------------------------------------------------------
        # Construção dinâmica da grelha
        # ---------------------------------------------------------
        # n = número de células/eventos visuais
        n = len(self.labels)

        # Número de colunas da grelha:
        # usa a raiz quadrada arredondada por excesso para tentar criar
        # uma grelha o mais "quadrada" possível
        cols = math.ceil(n ** 0.5)

        # Layout em grelha onde serão colocados os botões
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self._layout.addLayout(self.grid)

        # Lista que guarda todos os botões/células da grelha
        self.buttons = []

        # Criação dos botões da grelha
        for i, txt in enumerate(self.labels):
            # Se o texto for "<sem nome>", mostra vazio em vez do texto literal
            visual_text = "" if txt == "<sem nome>" else str(txt)

            # Cada célula é um botão desativado (não clicável pelo utilizador)
            btn = QPushButton(visual_text)
            btn.setMinimumSize(170, 110)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setEnabled(False)

            # Aplica estilo inicial consoante:
            # - a célula é target ou não
            # - está ativa ou não (inicialmente False)
            btn.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))

            # Guarda o botão na lista
            self.buttons.append(btn)

            # Calcula posição na grelha:
            # linha = i // cols
            # coluna = i % cols
            r = i // cols
            c = i % cols
            self.grid.addWidget(btn, r, c)

        # ---------------------------------------------------------
        # Timer de desligar o flash
        # ---------------------------------------------------------
        # Quando uma célula entra em flash, este timer espera flash_ms
        # e depois chama _flash_off().
        self._off_timer = QTimer()
        self._off_timer.setSingleShot(True)
        self._off_timer.timeout.connect(self._flash_off)

        # Atualiza o texto inicial do target
        self._update_target_text()

    def _target_name(self):
        """
        Devolve o nome/texto do target atual, com base em target_idx.
        """
        return self.labels[self.target_idx]

    def _update_target_text(self):
        """
        Atualiza a label superior que mostra o target atual.
        """
        self.target_label.setText(f"Target atual: {self._target_name()}")

    def _style(self, active: bool, is_target: bool):
        """
        Gera e devolve a stylesheet Qt para uma célula da grelha.

        Parâmetros:
        - active:
            True  -> célula está atualmente em flash
            False -> célula está em estado normal
        - is_target:
            True  -> esta célula corresponde ao target atual
            False -> célula normal

        Existem 4 combinações possíveis:
        1) normal + não target
        2) normal + target
        3) ativo + não target
        4) ativo + target
        """
        if not active:
            # Estado OFF
            if is_target and self.show_target_hint:
                # Estado OFF mas sendo target destacado
                return """
                QPushButton {
                    background: #6e6e6e;
                    color: white;
                    font-size: 24px;
                    font-weight: bold;
                    border: 5px solid #ffd54f;
                    border-radius: 10px;
                    padding: 10px;
                }"""
            # Estado OFF normal
            return """
            QPushButton {
                background: #6e6e6e;
                color: white;
                font-size: 24px;
                font-weight: bold;
                border: 3px solid #404040;
                border-radius: 10px;
                padding: 10px;
            }"""
        else:
            # Estado ON
            if is_target and self.show_target_hint:
                # Estado ON e target
                return """
                QPushButton {
                    background: #f0f0f0;
                    color: black;
                    font-size: 24px;
                    font-weight: bold;
                    border: 10px solid #ffd54f;
                    border-radius: 10px;
                    padding: 10px;
                }"""
            # Estado ON normal
            return """
            QPushButton {
                background: #f0f0f0;
                color: black;
                font-size: 24px;
                font-weight: bold;
                border: 10px solid #ffffff;
                border-radius: 10px;
                padding: 10px;
            }"""

    def set_target(self, idx: int):
        """
        Define qual é o target atual.

        O controller chama este método no início de cada trial.
        Depois:
        - atualiza target_idx
        - atualiza o texto superior
        - redesenha a grelha em estado OFF
        """
        self.target_idx = int(idx)
        self._update_target_text()
        self.clear_all()

    def clear_all(self):
        """
        Coloca todas as células em estado OFF.

        Cada botão recebe o estilo correspondente ao seu estado:
        - target destacado, se aplicável
        - célula normal, caso contrário
        """
        for i, b in enumerate(self.buttons):
            b.setStyleSheet(self._style(active=False, is_target=(i == self.target_idx)))

    def flash_cell(self, idx: int):
        """
        Faz o flash de uma célula específica.

        Este método é chamado pelo controller para iniciar um estímulo.

        Passos:
        1) limpa visualmente todas as células
        2) define a célula atual
        3) calcula se essa célula é target ou não
        4) aplica o estilo ON
        5) força repaint para aparecer imediatamente
        6) dispara callback on_stimulus_start, se existir
        7) arranca o timer que vai desligar o flash após flash_ms
        """
        # Garante que nenhuma outra célula fica visualmente ativa
        self.clear_all()

        # Guarda o índice da célula atualmente em flash
        self._current_idx = int(idx)

        # Determina se esta célula corresponde ao target atual
        is_target = self._current_idx == self.target_idx

        # Aplica o estilo visual ON à célula ativa
        self.buttons[self._current_idx].setStyleSheet(
            self._style(active=True, is_target=is_target)
        )

        # Força pintura imediata do botão antes do callback externo
        self.buttons[self._current_idx].repaint()

        # Se existir callback externo, informa o controller que o estímulo começou
        if callable(self.on_stimulus_start):
            self.on_stimulus_start(
                self._current_idx,
                is_target,
                self.labels[self._current_idx],
            )

        # Arranca o timer que vai chamar _flash_off() após flash_ms
        self._off_timer.start(self.flash_ms)

    def _flash_off(self):
        """
        Termina o flash atual.

        Passos:
        1) limpa visualmente a grelha
        2) dispara callback on_stimulus_end, se existir
        3) limpa o índice atual
        """
        # Coloca todas as células novamente em estado OFF
        self.clear_all()

        # Informa o controller que o estímulo terminou
        if callable(self.on_stimulus_end):
            self.on_stimulus_end()

        # Já não há célula ativa
        self._current_idx = None