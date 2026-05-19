""" 
Controller P300 com stream LSL contínuo de eventos.

Streams LSL:
- P300_Events  -> contínuo, 2 canais float32 [code, trigger]
- P300_Control -> irregular, strings START_CSV / STOP_CSV

"""

# =============================================================
# SECÇÃO 1 — IMPORTS STANDARD / UTILITÁRIOS
# Módulos da biblioteca padrão do Python usados neste ficheiro.
# =============================================================

import json
# json: permite converter dicionários Python em texto JSON e vice-versa.
# Usado para guardar os metadados da sessão (utilizador, condição, hora)
# num ficheiro .json legível por humanos e por outros programas.

import os
# os: interface com o sistema operativo.
# Usado aqui para:
#   - definir variáveis de ambiente (os.environ) que o pipeline filho lê
#   - copiar as variáveis de ambiente para o processo filho (os.environ.copy())

import random
# random: geração de números pseudoaleatórios.
# Usado para criar o gerador local (random.Random) que baralha a sequência
# de estímulos de cada trial de forma reprodutível (com seed fixa).

import re
# re: expressões regulares.
# Usado exclusivamente para validar o formato do ID do utilizador,
# garantindo que só contém caracteres seguros para nomes de pastas/ficheiros.

import subprocess
# subprocess: criação e gestão de processos filhos.
# Usado para lançar o pipeline de processamento EEG como um processo
# independente (subprocess.Popen), separado do processo do controller.

import sys
# sys: acesso a parâmetros e funções do interpretador Python.
# Usado para obter o caminho do executável Python atual (sys.executable),
# garantindo que o pipeline filho usa o mesmo ambiente virtual.

import time
# time: utilitários temporais standard.
# Usado apenas para time.sleep() na espera por consumidores LSL ligados,
# evitando que o ciclo de polling consuma 100% de CPU.

from datetime import datetime
# datetime: representação e manipulação de datas e horas.
# Usado para gerar o timestamp do nome da pasta/ficheiro de saída
# e para registar a hora de criação nos metadados da sessão.

from pathlib import Path
# Path: manipulação de caminhos de ficheiros de forma independente do SO.
# Preferido a os.path porque oferece uma API mais legível e robusta,
# especialmente em Windows onde os separadores de path diferem.


# =============================================================
# SECÇÃO 2 — IMPORTS LSL / Qt
# Bibliotecas de comunicação LSL e interface gráfica Qt.
# =============================================================

from pylsl import StreamInfo, StreamOutlet, local_clock
# pylsl: biblioteca Python para o protocolo Lab Streaming Layer (LSL).
#
# StreamInfo: descreve um stream LSL (nome, tipo, canais, frequência, formato).
#   Funciona como um "cabeçalho" que anuncia o stream na rede local.
#
# StreamOutlet: publica dados num stream LSL já descrito por um StreamInfo.
#   É o objeto que efetivamente envia amostras para outros processos/máquinas.
#
# local_clock: devolve o tempo atual no relógio LSL (segundos desde epoch LSL).
#   Todos os timestamps de eventos e amostras usam este relógio para garantir
#   sincronização entre processos diferentes.

from PySide6.QtCore import QTimer, QCoreApplication, Qt
# PySide6.QtCore: módulo central do Qt sem componentes visuais.
#
# QTimer: temporizador assíncrono do Qt.
#   Usado extensivamente para agendar ações futuras (flash, ISI, trials)
#   sem bloquear o event loop — a alternativa seria time.sleep(), que
#   bloquearia toda a interface gráfica.
#
# QCoreApplication: representa a aplicação Qt ao nível do núcleo.
#   Usado aqui apenas para chamar QCoreApplication.quit(), que termina
#   o event loop principal quando o ensaio acaba.
#
# Qt: namespace com enumerações e constantes do Qt (ex: Qt.AlignCenter).
#   Usado para alinhar elementos visuais nos layouts.

from PySide6.QtWidgets import (
    QDialog,        # Janela de diálogo modal/não-modal. Base de todas as janelas popup.
    QApplication,   # Representa a aplicação Qt com interface gráfica. Gere o event loop.
    QVBoxLayout,    # Layout que empilha widgets verticalmente (de cima para baixo).
    QHBoxLayout,    # Layout que coloca widgets lado a lado horizontalmente.
    QFormLayout,    # Layout em duas colunas: label à esquerda, widget à direita.
    QLabel,         # Widget de texto estático, não editável. Usado para títulos e labels.
    QPushButton,    # Botão clicável. Liga-se a funções via .clicked.connect().
    QLineEdit,      # Campo de texto de linha única editável pelo utilizador.
    QCheckBox,      # Caixa de seleção com dois estados: marcada ou desmarcada.
    QMessageBox,    # Caixa de diálogo para mostrar mensagens de erro, aviso ou info.
    QWidget,        # Widget base genérico. Usado como contentor para outros widgets.
)


# =============================================================
# SECÇÃO 3 — IMPORTS DO GPYPE E MÓDULOS DO PROJETO
# Framework de processamento e módulos desenvolvidos para este projeto.
# =============================================================

import gpype as gp
# gpype: framework de processamento de sinal em pipeline para BCI.
# Fornece a aplicação principal (gp.MainApp), nós de processamento
# (gp.Bandpass, gp.Generator, etc.) e widgets visuais (gp.TimeSeriesScope).
# Importado como 'gp' para abreviar as referências ao longo do código.

from p300_experiment_setup import P300ExperimentSetupDialog
# P300ExperimentSetupDialog: janela de configuração do ensaio P300.
# Permite ao utilizador definir parâmetros como número de rondas,
# duração do flash, ISI, targets, etc., antes de iniciar o ensaio.
# Está definida no ficheiro p300_experiment_setup.py da mesma pasta.

from p300_single_cell_grid import P300SingleCellGrid
# P300SingleCellGrid: widget visual da grelha 3x3 do P300.
# Cada célula corresponde a uma palavra/símbolo comunicativo.
# O controller manda-lhe fazer flash de células específicas;
# a grelha é passiva e não decide nada por conta própria.
# Está definida no ficheiro p300_single_cell_grid.py da mesma pasta.

from p300_sequence import gera_seq_aleatoria
# gera_seq_aleatoria: função que gera a sequência de índices de estímulos
# para um trial completo. Garante que cada célula aparece exatamente uma
# vez por round, em ordem aleatória controlada pelo gerador rng passado.
# Está definida no ficheiro p300_sequence.py da mesma pasta.


# =============================================================
# SECÇÃO 4 — CONSTANTES GLOBAIS
# Valores fixos usados em todo o ficheiro.
# =============================================================

FIXED_LABELS = [
    "Sim", "Sono", "TV",      # linha 1 da grelha 3x3
    "Fome", "Sede", "Não",    # linha 2 da grelha 3x3
    "Ajuda", "Tosse", "Stop", # linha 3 da grelha 3x3
]
# FIXED_LABELS: lista com os 9 textos das células da grelha P300.
# A posição na lista corresponde ao índice da célula (base 0).
# O índice 0 = "Sim", índice 8 = "Stop".
# São fixos porque a grelha atual é sempre 3x3 com estas palavras.

EVENT_SAMPLING_RATE = 250
# EVENT_SAMPLING_RATE: frequência de amostragem do stream contínuo P300_Events,
# em amostras por segundo (Hz).
# A cada 1/250 = 4 ms, o LSLContinuousEventSender envia uma amostra
# com o estado atual [code, trigger] para o stream LSL.
# Valor escolhido para coincidir com a frequência do EEG (250 Hz),
# facilitando o alinhamento temporal na análise posterior.


# =============================================================
# CLASSE 1 — MainMenuDialog
# Primeiro ecrã da aplicação. Recolhe condição e ID do utilizador.
# =============================================================

class MainMenuDialog(QDialog):
    """
    Menu principal da aplicação.

    É o primeiro diálogo que o utilizador vê ao correr o programa.
    Recolhe dois dados essenciais antes de avançar:
    - a condição experimental (offline ou online)
    - o ID do utilizador (usado para nomear a pasta de saída)
    """

    def __init__(self):
        # Chama o construtor da classe base QDialog,
        # inicializando a janela de diálogo Qt.
        super().__init__()

        # Define o texto que aparece na barra de título da janela.
        self.setWindowTitle("Projeto Final BCI4ALL")

        # setModal(True): enquanto este diálogo estiver aberto,
        # o utilizador não pode interagir com outras janelas da aplicação.
        self.setModal(True)

        # Garante uma largura mínima de 420 px para o diálogo não ficar estreito.
        self.setMinimumWidth(420)

        # layout: layout vertical principal que empilha todos os elementos
        # do diálogo de cima para baixo.
        layout = QVBoxLayout(self)

        # title: label com o nome do projeto em destaque no topo do diálogo.
        # setAlignment(Qt.AlignCenter): centra o texto horizontalmente.
        # setStyleSheet: aplica CSS para aumentar o tamanho e peso da fonte.
        title = QLabel("Projeto Final BCI4ALL")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # subtitle: instrução breve por baixo do título principal.
        subtitle = QLabel("Selecione a condição e introduza o ID do Utilizador")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; margin-bottom: 12px;")
        layout.addWidget(subtitle)

        # form: layout de formulário com duas colunas (label + widget).
        # Organiza os campos de entrada de forma alinhada e legível.
        form = QFormLayout()

        # offline_check / online_check: caixas de seleção para a condição experimental.
        # São mutuamente exclusivas — apenas uma pode estar ativa de cada vez.
        # A exclusividade é implementada manualmente via callbacks toggled,
        # porque QCheckBox não tem modo de exclusividade nativa como QRadioButton.
        self.offline_check = QCheckBox("Offline")
        self.online_check = QCheckBox("Online")

        # Por defeito, a condição offline fica selecionada ao abrir o diálogo.
        self.offline_check.setChecked(True)

        # Liga o sinal toggled (emitido quando o estado muda) aos métodos
        # que impõem a exclusividade entre os dois checkboxes.
        self.offline_check.toggled.connect(self._on_offline_toggled)
        self.online_check.toggled.connect(self._on_online_toggled)

        # cond_widget: widget contentor usado apenas para colocar
        # os dois checkboxes lado a lado num layout horizontal.
        cond_widget = QWidget()
        cond_layout = QHBoxLayout(cond_widget)
        cond_layout.setContentsMargins(0, 0, 0, 0)  # sem margens internas
        cond_layout.setSpacing(16)                   # 16 px de espaço entre checkboxes
        cond_layout.addWidget(self.offline_check)
        cond_layout.addWidget(self.online_check)

        # Adiciona a linha "Condição:" ao formulário.
        form.addRow("Condição:", cond_widget)

        # user_id_edit: campo de texto onde o utilizador escreve o seu identificador.
        # O valor inicial "User01" é apenas uma sugestão que pode ser apagada.
        self.user_id_edit = QLineEdit("User01")
        form.addRow("ID do Utilizador:", self.user_id_edit)

        # Adiciona o formulário ao layout principal vertical.
        layout.addLayout(form)

        # buttons: layout horizontal para os botões de ação no fundo do diálogo.
        buttons = QHBoxLayout()

        # next_btn: botão principal que valida os dados e avança para o setup.
        self.next_btn = QPushButton("Avançar")

        # cancel_btn: botão que fecha o diálogo sem aceitar (resultado = Rejected).
        self.cancel_btn = QPushButton("Cancelar")

        # Liga o clique do botão "Avançar" ao método de validação.
        self.next_btn.clicked.connect(self._validate_and_accept)

        # Liga o clique do botão "Cancelar" ao método reject() herdado de QDialog.
        # reject() fecha o diálogo e devolve QDialog.Rejected ao chamador.
        self.cancel_btn.clicked.connect(self.reject)

        buttons.addWidget(self.next_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

    def _on_offline_toggled(self, checked: bool):
        """
        Callback chamado sempre que o estado do checkbox Offline muda.

        checked: True se o checkbox ficou marcado, False se ficou desmarcado.

        Lógica de exclusividade:
        - Se Offline ficou marcado -> desmarca Online.
        - Se Offline ficou desmarcado e Online também está desmarcado
          -> volta a marcar Offline (nunca deixa ambos desmarcados).
        """
        if checked:
            self.online_check.setChecked(False)
        elif not self.online_check.isChecked():
            self.offline_check.setChecked(True)

    def _on_online_toggled(self, checked: bool):
        """
        Callback simétrico ao anterior, para o checkbox Online.

        checked: True se Online foi marcado, False se foi desmarcado.
        """
        if checked:
            self.offline_check.setChecked(False)
        elif not self.offline_check.isChecked():
            self.online_check.setChecked(True)

    def _validate_and_accept(self):
        """
        Tenta ler e validar os dados do formulário antes de fechar o diálogo.

        Se get_config() não lançar exceção -> aceita o diálogo (Accepted).
        Se lançar ValueError -> mostra aviso e mantém o diálogo aberto.
        """
        try:
            _ = self.get_config()
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Configuração inválida", str(e))

    def get_config(self):
        """
        Lê e valida os dados do diálogo, devolvendo um dicionário.

        Validações:
        - O ID do utilizador não pode estar vazio.
        - O ID só pode conter letras, números, '_' e '-'.

        Retorna:
        - "condition": "offline" ou "online"
        - "user_id":   string validada com o identificador do utilizador
        """
        # Lê o texto do campo e remove espaços no início e fim.
        user_id = self.user_id_edit.text().strip()

        # Validação 1: campo não pode estar vazio.
        if not user_id:
            raise ValueError("O ID do Utilizador não pode estar vazio.")

        # Validação 2: só caracteres seguros para nomes de pastas.
        # re.fullmatch exige que TODA a string corresponda ao padrão.
        if not re.fullmatch(r"[A-Za-z0-9_-]+", user_id):
            raise ValueError(
                "O ID do Utilizador só pode conter letras, números, '_' e '-'."
            )

        # Determina a condição com base em qual checkbox está marcada.
        condition = "offline" if self.offline_check.isChecked() else "online"

        return {
            "condition": condition,
            "user_id": user_id,
        }


# =============================================================
# CLASSE 2 — LSLContinuousEventSender
# Publica continuamente o estado atual do estímulo no stream P300_Events.
# =============================================================

class LSLContinuousEventSender:
    """
    Publica continuamente um stream LSL com 2 canais float32:
    - canal 1 (code):    índice da célula em flash (1..9), ou 0 se nenhuma.
    - canal 2 (trigger): 1 se a célula em flash é o target, 0 caso contrário.

    A publicação é contínua (a cada 4 ms para 250 Hz), mesmo quando não há
    estímulo ativo — nesse caso envia [0, 0].
    Esta abordagem permite ao pipeline EEG ter sempre um valor alinhado
    temporalmente com cada amostra de EEG, sem depender de eventos esparsos.
    """

    def __init__(self, sampling_rate=EVENT_SAMPLING_RATE):
        # sampling_rate: número de amostras por segundo a publicar no stream.
        self.sampling_rate = int(sampling_rate)

        # StreamInfo: descreve o stream LSL que vai ser publicado.
        # name="P300_Events": nome pelo qual outros processos o encontram.
        # channel_count=2: dois canais (code e trigger).
        # nominal_srate: frequência nominal declarada (250.0 Hz).
        # channel_format="float32": cada amostra é um par de floats de 32 bits.
        # source_id: identificador único desta fonte, evita colisões de streams.
        info = StreamInfo(
            name="P300_Events",
            type="Markers",
            channel_count=2,
            nominal_srate=float(self.sampling_rate),
            channel_format="float32",
            source_id="p300_events_continuous_v1",
        )

        # outlet: objeto que efetivamente envia amostras para o stream LSL.
        self.outlet = StreamOutlet(info)

        # current_code: valor atual do canal 1 (índice da célula em flash, 1..9).
        # Começa em 0.0 (nenhuma célula ativa).
        self.current_code = 0.0

        # current_trigger: valor atual do canal 2 (1 = target, 0 = não-target).
        # Começa em 0.0 (sem estímulo ativo).
        self.current_trigger = 0.0

        # timer: temporizador Qt que dispara periodicamente para enviar amostras.
        # timeout.connect liga o sinal de disparo ao método _push_sample.
        self.timer = QTimer()
        self.timer.timeout.connect(self._push_sample)

        # Calcula o intervalo do timer em ms a partir do sampling_rate.
        # max(1, ...) garante que o intervalo nunca é inferior a 1 ms.
        self.timer.start(max(1, int(round(1000 / self.sampling_rate))))

    def _push_sample(self):
        """
        Chamado pelo timer a cada intervalo (≈4 ms para 250 Hz).
        Envia uma amostra LSL com o estado atual [current_code, current_trigger].
        O timestamp local_clock() é o relógio LSL partilhado entre processos.
        """
        ts = local_clock()  # timestamp LSL do momento exato de envio
        self.outlet.push_sample(
            [float(self.current_code), float(self.current_trigger)],
            timestamp=ts,
        )

    def set_event(self, code: float, trigger: float):
        """
        Atualiza o estado interno para refletir um estímulo ativo.

        code:    índice 1-based da célula atualmente em flash.
        trigger: 1.0 se é o target do trial, 0.0 caso contrário.

        A partir deste momento, o timer publica estes valores
        até clear_event() ser chamado.
        """
        self.current_code = float(code)
        self.current_trigger = float(trigger)
        print(f"[LSL][EVENTS] ON  code={self.current_code}, trigger={self.current_trigger}")

    def clear_event(self):
        """
        Repõe o estado interno para [0, 0].
        Sinaliza ao pipeline que estamos no período OFF/ISI (sem estímulo).
        O timer contínua a publicar, mas com valores nulos.
        """
        self.current_code = 0.0
        self.current_trigger = 0.0
        print("[LSL][EVENTS] OFF code=0, trigger=0")


# =============================================================
# CLASSE 3 — LSLControlSender
# Envia comandos de controlo ao pipeline via stream LSL irregular.
# =============================================================

class LSLControlSender:
    """
    Publica comandos de controlo no stream LSL irregular P300_Control.

    Stream irregular (nominal_srate=0.0) porque os comandos não são
    enviados a frequência fixa — são eventos esparsos.

    Comandos suportados:
    - "START_CSV": instrui o pipeline a começar a gravar no CSV.
    - "STOP_CSV":  instrui o pipeline a parar a gravação e escrever o ficheiro.
    """

    def __init__(self):
        # StreamInfo para o stream de controlo.
        # nominal_srate=0.0: stream irregular, sem frequência fixa.
        # channel_format="string": cada amostra é uma string de texto.
        control_info = StreamInfo(
            name="P300_Control",
            type="Markers",
            channel_count=1,
            nominal_srate=0.0,
            channel_format="string",
            source_id="p300_control_v3",
        )

        # control_outlet: outlet LSL para publicar os comandos de controlo.
        self.control_outlet = StreamOutlet(control_info)

    def send_control(self, command: str):
        """
        Envia um comando de controlo para o stream P300_Control.

        command: string do comando a enviar ("START_CSV" ou "STOP_CSV").
        O timestamp LSL permite ao pipeline registar exatamente quando
        o comando foi enviado, em relação ao sinal EEG.

        Antes de enviar, aguarda até que o pipeline tenha criado o inlet
        e esteja efectivamente ligado a este outlet. Sem esta espera, o
        primeiro START_CSV pode ser publicado antes do pipeline conseguir
        resolver o stream — e perde-se silenciosamente. Timeout 15 s como
        salvaguarda: se ninguém ligar, envia na mesma e regista aviso.
        """
        waited = 0.0
        while not self.control_outlet.have_consumers() and waited < 15.0:
            time.sleep(0.1)
            waited += 0.1
        if not self.control_outlet.have_consumers():
            print(f"[WARN] {command}: timeout à espera de consumidor — envio na mesma")

        ts = local_clock()  # timestamp LSL do momento de envio
        self.control_outlet.push_sample([str(command)], timestamp=ts)
        print(f"[LSL][CONTROL] {command} @ {ts:.6f}")


# =============================================================
# CLASSE 4 — P300ExperimentController
# Orquestra toda a lógica temporal e sequencial do ensaio P300.
# =============================================================

class P300ExperimentController:
    """
    Controlador principal da lógica experimental do P300.

    Responsabilidades:
    - gerir o ciclo de trials (início, progressão, fim)
    - definir qual célula é o target em cada trial
    - gerar a sequência aleatória de estímulos de cada trial
    - ordenar à grelha o flash da célula correta em cada momento
    - atualizar o stream contínuo de eventos (code/trigger)
    - enviar START_CSV e STOP_CSV nos momentos certos

    A grelha (P300SingleCellGrid) é completamente passiva:
    não decide nada, apenas executa as ordens deste controller.
    """

    def __init__(
        self,
        grid,                       # widget visual da grelha P300
        event_sender,               # LSLContinuousEventSender — publica code/trigger
        control_sender,             # LSLControlSender — envia START_CSV / STOP_CSV
        targets,                    # lista de códigos de target por trial (ex: [5,1,9,3])
        rounds_per_trial,           # número de vezes que cada célula pisca por trial
        num_events,                 # número total de células/estímulos (fixo: 9)
        isi_ms,                     # inter-stimulus interval: pausa em ms entre flashes
        inter_trial_ms=1000,        # pausa em ms entre o fim de um trial e o início do próximo
        pre_start_delay_ms=3000,    # pausa em ms entre START_CSV e o 1º trial
        start_trial_delay_ms=500,   # pausa interna em ms antes do 1º flash de cada trial
        rng_seed=42,                # seed do gerador pseudoaleatório (garante reprodutibilidade)
    ):
        # grid: referência ao widget visual da grelha.
        # O controller manda-lhe fazer flash e definir o target.
        self.grid = grid

        # event_sender: publica continuamente o estado [code, trigger] no stream LSL.
        # O controller chama set_event() quando um flash começa e clear_event() quando termina.
        self.event_sender = event_sender

        # control_sender: envia comandos de gravação ao pipeline via stream LSL.
        self.control_sender = control_sender

        # targets: lista de códigos 1-based dos targets de cada trial.
        # Ex: [5,1,9,3] = 4 trials com targets "Sede","Sim","Stop","Fome".
        self.targets = list(targets)

        # rounds_per_trial: quantas vezes cada célula pisca em cada trial.
        # Com 9 células e 5 rounds, cada trial tem 9×5=45 flashes no total.
        self.rounds_per_trial = int(rounds_per_trial)

        # num_events: número total de células/estímulos disponíveis (fixo: 9).
        self.num_events = int(num_events)

        # isi_ms: inter-stimulus interval em milissegundos.
        # Pausa entre o fim de um flash e o início do próximo.
        # Permite ao sinal EEG "recuperar" e facilita a segmentação dos epochs.
        self.isi_ms = int(isi_ms)

        # inter_trial_ms: pausa em ms entre o fim de um trial e o início do seguinte.
        # Dá tempo ao utilizador para se focar no próximo target.
        self.inter_trial_ms = int(inter_trial_ms)

        # pre_start_delay_ms: pausa entre o envio de START_CSV e o arranque do 1º trial.
        # Configurável pelo utilizador no setup. Permite que o EEG estabilize
        # antes de qualquer estímulo ser apresentado.
        self.pre_start_delay_ms = int(pre_start_delay_ms)

        # start_trial_delay_ms: pequena pausa interna antes do 1º flash de cada trial.
        # Aplicada nos trials 2, 3, ... (o trial 1 já tem o pre_start_delay_ms).
        self.start_trial_delay_ms = int(start_trial_delay_ms)

        # rng: gerador pseudoaleatório local com seed fixa.
        # A seed fixa garante que a mesma sequência é gerada em todas as execuções
        # com os mesmos parâmetros — importante para reprodutibilidade científica.
        self.rng = random.Random(rng_seed)

        # current_trial_idx: índice do trial atualmente em execução.
        # Começa em -1 porque é incrementado antes de ser usado pela 1ª vez.
        self.current_trial_idx = -1

        # current_sequence: lista de índices 0-based das células para o trial atual.
        # Ex: [3,7,0,5,2,8,1,6,4, 6,2,8,0,4,7,3,1,5] para 9 células e 2 rounds.
        self.current_sequence = []

        # current_event_pos: posição atual dentro de current_sequence.
        # Começa em -1 porque é incrementado antes de ser usado.
        self.current_event_pos = -1

        # running: flag booleana que indica se o ensaio está em execução.
        # Quando False, todos os callbacks e timers abortam imediatamente.
        self.running = False

        # Liga os callbacks da grelha a este controller (acoplamento fraco).
        # on_stimulus_start: chamado pela grelha quando o flash de uma célula começa.
        # on_stimulus_end:   chamado pela grelha quando o flash de uma célula termina.
        self.grid.on_stimulus_start = self._on_stimulus_start
        self.grid.on_stimulus_end = self._on_stimulus_end

    def start(self):
        """
        Inicia o ensaio experimental.

        Sequência:
        1. Ativa a flag running.
        2. Envia START_CSV ao pipeline (inicia gravação do EEG).
        3. Aguarda pre_start_delay_ms antes do primeiro trial.
           Este atraso é configurável e permite que o EEG estabilize
           após o início da gravação antes de qualquer estímulo.
        """
        # Marca o ensaio como ativo — todos os callbacks passam a funcionar.
        self.running = True

        # Instrui o pipeline a começar a gravar dados EEG no CSV.
        self.control_sender.send_control("START_CSV")

        print(f"[INFO] A aguardar {self.pre_start_delay_ms} ms antes do 1º trial...")

        # Agenda o arranque do 1º trial após a pausa configurada pelo utilizador.
        # QTimer.singleShot não bloqueia — o event loop Qt continua ativo.
        QTimer.singleShot(self.pre_start_delay_ms, self._start_next_trial)

    def stop(self):
        """
        Termina o ensaio de forma controlada.

        1. Verifica se está em execução (evita dupla paragem).
        2. Desativa a flag running.
        3. Limpa o stream de eventos (envia [0,0]).
        4. Envia STOP_CSV ao pipeline (termina gravação e escreve ficheiro).
        """
        # Guarda duplo: se já parou, não faz nada.
        if not self.running:
            return

        # Desativa o ensaio — todos os callbacks posteriores vão abortar.
        self.running = False

        # Garante que o stream de eventos fica em [0,0] após o fim.
        self.event_sender.clear_event()

        # Instrui o pipeline a parar a gravação e escrever o CSV em disco.
        self.control_sender.send_control("STOP_CSV")

    def _start_next_trial(self):
        """
        Prepara e inicia o trial seguinte na lista de targets.

        1. Incrementa o índice de trial.
        2. Verifica se o ensaio terminou (sem mais trials).
        3. Define o target do novo trial na grelha.
        4. Gera a sequência aleatória de estímulos para este trial.
        5. Aguarda start_trial_delay_ms antes do 1º flash.
        """
        # Aborta se o ensaio foi parado entretanto.
        if not self.running:
            return

        # Avança para o próximo trial (começa em -1, fica 0 no 1º trial).
        self.current_trial_idx += 1

        # Verifica se já não há mais trials na lista.
        if self.current_trial_idx >= len(self.targets):
            print("[INFO] Ensaio terminado.")
            self.stop()           # para o ensaio e envia STOP_CSV
            QCoreApplication.quit()  # fecha o event loop Qt
            return

        # target_code: código 1-based do target deste trial (ex: 9 para "Stop").
        target_code = self.targets[self.current_trial_idx]

        # target_idx: índice 0-based correspondente, usado internamente na grelha.
        # Ex: target_code=9 -> target_idx=8.
        target_idx = target_code - 1

        # Informa a grelha de qual é o target — atualiza destaque visual e texto.
        self.grid.set_target(target_idx)

        # Gera a sequência completa de eventos deste trial.
        # Cada round contém todas as 9 células exatamente uma vez, em ordem aleatória.
        # O rng é partilhado entre trials, por isso o seu estado evolui continuamente.
        self.current_sequence = gera_seq_aleatoria(
            num_events=self.num_events,       # 9 células
            num_rounds=self.rounds_per_trial, # número de passagens completas
            rng=self.rng,                     # gerador partilhado (estado preservado)
        )

        # Reinicia a posição do evento para -1 (será incrementado antes de ser usado).
        self.current_event_pos = -1

        print(
            f"[INFO] Trial {self.current_trial_idx + 1}/{len(self.targets)} "
            f"| target = {FIXED_LABELS[target_idx]} "
            f"| eventos = {len(self.current_sequence)}"
        )

        # Aguarda start_trial_delay_ms antes de apresentar o 1º flash do trial.
        # Para o trial 1, o pre_start_delay_ms já foi aguardado em start().
        # Para os trials seguintes, esta pausa dá transição visual entre trials.
        QTimer.singleShot(self.start_trial_delay_ms, self._start_next_event)

    def _start_next_event(self):
        """
        Apresenta o próximo estímulo da sequência do trial atual.

        Se a sequência estiver esgotada:
        - aguarda inter_trial_ms e arranca o próximo trial.

        Se ainda há eventos:
        - obtém o índice da próxima célula a piscar.
        - ordena à grelha que faça flash dessa célula.
        """
        # Aborta se o ensaio foi parado.
        if not self.running:
            return

        # Avança para o próximo evento na sequência do trial atual.
        self.current_event_pos += 1

        # Verifica se a sequência do trial atual foi completamente apresentada.
        if self.current_event_pos >= len(self.current_sequence):
            print(f"[INFO] Fim do trial {self.current_trial_idx + 1}")
            # Aguarda a pausa entre trials e arranca o próximo.
            QTimer.singleShot(self.inter_trial_ms, self._start_next_trial)
            return

        # idx: índice 0-based da célula que vai piscar neste momento.
        idx = self.current_sequence[self.current_event_pos]

        # Ordena à grelha que faça flash da célula com índice idx.
        # A grelha chama on_stimulus_start quando começa e on_stimulus_end quando termina.
        self.grid.flash_cell(idx)

    def _on_stimulus_start(self, idx, is_target, label_text):
        """
        Callback chamado pela grelha quando o flash de uma célula começa.

        idx:        índice 0-based da célula que está a piscar.
        is_target:  True se esta célula é o target do trial atual.
        label_text: texto da célula (ex: "Sim"), apenas informativo.

        Codificação dos canais LSL:
        - Ch09 (code):    70 se é target, índice 1-based da célula se é distractor.
        - Ch10 (trigger): índice 1-based da célula se é target, 0 se é distractor.

        Desta forma, no CSV:
        - Ch09 == 70 identifica inequivocamente um evento target.
        - Ch10 != 0 indica qual a célula target nesse instante.
        - Cruzando Ch09==70 com Ch10, sabe-se exatamente qual célula foi o target.
        """
        # code: 70 se é target (valor fora do range 1..9, fácil de identificar);
        #       índice 1-based da célula se é distractor (ex: idx=8 -> code=9).
        code = 70 if is_target else idx + 1

        # trigger: índice 1-based da célula se é target (ex: idx=4 -> trigger=5),
        #          permitindo identificar qual célula foi o target;
        #          0 se é distractor (sem informação relevante).
        trigger = idx + 1 if is_target else 0

        # Atualiza o stream P300_Events com a nova codificação.
        self.event_sender.set_event(code, trigger)

    def _on_stimulus_end(self):
        """
        Callback chamado pela grelha quando o flash de uma célula termina.

        Coloca o stream de eventos em [0,0] (período OFF/ISI)
        e agenda o próximo evento após o intervalo ISI configurado.
        """
        # Coloca o stream em [0,0] — período sem estímulo ativo.
        self.event_sender.clear_event()

        # Só agenda o próximo evento se o ensaio ainda estiver em curso.
        if self.running:
            # Aguarda isi_ms antes de apresentar o próximo flash.
            QTimer.singleShot(self.isi_ms, self._start_next_event)


# =============================================================
# FUNÇÕES AUXILIARES
# Funções de suporte que não pertencem a nenhuma classe específica.
# =============================================================

def _build_output_paths(user_id: str):
    """
    Cria a estrutura de pastas da sessão e prepara o caminho do CSV.

    user_id: identificador do utilizador, usado como nome da subpasta.

    Estrutura criada:
        outputs/<user_id>/p300_full_output_lsl_AAAAMMDD_HHMMSS.csv

    Retorna:
    - output_dir: Path para a pasta da sessão (criada se não existir)
    - csv_file:   Path completo para o ficheiro CSV esperado
    """
    # output_dir: pasta outputs/<user_id>/ em caminho absoluto.
    # Resolve() converte para absoluto usando o CWD do controller, garantindo
    # que o pipeline (com CWD diferente) escreve no mesmo sítio que o controller.
    output_dir = Path("outputs").resolve() / user_id

    # Cria a pasta e todas as intermédias se não existirem.
    # exist_ok=True evita erro se a pasta já existir de uma sessão anterior.
    output_dir.mkdir(parents=True, exist_ok=True)

    # stamp: timestamp AAAAMMDD_HHMMSS para tornar o nome do ficheiro único.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # csv_file: caminho completo do ficheiro de saída com timestamp no nome.
    csv_file = output_dir / f"p300_full_output_lsl_{stamp}.csv"

    return output_dir, csv_file


def _write_session_info(output_dir: Path, condition: str, user_id: str):
    """
    Guarda um ficheiro JSON com metadados básicos da sessão.

    output_dir: pasta da sessão onde o ficheiro será criado.
    condition:  condição experimental ("offline" ou "online").
    user_id:    identificador do utilizador.

    O ficheiro session_info.json permite:
    - identificar a sessão sem abrir o CSV.
    - associar dados ao utilizador/condição nas análises.
    - rastrear quando cada sessão foi realizada.
    """
    # info_file: caminho do ficheiro de metadados dentro da pasta da sessão.
    info_file = output_dir / "session_info.json"

    # payload: dicionário com os metadados a guardar em JSON.
    payload = {
        "project": "Projeto Final BCI4ALL",
        "condition": condition,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),  # hora de criação ISO 8601
    }

    try:
        # Abre o ficheiro para escrita em modo texto UTF-8.
        with open(info_file, "w", encoding="utf-8") as fh:
            # json.dump: serializa o dicionário para JSON.
            # indent=2: indentação de 2 espaços para legibilidade humana.
            # ensure_ascii=False: permite caracteres acentuados (ex: "ã", "é").
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        # Se falhar (ex: permissões negadas), apenas avisa sem crashar.
        print(f"[WARN] Não foi possível escrever session_info.json: {e}")


def launch_pipeline_process():
    """
    Lança o pipeline de processamento EEG como processo filho independente.

    O pipeline corre em processo separado para que:
    - possa ter o seu próprio event loop Qt sem conflito com o controller.
    - controller e pipeline comuniquem exclusivamente via LSL.
    - se um falhar, o outro possa continuar ou ser terminado de forma controlada.

    Retorna o objeto Process do pipeline lançado (subprocess.Popen).
    """
    # script_dir: pasta absoluta onde este script está localizado.
    # resolve() converte o caminho para absoluto, sem '..' ou links simbólicos.
    script_dir = Path(__file__).resolve().parent

    # pipeline_path: caminho completo para o script do pipeline na mesma pasta.
    pipeline_path = script_dir / "p300_pipeline_gpype_lsl.py"

    # Verifica se o ficheiro do pipeline existe antes de tentar lançá-lo.
    if not pipeline_path.exists():
        raise FileNotFoundError(
            f"Não foi encontrado o ficheiro do pipeline: {pipeline_path}"
        )

    # subprocess.Popen: lança um novo processo sem bloquear o processo atual.
    # sys.executable: usa o mesmo interpretador Python (mesmo ambiente virtual).
    # cwd=script_dir: o processo filho começa na mesma pasta que o controller.
    # env=os.environ.copy(): passa as variáveis de ambiente, incluindo BCI4ALL_*.
    process = subprocess.Popen(
        [sys.executable, str(pipeline_path)],
        cwd=str(script_dir),
        env=os.environ.copy(),
    )

    print(f"[INFO] Pipeline lançado com PID {process.pid}")
    return process


def continue_after_pipeline_start(app, pipeline_process, condition):
    """
    Continua o fluxo da aplicação após o pipeline ter tido tempo de inicializar.

    Chamada via QTimer.singleShot com 1000 ms de atraso para dar tempo ao
    pipeline de arrancar sem bloquear o event loop Qt com time.sleep().

    app:              instância da aplicação gpype (para adicionar widgets).
    pipeline_process: objeto do processo filho do pipeline (subprocess.Popen).
    condition:        "offline" ou "online".
    """
    if condition == "offline":
        # Abre o diálogo de configuração do ensaio P300.
        dialog = P300ExperimentSetupDialog()

        # exec(): abre o diálogo e bloqueia até o utilizador fechar.
        # Se cancelar, termina o pipeline e sai desta função.
        if dialog.exec() != QDialog.Accepted:
            if pipeline_process is not None:
                try:
                    pipeline_process.terminate()  # envia SIGTERM ao processo filho
                except Exception:
                    pass
            return

        # cfg: dicionário com todos os parâmetros configurados pelo utilizador.
        cfg = dialog.get_config()

        # Extrai cada parâmetro do dicionário com nome descritivo local.
        num_events       = 9                       # fixo: grelha 3x3 tem sempre 9 células
        rounds_per_trial = cfg["rounds_per_trial"] # rounds por trial (ex: 5)
        flash_ms         = cfg["flash_ms"]          # duração do flash em ms (ex: 200)
        isi_ms           = cfg["isi_ms"]            # inter-stimulus interval em ms (ex: 100)
        inter_trial_ms   = cfg["inter_trial_ms"]    # pausa entre trials em ms (ex: 1000)
        targets          = cfg["targets"]           # lista de targets (ex: [1,2,3,4,5,6,7,8,9])
        show_target_hint = cfg["show_target_hint"]  # True = destaca visualmente o target

        # pre_start_delay_ms: pausa entre START_CSV e o 1º trial.
        # Vem do campo "Pausa após início de gravação" configurado pelo utilizador.
        pre_start_delay_ms = cfg["pre_start_delay_ms"]

        # event_sender: publica continuamente [code, trigger] no stream P300_Events.
        event_sender = LSLContinuousEventSender(sampling_rate=EVENT_SAMPLING_RATE)

        # control_sender: envia START_CSV / STOP_CSV no stream P300_Control.
        control_sender = LSLControlSender()

        # grid: widget visual da grelha P300 com os parâmetros configurados.
        grid = P300SingleCellGrid(
            labels=FIXED_LABELS,               # textos das 9 células
            title="Interface de Seleção P300", # título interno do widget gpype
            flash_ms=flash_ms,                 # duração do flash visual em ms
            target_idx=0,                      # target inicial (atualizado pelo controller)
            show_target_hint=show_target_hint, # se destaca o target com borda amarela
        )

        # controller: objeto que orquestra toda a lógica experimental.
        controller = P300ExperimentController(
            grid=grid,
            event_sender=event_sender,
            control_sender=control_sender,
            targets=targets,
            rounds_per_trial=rounds_per_trial,
            num_events=num_events,
            isi_ms=isi_ms,
            inter_trial_ms=inter_trial_ms,
            pre_start_delay_ms=pre_start_delay_ms,  # vem do setup — pausa após START_CSV
            start_trial_delay_ms=500,               # pausa interna fixa antes de cada trial
            rng_seed=42,                            # seed fixa para reprodutibilidade
        )

        # Adiciona a grelha à janela principal da aplicação gpype.
        app.add_widget(grid)

        # Aguarda 500 ms para garantir que a UI está completamente renderizada
        # antes de chamar controller.start() — que envia START_CSV imediatamente.
        QTimer.singleShot(500, controller.start)

        print("[INFO] Controller P300 com stream contínuo pronto.")
        print(f"[INFO] Pausa após START_CSV: {pre_start_delay_ms} ms")
        print("[INFO] Event stream: P300_Events")
        print("[INFO] Control stream: P300_Control")

    else:
        # Modo online: ainda não implementado.
        # Mostra mensagem informativa e termina o pipeline lançado.
        QMessageBox.information(
            None,
            "Modo Online",
            "O fluxo online ainda não está implementado.\n"
            "Por agora, esta opção serve apenas como seleção de condição."
        )
        if pipeline_process is not None:
            try:
                pipeline_process.terminate()
            except Exception:
                pass
        return


# =============================================================
# FUNÇÃO PRINCIPAL — main()
# Ponto de entrada da aplicação. Orquestra o fluxo completo.
# =============================================================

def main():
    """
    Função principal do controller P300.

    Fluxo completo:
    1. Cria a aplicação Qt/gpype.
    2. Aplica o tema gráfico escuro a toda a aplicação.
    3. Mostra o menu principal (recolhe condição + ID do utilizador).
    4. Cria a pasta de saída e guarda os metadados da sessão.
    5. Define variáveis de ambiente para o pipeline filho.
    6. Lança o pipeline como processo filho independente.
    7. Agenda a continuação do fluxo sem bloquear o event loop.
    8. Entra no event loop principal (app.run()).
    9. No final, aguarda ou força a terminação do processo filho.
    """

    # Cria a aplicação principal do gpype.
    # Internamente cria também a QApplication Qt necessária para a UI.
    app = gp.MainApp()

    # Renomeia as janelas top-level já existentes para o título do projeto.
    qt_app = QApplication.instance()
    if qt_app is not None:
        for widget in qt_app.topLevelWidgets():
            widget.setWindowTitle("Projeto Final BCI4ALL")

    # Aplica tema escuro a todos os widgets Qt deste processo.
    # setStyleSheet no nível da QApplication aplica-se globalmente a todos os widgets.
    qt_app = QApplication.instance()
    if qt_app is not None:
        qt_app.setStyleSheet("""
            QWidget      { background-color: #121212; color: #f0f0f0; }
            QDialog      { background-color: #121212; color: #f0f0f0; }
            QLabel       { color: #f0f0f0; }
            QPushButton  { background-color: #2b2b2b; color: #f0f0f0;
                           border: 1px solid #555555; padding: 6px; border-radius: 6px; }
            QPushButton:disabled { color: #f0f0f0; }
            QLineEdit, QSpinBox  { background-color: #1e1e1e; color: #f0f0f0;
                                   border: 1px solid #555555; padding: 4px; border-radius: 4px; }
            QCheckBox    { color: #f0f0f0; }
        """)

    # ---------------------------------------------------------
    # PASSO 1: Menu principal
    # Recolhe condição e ID do utilizador antes de qualquer outra ação.
    # ---------------------------------------------------------
    main_menu = MainMenuDialog()

    # exec(): abre o diálogo e bloqueia até o utilizador fechar.
    # Se cancelar (resultado != Accepted), termina o programa imediatamente.
    if main_menu.exec() != QDialog.Accepted:
        return

    # Lê os dados validados do menu principal.
    main_cfg  = main_menu.get_config()
    condition = main_cfg["condition"]  # "offline" ou "online"
    user_id   = main_cfg["user_id"]   # ex: "User01"

    # ---------------------------------------------------------
    # PASSO 2: Preparar estrutura de ficheiros da sessão
    # ---------------------------------------------------------

    # output_dir: pasta outputs/<user_id>/ (criada automaticamente).
    # csv_file:   caminho completo do CSV com timestamp no nome.
    output_dir, csv_file = _build_output_paths(user_id)

    # Guarda session_info.json com metadados básicos da sessão.
    _write_session_info(output_dir, condition, user_id)

    # ---------------------------------------------------------
    # PASSO 3: Variáveis de ambiente para o pipeline filho
    # O pipeline lê estas variáveis para saber onde guardar os dados.
    # ---------------------------------------------------------
    os.environ["BCI4ALL_USER_ID"]     = user_id         # ID do utilizador
    os.environ["BCI4ALL_CONDITION"]   = condition        # condição experimental
    os.environ["BCI4ALL_OUTPUT_DIR"]  = str(output_dir) # pasta de saída
    os.environ["BCI4ALL_OUTPUT_FILE"] = str(csv_file)   # caminho completo do CSV

    print(f"[INFO] Condition: {condition}")
    print(f"[INFO] User ID: {user_id}")
    print(f"[INFO] Output directory: {output_dir}")
    print(f"[INFO] Expected CSV output: {csv_file}")

    # ---------------------------------------------------------
    # PASSO 4: Lançar o pipeline como processo filho
    # ---------------------------------------------------------
    pipeline_process = None  # inicializado a None para o bloco finally poder usá-lo

    try:
        # Lança o script do pipeline num processo separado.
        # As variáveis de ambiente BCI4ALL_* definidas acima são passadas automaticamente.
        pipeline_process = launch_pipeline_process()
    except Exception as e:
        # Se o pipeline não puder ser lançado, mostra erro crítico e termina.
        QMessageBox.critical(
            None,
            "Erro ao lançar pipeline",
            f"Não foi possível iniciar o pipeline.\n\n{e}"
        )
        return

    # ---------------------------------------------------------
    # PASSO 5: Agendar a continuação do fluxo
    # QTimer.singleShot dá 1000 ms ao pipeline para inicializar,
    # sem bloquear o event loop Qt (que ficaria congelado com time.sleep()).
    # ---------------------------------------------------------
    QTimer.singleShot(
        1000,  # aguarda 1 segundo antes de continuar
        # lambda: função anónima que captura app, pipeline_process e condition
        # e chama continue_after_pipeline_start quando o timer disparar.
        lambda: continue_after_pipeline_start(app, pipeline_process, condition)
    )

    try:
        # Entra no event loop principal da aplicação.
        # Fica aqui até QCoreApplication.quit() ser chamado (fim do ensaio).
        app.run()
    finally:
        # Bloco finally: executado sempre, mesmo que ocorra uma exceção.
        if pipeline_process is not None:
            try:
                # Aguarda até 3 segundos para o pipeline terminar normalmente.
                pipeline_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # Se não terminar em 3 segundos, força a terminação.
                print("[WARN] Pipeline ainda ativo, a terminar processo...")
                pipeline_process.terminate()


# Ponto de entrada do script.
# Só executa main() se o ficheiro for corrido diretamente,
# não quando é importado como módulo por outro script.
if __name__ == "__main__":
    main()