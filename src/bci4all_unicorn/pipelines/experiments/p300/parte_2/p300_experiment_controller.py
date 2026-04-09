"""
Nome do ficheiro:
    p300_experiment_controller.py

Descrição:
    Camada 2 do protótipo P300.

    Este ficheiro controla a lógica da experiência:
    - define qual é o target atual
    - arranca e pára a sequência
    - recebe notificações da grelha visual quando um flash começa e termina
    - mantém o estado atual dos eventos
    - envia continuamente 3 valores por UDP:
        * Ch09 -> código da célula ativa
        * Ch10 -> trigger target/non-target
        * controlo -> comandos START/STOP do CSV

Convenção:
    Porta 12345 -> Ch09 = código do estímulo
        0 = sem evento
        1..9 = célula ativa

    Porta 12346 -> Ch10 = trigger binário
        0 = sem target
        1 = flash target

    Porta 12347 -> controlo da gravação
        0 = idle
        1 = START_CSV
        2 = STOP_CSV
"""

# socket -> usado para enviar valores por UDP
import socket

# threading -> usado para criar threads paralelas
# e locks para proteger variáveis partilhadas
import threading

# time -> usado para timestamps e controlo temporal
import time

# dataclass -> permite criar uma classe simples para guardar estado
from dataclasses import dataclass, field

# gpype -> framework principal da aplicação
import gpype as gp

# Qt -> alinhamentos e constantes gráficas
from PySide6.QtCore import Qt

# Widgets da interface
from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QMessageBox, QWidget

# Widget base do g.Pype
from gpype.frontend.widgets.base.widget import Widget

# Importa a grelha visual 3x3 que faz os flashes
from p300_single_cell_grid import P300SingleCellGrid


# -------------------------------------------------------------------
# ESTRUTURA DE DADOS PARA GUARDAR O ESTADO DOS EVENTOS
# -------------------------------------------------------------------
@dataclass
class EventState:
    """
    Guarda o estado atual dos 3 sinais que serão enviados por UDP.

    stim_code:
        Código da célula ativa no momento.
        0 = nenhuma célula ativa
        1..9 = célula atualmente em flash

    stim_trigger:
        Aqui usamos:
        0 = flash não-target ou sem estímulo
        1 = flash target

    control_code:
        0 = idle
        1 = START_CSV
        2 = STOP_CSV

    lock:
        Lock usado para garantir que threads diferentes não acedem
        às variáveis ao mesmo tempo de forma insegura.
    """
    stim_code: int = 0
    stim_trigger: int = 0
    control_code: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


# -------------------------------------------------------------------
# THREAD QUE ENVIA CONTINUAMENTE O ESTADO POR UDP
# -------------------------------------------------------------------
class EventBroadcaster(threading.Thread):
    """
    Esta thread corre em paralelo com a interface gráfica.

    Função:
        Enviar continuamente, a 250 Hz, os 3 canais por UDP:
        - porta 12345 -> stim_code
        - porta 12346 -> stim_trigger
        - porta 12347 -> control_code

    Porque é útil:
        Em vez de enviar só impulsos pontuais, mantemos os valores
        continuamente ativos enquanto o flash decorre, criando sinais
        quadrados estáveis no lado da pipeline.
    """

    def __init__(
        self,
        state: EventState,         # estado partilhado com os valores atuais
        host="127.0.0.1",          # endereço local
        port_code=12345,           # porta do Ch09
        port_trigger=12346,        # porta do Ch10
        port_control=12347,        # porta do controlo CSV
        rate_hz=250,               # frequência de envio
    ):
        # daemon=True -> a thread fecha quando o programa principal termina
        super().__init__(daemon=True)

        # guarda referência ao estado partilhado
        self.state = state

        # guarda configurações de rede
        self.host = str(host)
        self.port_code = int(port_code)
        self.port_trigger = int(port_trigger)
        self.port_control = int(port_control)

        # frequência e período de envio
        self.rate_hz = float(rate_hz)
        self.period_s = 1.0 / self.rate_hz

        # cria socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # flag de execução
        self._running = True

        # lock para proteger a flag _running
        self._running_lock = threading.Lock()

    def stop(self):
        """
        Pede à thread para parar e fecha o socket.
        """
        with self._running_lock:
            self._running = False

        try:
            self.sock.close()
        except Exception:
            pass

    def run(self):
        """
        Método principal da thread.

        Fica num ciclo infinito até receber ordem de paragem.
        Em cada iteração:
        - lê o estado atual
        - envia os 3 valores por UDP
        - espera até à próxima amostra
        """
        next_t = time.perf_counter()

        while True:
            # verifica se deve continuar
            with self._running_lock:
                if not self._running:
                    break

            # lê os valores atuais do estado partilhado
            with self.state.lock:
                code = int(self.state.stim_code)
                trigger = int(self.state.stim_trigger)
                control = int(self.state.control_code)

            try:
                # envia Ch09 = código da célula
                self.sock.sendto(str(code).encode("utf-8"), (self.host, self.port_code))

                # envia Ch10 = trigger target/non-target
                self.sock.sendto(str(trigger).encode("utf-8"), (self.host, self.port_trigger))

                # envia código de controlo START/STOP/idle
                self.sock.sendto(str(control).encode("utf-8"), (self.host, self.port_control))

            except OSError:
                # socket foi fechado -> termina
                break
            except Exception as e:
                # outro erro qualquer -> mostra no terminal
                print(f"[ERRO] EventBroadcaster: {e}")

            # calcula o instante em que deverá enviar a próxima amostra
            next_t += self.period_s

            # calcula quanto tempo falta até lá
            sleep_s = next_t - time.perf_counter()

            if sleep_s > 0:
                time.sleep(sleep_s)
            else:
                # se estiver atrasado, reinicia o relógio para evitar drift acumulado
                next_t = time.perf_counter()


# -------------------------------------------------------------------
# CONTROLADOR PRINCIPAL DA EXPERIÊNCIA
# -------------------------------------------------------------------
class P300ExperimentController(Widget):
    """
    Widget principal da experiência P300.

    Responsabilidades:
    - criar a interface com botões e labels de estado
    - criar a grelha visual 3x3
    - reagir aos callbacks da grelha quando um estímulo começa/acaba
    - controlar o target atual
    - contar flashes target e non-target
    - manter atualizado o estado enviado por UDP
    """

    def __init__(
        self,
        labels,                        # lista de palavras/células
        rows,                          # número de linhas da grelha
        cols,                          # número de colunas da grelha
        title="P300 Experiment Controller",
        flash_ms=200,                  # duração do flash ON
        isi_ms=100,                    # intervalo OFF entre flashes
        target_idx=0,                  # índice inicial do target
        total_flashes=120,             # número total de flashes
        udp_host="127.0.0.1",
        udp_port_code=12345,
        udp_port_trigger=12346,
        udp_port_control=12347,
    ):
        # container real Qt onde o widget do g.Pype é montado
        container = QWidget()

        # chama construtor da classe base
        super().__init__(widget=container, name=title)

        # guarda parâmetros principais
        self.labels = list(labels)
        self.rows = int(rows)
        self.cols = int(cols)

        self.flash_ms = int(flash_ms)
        self.isi_ms = int(isi_ms)
        self.target_idx = int(target_idx)
        self.total_flashes = int(total_flashes)

        # variáveis de estado da experiência
        self.running = False               # indica se está a correr
        self.flash_count = 0               # número total de flashes já feitos
        self.target_count = 0              # quantos flashes target ocorreram
        self.nontarget_count = 0           # quantos flashes non-target ocorreram
        self.start_time = None             # instante de arranque

        # cria estado partilhado dos eventos
        self.event_state = EventState()

        # cria e arranca a thread que envia os sinais por UDP
        self.broadcaster = EventBroadcaster(
            state=self.event_state,
            host=udp_host,
            port_code=udp_port_code,
            port_trigger=udp_port_trigger,
            port_control=udp_port_control,
            rate_hz=250,
        )
        self.broadcaster.start()

        # cria os controlos de interface superiores
        self._build_controls()

        # cria a grelha visual
        self.grid_widget = P300SingleCellGrid(
            labels=self.labels,
            rows=self.rows,
            cols=self.cols,
            title="P300 3x3 Grid",
            flash_ms=self.flash_ms,
            isi_ms=self.isi_ms,
            target_idx=self.target_idx,
            show_target_hint=True,     # mostra borda especial no target atual
        )

        # liga os callbacks da grelha às funções deste controller
        self.grid_widget.on_stimulus_start = self._on_stimulus_start
        self.grid_widget.on_stimulus_end = self._on_stimulus_end

        # adiciona a grelha ao layout do widget
        self._layout.addWidget(self.grid_widget.widget)

        # atualiza o texto inicial
        self._refresh_status()

    def _build_controls(self):
        """
        Cria os labels de informação e os botões de controlo.
        """
        # label com target atual
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 6px;")

        # label com estatísticas da experiência
        self.stats_label = QLabel()
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setStyleSheet("font-size: 14px; padding: 4px;")

        # botões principais
        self.start_button = QPushButton("Iniciar")
        self.stop_button = QPushButton("Parar")
        self.next_target_button = QPushButton("Próximo target")

        # liga o clique dos botões às respetivas funções
        self.start_button.clicked.connect(self.start_experiment)
        self.stop_button.clicked.connect(self.stop_experiment)
        self.next_target_button.clicked.connect(self.next_target)

        # layout horizontal para os botões
        row = QHBoxLayout()
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.next_target_button)

        # adiciona tudo ao layout principal
        self._layout.addWidget(self.info_label)
        self._layout.addWidget(self.stats_label)
        self._layout.addLayout(row)

    def _refresh_status(self):
        """
        Atualiza o texto mostrado na interface:
        - target atual
        - contagens de flashes
        - estado geral
        """
        target_label = self.labels[self.target_idx]

        self.info_label.setText(
            f"Target atual: <b>{target_label}</b> &nbsp;&nbsp; "
            f"(índice {self.target_idx}, código {self.target_idx + 1})"
        )

        self.stats_label.setText(
            f"Flashes: {self.flash_count}/{self.total_flashes} | "
            f"Target: {self.target_count} | "
            f"Non-target: {self.nontarget_count} | "
            f"Estado: {'A correr' if self.running else 'Parado'}"
        )

    def _pulse_control(self, value: int, pulse_ms: int = 50):
        """
        Envia um pulso curto no canal de controlo.

        Exemplo:
            value=1 -> START_CSV
            value=2 -> STOP_CSV

        O valor fica ativo durante 'pulse_ms' milissegundos
        e depois volta automaticamente a 0.
        """
        # coloca o valor de controlo ativo
        with self.event_state.lock:
            self.event_state.control_code = int(value)

        # função interna que volta a pôr o controlo em 0
        def clear_control():
            with self.event_state.lock:
                self.event_state.control_code = 0

        # agenda a limpeza do valor após o pulso
        threading.Timer(pulse_ms / 1000.0, clear_control).start()

    def start_experiment(self):
        """
        Arranca a experiência.

        Faz:
        - impede arranque duplicado
        - reinicia contagens
        - limpa canais de evento
        - envia START_CSV
        - arranca a grelha visual
        """
        if self.running:
            return

        # marca estado como ativo
        self.running = True

        # reinicia contadores
        self.flash_count = 0
        self.target_count = 0
        self.nontarget_count = 0

        # guarda instante de arranque
        self.start_time = time.time()

        # limpa os canais de evento antes de começar
        with self.event_state.lock:
            self.event_state.stim_code = 0
            self.event_state.stim_trigger = 0

        # garante que a grelha sabe qual é o target atual
        self.grid_widget.set_target(self.target_idx)

        # envia pulso para mandar abrir o CSV na pipeline
        self._pulse_control(1)

        # arranca a sequência de flashes
        self.grid_widget.start()

        # atualiza a interface
        self._refresh_status()

        print("[INFO] Experiência iniciada.")
        print("[INFO] START_CSV enviado.")

    def stop_experiment(self):
        """
        Pára a experiência.

        Faz:
        - impede paragem duplicada
        - pára a grelha
        - limpa os canais de evento
        - envia STOP_CSV
        """
        if not self.running:
            return

        # marca estado como parado
        self.running = False

        # pára a grelha visual
        self.grid_widget.stop()

        # limpa os canais de evento
        with self.event_state.lock:
            self.event_state.stim_code = 0
            self.event_state.stim_trigger = 0

        # envia pulso para fechar o CSV
        self._pulse_control(2)

        # atualiza a interface
        self._refresh_status()

        print("[INFO] Experiência terminada.")
        print("[INFO] STOP_CSV enviado.")

    def next_target(self):
        """
        Muda para o próximo target da lista.

        Só permite mudar quando a experiência está parada.
        """
        if self.running:
            QMessageBox.information(
                self.widget,
                "Experiência a decorrer",
                "Pára primeiro a experiência antes de mudar o target."
            )
            return

        # passa ao próximo target de forma circular
        self.target_idx = (self.target_idx + 1) % len(self.labels)

        # atualiza o target na grelha
        self.grid_widget.set_target(self.target_idx)

        # atualiza labels da interface
        self._refresh_status()

    def _on_stimulus_start(self, idx, timestamp, is_target, label):
        """
        Callback chamado automaticamente pela grelha
        quando um flash começa.

        idx:
            índice da célula que começou a piscar

        timestamp:
            instante do início do flash

        is_target:
            True se a célula ativa é o target atual
            False se é non-target

        label:
            texto mostrado nessa célula
        """
        if not self.running:
            return

        # incrementa contagem global de flashes
        self.flash_count += 1

        # converte índice 0..8 para código 1..9
        cell_code = idx + 1

        # atualiza os valores que vão ser enviados continuamente por UDP
        with self.event_state.lock:
            # Ch09 = código da célula ativa
            self.event_state.stim_code = cell_code

            # Ch10 = 1 apenas se for target; 0 se for non-target
            self.event_state.stim_trigger = 1 if is_target else 0

        # atualiza contadores target/non-target
        if is_target:
            self.target_count += 1
        else:
            self.nontarget_count += 1

        # escreve informação detalhada no terminal
        print(
            f"[{timestamp:.3f}] "
            f"flash={self.flash_count} "
            f"cell_code={cell_code} "
            f"label={label} "
            f"target={is_target}"
        )

        # atualiza os labels da interface
        self._refresh_status()

    def _on_stimulus_end(self, timestamp):
        """
        Callback chamado automaticamente pela grelha
        quando um flash termina.

        Aqui voltamos os canais de evento a zero.
        """
        with self.event_state.lock:
            # fim do flash -> não há célula ativa
            self.event_state.stim_code = 0

            # fim do flash -> trigger volta a 0
            self.event_state.stim_trigger = 0

        # se já atingimos o número máximo de flashes,
        # pára automaticamente a experiência
        if self.running and self.flash_count >= self.total_flashes:
            self.stop_experiment()

    def closeEvent(self, event):
        """
        Evento chamado quando a janela está a fechar.

        Serve para:
        - limpar sinais
        - parar a thread broadcaster
        - evitar sockets abertos ao sair
        """
        try:
            with self.event_state.lock:
                self.event_state.stim_code = 0
                self.event_state.stim_trigger = 0
                self.event_state.control_code = 0

            self.broadcaster.stop()
            self.broadcaster.join(timeout=1.0)
        except Exception:
            pass

        super().closeEvent(event)


# -------------------------------------------------------------------
# FUNÇÃO PRINCIPAL
# -------------------------------------------------------------------
def main():
    """
    Ponto de entrada da aplicação.
    Cria a app, define as palavras da grelha e abre o controller.
    """
    # cria a aplicação g.Pype
    app = gp.MainApp()

    # palavras mostradas nas 9 células
    labels = [
        "Sim", "Não", "Água",
        "Dor", "Tosse", "TV",
        "Frio", "Quente", "Ajuda"
    ]

    # cria o widget controlador da experiência
    controller = P300ExperimentController(
        labels=labels,
        rows=3,
        cols=3,
        title="P300 Experiment Controller",
        flash_ms=200,
        isi_ms=100,
        target_idx=0,
        total_flashes=120,
        udp_host="127.0.0.1",
        udp_port_code=12345,
        udp_port_trigger=12346,
        udp_port_control=12347,
    )

    # adiciona o widget à app
    app.add_widget(controller)

    # corre a aplicação
    app.run()


# só executa main() se este ficheiro for corrido diretamente
if __name__ == "__main__":
    main()