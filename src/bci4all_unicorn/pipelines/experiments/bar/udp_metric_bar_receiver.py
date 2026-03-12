# Módulo do sistema
# Aqui é usado para aceder aos argumentos da aplicação e terminar corretamente o programa
import sys

# Módulo para trabalhar com JSON
# Serve para converter mensagens recebidas por UDP em dicionários Python
import json

# Módulo para comunicação em rede por sockets
# Aqui é usado para receber mensagens UDP
import socket

# Módulo para trabalhar com tempo
# Aqui é usado para detetar há quanto tempo chegou o último pacote
import time

# Importa classes base do Qt Core:
# - Qt: constantes e alinhamentos
# - QThread: thread separada da interface gráfica
# - Signal: mecanismo de comunicação entre thread e UI
from PySide6.QtCore import Qt, QThread, Signal

# Importa os widgets da interface gráfica
from PySide6.QtWidgets import (
    QApplication,   # aplicação Qt
    QWidget,        # janela base
    QVBoxLayout,    # layout vertical
    QLabel,         # texto na interface
    QProgressBar,   # barra de progresso
)


class UdpWorker(QThread):
    """
    Thread responsável por escutar dados UDP sem bloquear a interface gráfica.

    Esta thread:
    - abre um socket UDP
    - fica à escuta no host/porto definidos
    - recebe mensagens JSON
    - extrai metric, channel e value
    - emite sinais para atualizar a interface
    """

    # Sinal emitido quando chega um pacote válido
    # Transporta:
    # - metric (str)
    # - channel (str)
    # - value (float)
    data_received = Signal(str, str, float)

    # Sinal emitido para atualizar o estado/diagnóstico da receção
    status_changed = Signal(str)

    def __init__(self, host="127.0.0.1", port=5005):
        """
        Construtor da thread UDP.

        Parâmetros:
        - host: endereço IP onde o receiver vai escutar
        - port: porto UDP onde o receiver vai escutar
        """
        super().__init__()

        # Guarda o host como string
        self.host = str(host)

        # Guarda o porto como inteiro
        self.port = int(port)

        # Flag de controlo da execução da thread
        # Enquanto for True, o ciclo principal continua
        self.running = True

        # Referência ao socket; começa a None até ser criado no run()
        self.sock = None

    def run(self):
        """
        Método executado automaticamente quando a thread é iniciada com start().

        Fluxo:
        1. cria o socket UDP
        2. faz bind ao host/porto
        3. define timeout para não bloquear indefinidamente
        4. entra num ciclo de receção
        5. quando recebe dados:
           - descodifica UTF-8
           - interpreta JSON
           - extrai metric, channel e value
           - emite sinal para a UI
        6. se não receber dados durante algum tempo, atualiza o estado
        7. fecha o socket no final
        """
        try:
            # Cria um socket UDP IPv4
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Associa o socket ao IP e porto indicados
            self.sock.bind((self.host, self.port))

            # Define timeout de 0.5 segundos para recvfrom()
            # Isto permite verificar periodicamente a flag self.running
            self.sock.settimeout(0.5)

            # Notifica a interface que o receiver está à escuta
            self.status_changed.emit(f"Listening on {self.host}:{self.port}")

            # Guarda o instante do último pacote recebido
            # Começa em 0.0, ou seja, ainda não chegou nada
            last_rx = 0.0

            # Ciclo principal da thread
            while self.running:
                try:
                    # Recebe até 4096 bytes via UDP
                    data, _addr = self.sock.recvfrom(4096)

                    # Converte os bytes recebidos em texto UTF-8
                    # e interpreta o conteúdo como JSON
                    msg = json.loads(data.decode("utf-8"))

                    # Extrai os campos esperados do JSON
                    # Se algum não existir, usa um valor por defeito
                    metric = str(msg.get("metric", "alpha_rms"))
                    channel = str(msg.get("channel", "-"))
                    value = float(msg.get("value", 0.0))

                    # Atualiza o instante do último pacote recebido
                    last_rx = time.time()

                    # Emite os dados para a interface gráfica
                    self.data_received.emit(metric, channel, value)

                    # Atualiza o estado para indicar que está a receber
                    self.status_changed.emit("Status: receiving")

                except socket.timeout:
                    # Se não chegou nada dentro do timeout,
                    # verifica se já passaram mais de 2 segundos desde a última receção
                    if last_rx != 0.0 and (time.time() - last_rx) > 2.0:
                        self.status_changed.emit("Status: no recent data")
                    continue

                except Exception as e:
                    # Se houver erro ao processar um pacote, notifica a interface
                    # e continua a escutar os próximos pacotes
                    self.status_changed.emit(f"Error: {e}")
                    continue

        except Exception as e:
            # Se houver erro ao arrancar o socket/bind, informa a interface
            self.status_changed.emit(f"Startup error: {e}")

        finally:
            # Garante o fecho do socket quando a thread termina
            if self.sock is not None:
                try:
                    self.sock.close()
                except Exception:
                    pass

    def stop(self):
        """
        Pede à thread para parar.

        Não termina imediatamente o socket.recvfrom(),
        mas como existe timeout, a thread sai pouco depois.
        """
        self.running = False


class UdpBarWindow(QWidget):
    """
    Janela principal da aplicação receiver.

    Esta janela:
    - mostra o nome da métrica recebida
    - mostra o canal
    - mostra o valor numérico
    - mostra o estado da receção
    - mostra uma barra vertical proporcional ao valor
    """

    def __init__(self, host="127.0.0.1", port=5005):
        """
        Construtor da janela principal.

        Parâmetros:
        - host: IP onde a thread UDP vai escutar
        - port: porto UDP onde a thread UDP vai escutar
        """
        super().__init__()

        # Guarda host e porto
        self.host = str(host)
        self.port = int(port)

        # Define título da janela
        self.setWindowTitle("Alpha RMS Receiver")

        # Define tamanho inicial da janela
        self.resize(280, 420)

        # Escala esperada para normalização da barra
        self.vmin = 0.0
        self.vmax = 30.0

        # Último valor recebido
        self.last_value = 0.0

        # Label do nome da métrica
        self.title_label = QLabel("Waiting for UDP data...")
        self.title_label.setAlignment(Qt.AlignCenter)

        # Label do canal recebido
        self.channel_label = QLabel("Channel: -")
        self.channel_label.setAlignment(Qt.AlignCenter)

        # Label do valor numérico atual
        self.value_label = QLabel("0.000")
        self.value_label.setAlignment(Qt.AlignCenter)

        # Label do estado atual do receiver
        self.status_label = QLabel("Starting...")
        self.status_label.setAlignment(Qt.AlignCenter)

        # Barra vertical que representa o valor recebido
        self.bar = QProgressBar()
        self.bar.setMinimum(0)          # mínimo interno da barra
        self.bar.setMaximum(1000)       # máximo interno da barra
        self.bar.setValue(0)            # começa a zero
        self.bar.setOrientation(Qt.Vertical)  # barra vertical
        self.bar.setMinimumWidth(80)    # largura mínima
        self.bar.setMinimumHeight(280)  # altura mínima
        self.bar.setTextVisible(False)  # esconde o texto interno da barra

        # Cria um layout vertical associado à janela
        layout = QVBoxLayout(self)

        # Adiciona os widgets ao layout por ordem
        layout.addWidget(self.title_label)
        layout.addWidget(self.channel_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.status_label)

        # Adiciona a barra e centra-a horizontalmente
        layout.addWidget(self.bar, alignment=Qt.AlignCenter)

        # Cria a thread de receção UDP
        self.worker = UdpWorker(host=self.host, port=self.port)

        # Liga os sinais da thread aos métodos da janela
        self.worker.data_received.connect(self.on_data_received)
        self.worker.status_changed.connect(self.on_status_changed)

        # Inicia a thread
        self.worker.start()

    def on_data_received(self, metric, channel, value):
        """
        Método chamado sempre que chega um pacote válido.

        Parâmetros:
        - metric: nome da métrica recebida
        - channel: canal associado
        - value: valor numérico recebido
        """
        # Guarda o último valor recebido
        self.last_value = float(value)

        # Atualiza os textos da interface
        self.title_label.setText(metric)
        self.channel_label.setText(f"Channel: {channel}")
        self.value_label.setText(f"{self.last_value:.3f}")

        # Inicializa a percentagem normalizada
        pct = 0.0

        # Só calcula se a escala for válida
        if self.vmax > self.vmin:
            pct = (self.last_value - self.vmin) / (self.vmax - self.vmin)

        # Limita o valor ao intervalo [0, 1]
        pct = max(0.0, min(1.0, pct))

        # Converte para a escala interna da barra [0, 1000]
        self.bar.setValue(int(pct * 1000))

    def on_status_changed(self, text):
        """
        Método chamado quando a thread quer atualizar o estado.

        Parâmetros:
        - text: mensagem de estado
        """
        # Atualiza a label de estado
        self.status_label.setText(text)

        # Também imprime o estado no terminal para debug
        print(f"[UDP RECEIVER] {text}")

    def closeEvent(self, event):
        """
        Evento chamado quando a janela vai ser fechada.

        Aqui:
        - pede-se à thread para parar
        - espera-se até 1 segundo pelo fecho
        - depois chama-se o comportamento normal da janela
        """
        self.worker.stop()
        self.worker.wait(1000)
        super().closeEvent(event)


if __name__ == "__main__":
    # Cria a aplicação Qt
    app = QApplication(sys.argv)

    # Cria a janela principal do receiver
    win = UdpBarWindow(host="127.0.0.1", port=5005)

    # Mostra a janela
    win.show()

    # Inicia o loop principal da aplicação
    sys.exit(app.exec())