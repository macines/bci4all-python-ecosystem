""" 
Controller P300 com stream LSL contínuo de eventos.

Streams LSL:
- P300_Events  -> contínuo, 2 canais float32 [code, trigger]
- P300_Control -> irregular, strings START_CSV / STOP_CSV

Notas:
- A lógica experimental foi mantida.
- Foi acrescentado:
    1) menu principal "Projeto Final BCI4ALL"
    2) escolha da condição (offline / online)
    3) campo ID do Utilizador
    4) criação automática da diretoria de saída
    5) abertura do setup experimental apenas para a condição offline
    6) arranque automático do pipeline como processo filho
"""

# ---------------------------------------------------------
# Imports standard / utilitários
# ---------------------------------------------------------

import json            # usado para guardar metadados da sessão em ficheiro JSON
import os              # usado para definir variáveis de ambiente e manipular paths do sistema
import random          # usado para controlar a aleatoriedade das sequências experimentais
import re              # usado para validar o formato do ID do utilizador
import subprocess      # usado para lançar o pipeline como processo filho
import sys             # usado para obter o executável Python atual
from datetime import datetime   # usado para timestamps de diretoria e metadados
from pathlib import Path        # usado para manipulação robusta de paths/pastas

# ---------------------------------------------------------
# Imports LSL / Qt
# ---------------------------------------------------------

from pylsl import StreamInfo, StreamOutlet, local_clock
from PySide6.QtCore import QTimer, QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QMessageBox,
    QWidget,
)

# ---------------------------------------------------------
# Import do gpype e módulos do projeto
# ---------------------------------------------------------

import gpype as gp

# Dialog já existente com parâmetros experimentais offline
from p300_experiment_setup import P300ExperimentSetupDialog

# Widget visual da grelha P300
from p300_single_cell_grid import P300SingleCellGrid

# Função que gera a sequência aleatória dos eventos de cada trial
from p300_sequence import gera_seq_aleatoria


# ---------------------------------------------------------
# Constantes globais da interface P300
# ---------------------------------------------------------

# Labels fixas apresentadas na grelha 3x3.
# Cada posição corresponde a um "evento" visual.
FIXED_LABELS = [
    "Sim", "Sono", "TV",
    "Fome", "Sede", "Não",
    "Ajuda", "Tosse", "Stop",
]

# Taxa de amostragem do stream contínuo de eventos.
# Este stream é publicado continuamente com [code, trigger].
EVENT_SAMPLING_RATE = 250


class MainMenuDialog(QDialog):
    """
    Menu principal da aplicação.

    Permite:
    - escolher a condição experimental
    - introduzir o ID do Utilizador
    - avançar para o setup apropriado

    Este dialog é o primeiro ecrã da aplicação.
    A lógica aqui é apenas de interface e validação básica.
    """

    def __init__(self):
        super().__init__()

        # Título da janela do menu principal
        self.setWindowTitle("Projeto Final BCI4ALL")

        # Modal=True obriga o utilizador a fechar/confirmar este dialog
        # antes de interagir com o resto da aplicação
        self.setModal(True)

        # Largura mínima para o layout não ficar apertado
        self.setMinimumWidth(420)

        # Layout vertical principal do dialog
        layout = QVBoxLayout(self)

        # Título visual principal
        title = QLabel("Projeto Final BCI4ALL")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Subtítulo explicativo
        subtitle = QLabel("Selecione a condição e introduza o ID do Utilizador")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; margin-bottom: 12px;")
        layout.addWidget(subtitle)

        # Form layout para organizar campos em linhas
        form = QFormLayout()

        # Checkboxes para condição experimental.
        # Aqui foi mantida a escolha via checkbox, mas com exclusividade manual:
        # apenas uma pode ficar ativa de cada vez.
        self.offline_check = QCheckBox("Offline")
        self.online_check = QCheckBox("Online")

        # Por defeito a condição offline fica selecionada
        self.offline_check.setChecked(True)

        # Liga os sinais "toggled" a funções que impõem exclusividade manual
        self.offline_check.toggled.connect(self._on_offline_toggled)
        self.online_check.toggled.connect(self._on_online_toggled)

        # Widget intermédio para colocar as duas checkboxes lado a lado
        cond_widget = QWidget()
        cond_layout = QHBoxLayout(cond_widget)
        cond_layout.setContentsMargins(0, 0, 0, 0)
        cond_layout.setSpacing(16)
        cond_layout.addWidget(self.offline_check)
        cond_layout.addWidget(self.online_check)

        form.addRow("Condição:", cond_widget)

        # Campo onde o utilizador escreve o seu identificador
        self.user_id_edit = QLineEdit("User01")
        form.addRow("ID do Utilizador:", self.user_id_edit)

        # Adiciona o formulário ao layout principal
        layout.addLayout(form)

        # Botões inferiores
        buttons = QHBoxLayout()
        self.next_btn = QPushButton("Avançar")
        self.cancel_btn = QPushButton("Cancelar")

        # "Avançar" valida primeiro o conteúdo do formulário
        self.next_btn.clicked.connect(self._validate_and_accept)

        # "Cancelar" fecha o dialog com rejeição
        self.cancel_btn.clicked.connect(self.reject)

        buttons.addWidget(self.next_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

    def _on_offline_toggled(self, checked: bool):
        """
        Impõe exclusividade manual:
        - se Offline for ativado, Online é desligado
        - se Offline for desligado e Online não estiver ligado,
          Offline volta a ligar-se para nunca ficarem ambos desligados
        """
        if checked:
            self.online_check.setChecked(False)
        elif not self.online_check.isChecked():
            self.offline_check.setChecked(True)

    def _on_online_toggled(self, checked: bool):
        """
        Impõe exclusividade manual simétrica para o checkbox Online.
        """
        if checked:
            self.offline_check.setChecked(False)
        elif not self.offline_check.isChecked():
            self.online_check.setChecked(True)

    def _validate_and_accept(self):
        """
        Tenta validar os dados do formulário.
        Se estiver tudo válido, aceita o dialog.
        Caso contrário, mostra mensagem de erro.
        """
        try:
            _ = self.get_config()
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Configuração inválida", str(e))

    def get_config(self):
        """
        Lê os dados do dialog e devolve um dicionário simples.

        Valida:
        - se o ID do utilizador não está vazio
        - se o ID do utilizador contém apenas caracteres permitidos

        Retorna:
        {
            "condition": "offline" ou "online",
            "user_id": <texto validado>
        }
        """
        user_id = self.user_id_edit.text().strip()

        # Garante que o campo não está vazio
        if not user_id:
            raise ValueError("O ID do Utilizador não pode estar vazio.")

        # Restringe os caracteres para evitar problemas em nomes de pastas/ficheiros
        if not re.fullmatch(r"[A-Za-z0-9_-]+", user_id):
            raise ValueError(
                "O ID do Utilizador só pode conter letras, números, '_' e '-'."
            )

        # Determina a condição experimental com base na checkbox ativa
        condition = "offline" if self.offline_check.isChecked() else "online"

        return {
            "condition": condition,
            "user_id": user_id,
        }


class LSLContinuousEventSender:
    """
    Publica continuamente um stream LSL com 2 canais:
    - canal 1: code
    - canal 2: trigger

    Durante OFF/ISI envia [0, 0].
    Durante FLASH envia [code, trigger].

    Esta classe mantém sempre um estado interno atual:
    - current_code
    - current_trigger

    E um timer Qt que, à frequência definida, envia esse estado
    continuamente para o stream LSL P300_Events.
    """

    def __init__(self, sampling_rate=EVENT_SAMPLING_RATE):
        # sampling_rate define quantas amostras por segundo vão ser enviadas
        self.sampling_rate = int(sampling_rate)

        # Descrição do stream LSL contínuo de eventos
        info = StreamInfo(
            name="P300_Events",
            type="Markers",
            channel_count=2,
            nominal_srate=float(self.sampling_rate),
            channel_format="float32",
            source_id="p300_events_continuous_v1",
        )

        # Outlet LSL que efetivamente publica os dados
        self.outlet = StreamOutlet(info)

        # Estado atual do evento:
        # code = índice da célula + 1
        # trigger = 1 se target, 0 se non-target
        self.current_code = 0.0
        self.current_trigger = 0.0

        # Timer Qt usado para enviar amostras continuamente
        self.timer = QTimer()
        self.timer.timeout.connect(self._push_sample)

        # Intervalo do timer em milissegundos com base no sampling_rate
        self.timer.start(max(1, int(round(1000 / self.sampling_rate))))

    def _push_sample(self):
        """
        Envia uma amostra LSL com o estado atual [code, trigger].

        O timestamp é dado por local_clock(), para ficar no relógio do LSL.
        """
        ts = local_clock()
        self.outlet.push_sample(
            [float(self.current_code), float(self.current_trigger)],
            timestamp=ts,
        )

    def set_event(self, code: float, trigger: float):
        """
        Atualiza o estado atual para o valor correspondente ao estímulo ON.
        A partir daí, o timer contínuo passa a publicar esses valores.
        """
        self.current_code = float(code)
        self.current_trigger = float(trigger)
        print(f"[LSL][EVENTS] ON  code={self.current_code}, trigger={self.current_trigger}")

    def clear_event(self):
        """
        Coloca o estado em OFF, isto é, [0, 0].
        O timer contínuo continua a publicar, mas agora com evento desligado.
        """
        self.current_code = 0.0
        self.current_trigger = 0.0
        print("[LSL][EVENTS] OFF code=0, trigger=0")


class LSLControlSender:
    """
    Publica o stream LSL irregular de controlo.

    Este stream é usado para enviar comandos como:
    - START_CSV
    - STOP_CSV

    O pipeline escuta este stream para saber quando começar e parar a gravação.
    """

    def __init__(self):
        # Stream LSL irregular (nominal_srate = 0.0) com 1 canal string
        control_info = StreamInfo(
            name="P300_Control",
            type="Markers",
            channel_count=1,
            nominal_srate=0.0,
            channel_format="string",
            source_id="p300_control_v3",
        )
        self.control_outlet = StreamOutlet(control_info)

    def send_control(self, command: str):
        """
        Envia um comando de controlo para o stream P300_Control.
        """
        ts = local_clock()
        self.control_outlet.push_sample([str(command)], timestamp=ts)
        print(f"[LSL][CONTROL] {command} @ {ts:.6f}")


class P300ExperimentController:
    """
    Controlador principal da lógica experimental.

    Responsabilidades:
    - gerir o ciclo dos trials
    - definir qual é o target do trial atual
    - gerar a sequência de eventos de cada trial
    - mandar a grelha fazer flash da célula certa
    - ligar/desligar o stream contínuo de eventos
    - mandar START_CSV / STOP_CSV

    A grelha é passiva: só mostra o estímulo que o controller ordena.
    """

    def __init__(
        self,
        grid,
        event_sender,
        control_sender,
        targets,
        rounds_per_trial,
        num_events,
        isi_ms,
        inter_trial_ms=1000,
        start_trial_delay_ms=500,
        rng_seed=42,
    ):
        # Widget visual da grelha
        self.grid = grid

        # Objeto que publica continuamente [code, trigger]
        self.event_sender = event_sender

        # Objeto que envia START_CSV / STOP_CSV
        self.control_sender = control_sender

        # Lista de targets por trial
        # Exemplo: [5, 8, 3, 7, ...]
        self.targets = list(targets)

        # Número de rounds completos por trial
        self.rounds_per_trial = int(rounds_per_trial)

        # Número total de eventos/células disponíveis
        self.num_events = int(num_events)

        # Intervalo entre o fim de um flash e o próximo evento
        self.isi_ms = int(isi_ms)

        # Pausa entre trials consecutivos
        self.inter_trial_ms = int(inter_trial_ms)

        # Pequeno atraso antes do primeiro evento de cada trial
        self.start_trial_delay_ms = int(start_trial_delay_ms)

        # Gerador pseudoaleatório local, com seed fixa para reprodutibilidade
        self.rng = random.Random(rng_seed)

        # Índice do trial atual (começa em -1 antes de iniciar)
        self.current_trial_idx = -1

        # Sequência de eventos do trial atual
        self.current_sequence = []

        # Posição atual dentro da sequência do trial
        self.current_event_pos = -1

        # Flag que indica se a experiência está em execução
        self.running = False

        # Liga os callbacks da grelha ao controller:
        # - quando o estímulo começa
        # - quando o estímulo termina
        self.grid.on_stimulus_start = self._on_stimulus_start
        self.grid.on_stimulus_end = self._on_stimulus_end

    def start(self):
        """
        Inicia a experiência:
        - ativa running
        - manda começar a gravação CSV
        - agenda o arranque do primeiro trial
        """
        self.running = True
        self.control_sender.send_control("START_CSV")
        QTimer.singleShot(300, self._start_next_trial)

    def stop(self):
        """
        Termina a experiência:
        - desativa running
        - limpa o evento contínuo
        - manda parar a gravação CSV
        """
        if not self.running:
            return

        self.running = False
        self.event_sender.clear_event()
        self.control_sender.send_control("STOP_CSV")

    def _start_next_trial(self):
        """
        Avança para o trial seguinte.

        Passos:
        1) incrementa o índice de trial
        2) verifica se a experiência já terminou
        3) escolhe o target desse trial
        4) gera a sequência aleatória do trial
        5) agenda o primeiro evento
        """
        if not self.running:
            return

        self.current_trial_idx += 1

        # Se já não houver mais trials, termina a experiência
        if self.current_trial_idx >= len(self.targets):
            print("[INFO] Ensaio terminado.")
            self.stop()
            QCoreApplication.quit()
            return

        # target_code é 1..N
        target_code = self.targets[self.current_trial_idx]

        # target_idx é índice base 0, usado internamente na grelha
        target_idx = target_code - 1

        # Atualiza visualmente o target da grelha
        self.grid.set_target(target_idx)

        # Gera a sequência completa do trial:
        # cada round contém todos os eventos uma vez, em ordem aleatória
        self.current_sequence = gera_seq_aleatoria(
            num_events=self.num_events,
            num_rounds=self.rounds_per_trial,
            rng=self.rng,
        )

        # Reinicia a posição do evento dentro deste trial
        self.current_event_pos = -1

        print(
            f"[INFO] Trial {self.current_trial_idx + 1}/{len(self.targets)} "
            f"| target = {FIXED_LABELS[target_idx]} "
            f"| eventos = {len(self.current_sequence)}"
        )

        # Aguarda um pouco antes de lançar o primeiro evento do trial
        QTimer.singleShot(self.start_trial_delay_ms, self._start_next_event)

    def _start_next_event(self):
        """
        Avança para o próximo evento da sequência do trial atual.

        Se a sequência do trial terminar:
        - espera inter_trial_ms
        - e arranca o próximo trial
        """
        if not self.running:
            return

        self.current_event_pos += 1

        # Se já esgotou os eventos deste trial, termina o trial
        if self.current_event_pos >= len(self.current_sequence):
            print(f"[INFO] Fim do trial {self.current_trial_idx + 1}")
            QTimer.singleShot(self.inter_trial_ms, self._start_next_trial)
            return

        # Obtém o índice da célula a piscar neste momento
        idx = self.current_sequence[self.current_event_pos]

        # Manda a grelha fazer flash dessa célula
        self.grid.flash_cell(idx)

    def _on_stimulus_start(self, idx, is_target, label_text):
        """
        Callback chamado pela grelha quando o flash começa.

        Converte:
        - idx (0-based) -> code (1-based)
        - is_target -> trigger (0/1)

        E atualiza o stream contínuo de eventos.
        """
        code = idx + 1
        trigger = 1 if is_target else 0
        self.event_sender.set_event(code, trigger)

    def _on_stimulus_end(self):
        """
        Callback chamado pela grelha quando o flash termina.

        Coloca o stream de eventos em OFF e agenda o próximo evento
        após o ISI.
        """
        self.event_sender.clear_event()

        if self.running:
            QTimer.singleShot(self.isi_ms, self._start_next_event)


def _build_output_paths(user_id: str):
    """
    Cria a diretoria da sessão e prepara o caminho esperado do CSV.

    Exemplo:
        outputs/User01/p300_full_output_lsl_20260420_123000.csv

    Retorna:
    - output_dir: diretoria da sessão
    - csv_file: caminho completo do CSV esperado
    """
    output_dir = Path("outputs") / user_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Timestamp usado para tornar o nome do ficheiro único
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = output_dir / f"p300_full_output_lsl_{stamp}.csv"

    return output_dir, csv_file


def _write_session_info(output_dir: Path, condition: str, user_id: str):
    """
    Guarda um pequeno ficheiro JSON com metadados básicos da sessão.

    Isto é útil para organização e rastreabilidade dos ensaios.
    """
    info_file = output_dir / "session_info.json"

    payload = {
        "project": "Projeto Final BCI4ALL",
        "condition": condition,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        with open(info_file, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] Não foi possível escrever session_info.json: {e}")


def launch_pipeline_process():
    """
    Arranca o pipeline como processo filho, herdando as variáveis
    de ambiente já preparadas pelo controller.

    O pipeline é lançado com:
    - o mesmo Python do processo atual
    - a mesma diretoria do script
    - uma cópia das variáveis de ambiente atuais
    """
    script_dir = Path(__file__).resolve().parent
    pipeline_path = script_dir / "p300_pipeline_gpype_lsl.py"

    # Garante que o ficheiro do pipeline existe
    if not pipeline_path.exists():
        raise FileNotFoundError(
            f"Não foi encontrado o ficheiro do pipeline: {pipeline_path}"
        )

    # Lança o pipeline como novo processo
    process = subprocess.Popen(
        [sys.executable, str(pipeline_path)],
        cwd=str(script_dir),
        env=os.environ.copy(),
    )

    print(f"[INFO] Pipeline lançado com PID {process.pid}")
    return process


def continue_after_pipeline_start(app, pipeline_process, condition):
    """
    Continua o fluxo da aplicação após o lançamento do pipeline,
    sem recorrer a bloqueios com sleep().

    Esta função é chamada de forma assíncrona com QTimer.singleShot(...),
    permitindo que o event loop Qt continue ativo enquanto se dá algum
    tempo ao pipeline para inicializar.
    """
    if condition == "offline":
        dialog = P300ExperimentSetupDialog()

        # Se o utilizador cancelar o setup, termina também o pipeline
        if dialog.exec() != QDialog.Accepted:
            if pipeline_process is not None:
                try:
                    pipeline_process.terminate()
                except Exception:
                    pass
            return

        # Lê os parâmetros configurados no setup offline
        cfg = dialog.get_config()

        # Aqui num_events é fixado a 9 porque a grelha/labels atuais são fixas
        num_events = 9

        # rounds_per_trial = número de passagens completas pela grelha em cada trial
        rounds_per_trial = cfg["rounds_per_trial"]

        # flash_ms = duração do flash ON
        flash_ms = cfg["flash_ms"]

        # isi_ms = intervalo OFF entre flashes
        isi_ms = cfg["isi_ms"]

        # inter_trial_ms = pausa entre trials consecutivos
        inter_trial_ms = cfg["inter_trial_ms"]

        # targets = lista dos targets por trial
        targets = cfg["targets"]

        # show_target_hint = se o target é destacado visualmente
        show_target_hint = cfg["show_target_hint"]

        # Sender do stream contínuo [code, trigger]
        event_sender = LSLContinuousEventSender(sampling_rate=EVENT_SAMPLING_RATE)

        # Sender dos comandos START_CSV / STOP_CSV
        control_sender = LSLControlSender()

        # Widget visual da grelha P300
        grid = P300SingleCellGrid(
            labels=FIXED_LABELS,
            title="Interface de Seleção P300",
            flash_ms=flash_ms,
            target_idx=0,
            show_target_hint=show_target_hint,
        )

        # Controller experimental que coordena sequência, trials, eventos e LSL
        controller = P300ExperimentController(
            grid=grid,
            event_sender=event_sender,
            control_sender=control_sender,
            targets=targets,
            rounds_per_trial=rounds_per_trial,
            num_events=num_events,
            isi_ms=isi_ms,
            inter_trial_ms=inter_trial_ms,
            start_trial_delay_ms=500,
            rng_seed=42,
        )

        # Adiciona a grelha à aplicação gpype
        app.add_widget(grid)

        # Arranque do ensaio ligeiramente atrasado para garantir que a UI está pronta
        QTimer.singleShot(500, controller.start)

        print("[INFO] Controller P300 com stream contínuo pronto.")
        print("[INFO] Event stream: P300_Events")
        print("[INFO] Control stream: P300_Control")

    else:
        # O modo online ainda não foi implementado.
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


def main():
    """
    Função principal do controller.

    Fluxo:
    1) cria a app Qt/gpype
    2) mostra menu principal
    3) prepara diretoria e metadados da sessão
    4) lança o pipeline automaticamente
    5) agenda a continuação do fluxo sem bloquear a thread principal
    6) corre a app
    """
    app = gp.MainApp()

    qt_app = QApplication.instance()
    if qt_app is not None:
        for widget in qt_app.topLevelWidgets():
                widget.setWindowTitle("Projeto Final BCI4ALL")

    # Aplica tema escuro às janelas Qt criadas por este processo
    qt_app = QApplication.instance()
    if qt_app is not None:
        qt_app.setStyleSheet("""
            QWidget {
                background-color: #121212;
                color: #f0f0f0;
            }

            QDialog {
                background-color: #121212;
                color: #f0f0f0;
            }

            QLabel {
                color: #f0f0f0;
            }

            QPushButton {
                background-color: #2b2b2b;
                color: #f0f0f0;
                border: 1px solid #555555;
                padding: 6px;
                border-radius: 6px;
            }

            QPushButton:disabled {
                color: #f0f0f0;
            }

            QLineEdit, QSpinBox {
                background-color: #1e1e1e;
                color: #f0f0f0;
                border: 1px solid #555555;
                padding: 4px;
                border-radius: 4px;
            }

            QCheckBox {
                color: #f0f0f0;
            }
        """)

    # ---------------------------------------------------------
    # 1) Menu principal
    # ---------------------------------------------------------
    main_menu = MainMenuDialog()

    # Se o utilizador cancelar o menu principal, termina logo
    if main_menu.exec() != QDialog.Accepted:
        return

    # Obtém condição e ID do utilizador a partir do menu principal
    main_cfg = main_menu.get_config()
    condition = main_cfg["condition"]
    user_id = main_cfg["user_id"]

    # Cria diretoria da sessão e prepara caminho esperado do CSV
    output_dir, csv_file = _build_output_paths(user_id)

    # Guarda metadados básicos da sessão
    _write_session_info(output_dir, condition, user_id)

    # Variáveis de ambiente para o pipeline:
    # o pipeline pode ler isto para saber onde guardar o CSV
    os.environ["BCI4ALL_USER_ID"] = user_id
    os.environ["BCI4ALL_CONDITION"] = condition
    os.environ["BCI4ALL_OUTPUT_DIR"] = str(output_dir)
    os.environ["BCI4ALL_OUTPUT_FILE"] = str(csv_file)

    print(f"[INFO] Condition: {condition}")
    print(f"[INFO] User ID: {user_id}")
    print(f"[INFO] Output directory: {output_dir}")
    print(f"[INFO] Expected CSV output: {csv_file}")

    # ---------------------------------------------------------
    # 2) Lançar pipeline automaticamente
    # ---------------------------------------------------------
    pipeline_process = None

    try:
        pipeline_process = launch_pipeline_process()
    except Exception as e:
        QMessageBox.critical(
            None,
            "Erro ao lançar pipeline",
            f"Não foi possível iniciar o pipeline.\n\n{e}"
        )
        return

    # Em vez de usar time.sleep(...), agenda a continuação do fluxo.
    # Isto mantém o event loop ativo e evita bloquear a thread principal.
    QTimer.singleShot(
        1000,
        lambda: continue_after_pipeline_start(app, pipeline_process, condition)
    )

    try:
        # Corre o loop principal da aplicação
        app.run()
    finally:
        # No fim, tenta esperar que o pipeline termine normalmente
        if pipeline_process is not None:
            try:
                pipeline_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                print("[WARN] Pipeline ainda ativo, a terminar processo...")
                pipeline_process.terminate()


if __name__ == "__main__":
    main()