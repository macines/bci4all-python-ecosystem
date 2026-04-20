from PySide6.QtWidgets import (
    QDialog,  # Janela de diálogo (popup modal)
    QVBoxLayout,  # Layout vertical (empilha elementos de cima para baixo)
    QFormLayout,  # Layout em formato formulário (label + input)
    QSpinBox,  # Campo numérico com setas (incrementa/decrementa)
    QLineEdit,  # Campo de texto simples
    QCheckBox,  # Caixa de seleção (checkbox)
    QPushButton,  # Botão
    QHBoxLayout,  # Layout horizontal (lado a lado)
    QMessageBox,  # Caixa de mensagens (avisos/erros)
)


class P300ExperimentSetupDialog(QDialog):
    """
    Janela inicial para configurar o ensaio P300.

    Objetivo:
    Permitir ao utilizador configurar parâmetros do experimento antes de iniciar.

    Inclui:
    - número de rondas por trial
    - duração do flash
    - intervalo entre eventos (ISI)
    - tempo entre trials
    - tempo entre início de gravação (START_CSV) e o 1º trial
    - sequência de targets
    - opção de destacar visualmente o target
    """

    def __init__(self):
        super().__init__()  # Inicializa a classe base QDialog

        self.setWindowTitle("Configuração do Ensaio P300")  # Define o título da janela
        self.setModal(True)  # Torna a janela modal (bloqueia interação com outras janelas)

        layout = QVBoxLayout(self)  # Layout principal vertical da janela
        form = QFormLayout()  # Layout tipo formulário (labels + inputs alinhados)

        # -------- ROUNDS POR TRIAL --------
        self.rounds_spin = QSpinBox()  # Campo numérico
        self.rounds_spin.setRange(1, 100)  # Limite mínimo e máximo
        self.rounds_spin.setValue(5)  # Valor inicial
        form.addRow("Rondas por trial:", self.rounds_spin)  # Adiciona ao formulário

        # -------- DURAÇÃO DO FLASH --------
        self.flash_spin = QSpinBox()
        self.flash_spin.setRange(10, 5000)  # 10 ms até 5 segundos
        self.flash_spin.setValue(200)  # Valor padrão
        form.addRow("Duração de Flash (ms):", self.flash_spin)

        # -------- INTER-STIMULUS INTERVAL (ISI) --------
        self.isi_spin = QSpinBox()
        self.isi_spin.setRange(10, 5000)
        self.isi_spin.setValue(100)
        form.addRow("Intervalo entre Eventos (ms):", self.isi_spin)

        # -------- TEMPO ENTRE TRIALS --------
        self.inter_trial_spin = QSpinBox()
        self.inter_trial_spin.setRange(10, 10000)
        self.inter_trial_spin.setValue(1000)
        form.addRow("Tempo entre trials (ms):", self.inter_trial_spin)

        # -------- PAUSA ENTRE START_CSV E O 1º TRIAL --------
        # Tempo que o sistema aguarda após iniciar a gravação (START_CSV)
        # antes de apresentar o primeiro estímulo do primeiro trial.
        # Permite ao utilizador estabilizar e focar-se antes do início.
        self.pre_start_delay_spin = QSpinBox()
        self.pre_start_delay_spin.setRange(0, 10000)
        self.pre_start_delay_spin.setValue(3000)
        form.addRow("Pausa após início de gravação (ms):", self.pre_start_delay_spin)

        # -------- SEQUÊNCIA DE TARGETS --------
        self.targets_edit = QLineEdit("1,2,3,4,5,6,7,8,9")
        # Campo de texto onde o utilizador define targets separados por vírgula
        form.addRow("Sequência de Targets (1..9):", self.targets_edit)

        # -------- OPÇÃO VISUAL DE HINT --------
        self.show_target_check = QCheckBox()
        self.show_target_check.setChecked(True)  # Ativado por defeito
        form.addRow("Destacar Target:", self.show_target_check)

        layout.addLayout(form)  # Adiciona o formulário ao layout principal

        # -------- BOTÕES --------
        buttons = QHBoxLayout()  # Layout horizontal para botões

        ok_btn = QPushButton("Iniciar")  # Botão para confirmar/iniciar
        cancel_btn = QPushButton("Cancelar")  # Botão para cancelar

        ok_btn.clicked.connect(self._validate_and_accept)  # Valida antes de aceitar
        cancel_btn.clicked.connect(self.reject)  # Fecha janela sem aceitar

        buttons.addWidget(ok_btn)  # Adiciona botão OK
        buttons.addWidget(cancel_btn)  # Adiciona botão Cancelar

        layout.addLayout(buttons)  # Adiciona botões à janela

    def _validate_and_accept(self):
        """
        Valida a configuração antes de fechar a janela.
        """
        try:
            _ = self.get_config()  # Tenta obter config (validação incluída)
            self.accept()  # Se tudo estiver OK, fecha com sucesso
        except ValueError as e:
            # Se houver erro, mostra mensagem ao utilizador
            QMessageBox.warning(self, "Configuração inválida", str(e))

    def get_config(self):
        """
        Converte os inputs da UI num dicionário de configuração válido.
        Também valida os dados inseridos.
        """

        raw_targets = self.targets_edit.text().strip()
        # Vai buscar o texto dos targets e remove espaços

        if not raw_targets:
            raise ValueError("A lista de targets não pode estar vazia.")

        try:
            targets = [int(x.strip()) for x in raw_targets.split(",") if x.strip()]
            # Converte string "1,2,3" numa lista de inteiros [1,2,3]
        except Exception:
            raise ValueError("Os targets devem ser inteiros separados por vírgulas.")

        if not targets:
            raise ValueError("A lista de targets não pode estar vazia.")

        invalid_targets = [t for t in targets if t < 1 or t > 9]
        if invalid_targets:
            raise ValueError(f"Há targets fora do intervalo 1..9: {invalid_targets}")

        # Retorna configuração final como dicionário
        return {
            "num_events": 9,                                            # Número fixo de estímulos na grelha
            "rounds_per_trial": self.rounds_spin.value(),               # Rondas por trial
            "flash_ms": self.flash_spin.value(),                        # Duração do flash
            "isi_ms": self.isi_spin.value(),                            # Intervalo entre eventos
            "inter_trial_ms": self.inter_trial_spin.value(),            # Pausa entre trials
            "pre_start_delay_ms": self.pre_start_delay_spin.value(),    # Pausa após START_CSV antes do 1º trial
            "targets": targets,                                         # Lista de targets validada
            "show_target_hint": self.show_target_check.isChecked(),     # Se mostra dica visual
        }