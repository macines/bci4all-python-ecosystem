# Módulo do sistema para interagir com argumentos e terminar a aplicação corretamente
import sys

# Módulo para converter texto JSON em dicionários Python
import json

# Módulo de sockets para comunicação em rede via UDP
import socket

# Importação dos componentes gráficos usados na interface
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QProgressBar

# Importação de utilitários do Qt:
# - Qt: constantes e alinhamentos
# - QThread: execução de tarefas em thread separada
# - Signal: mecanismo de sinais para comunicar entre thread e interface
from PySide6.QtCore import Qt, QThread, Signal


# ==========================================
# UDP WORKER
# ==========================================
class UdpWorker(QThread):
    """
    Thread responsável por escutar mensagens UDP continuamente.
    Sempre que recebe um valor, envia-o para a interface gráfica
    através de um sinal Qt.
    """

    # Sinal que transporta um valor float para a interface
    data = Signal(float)

    def __init__(self, host="127.0.0.1", port=5005):
        """
        Construtor da thread.

        Parâmetros:
        - host: endereço IP onde o socket vai escutar
        - port: porto UDP onde o socket vai ficar à escuta
        """
        super().__init__()
        self.host = host
        self.port = port

    def run(self):
        """
        Método executado automaticamente quando a thread é iniciada com start().

        Cria um socket UDP, associa-o ao IP e porto definidos,
        e entra num ciclo infinito a receber mensagens.
        Sempre que recebe uma mensagem:
        1. descodifica os bytes para texto UTF-8
        2. converte o JSON em dicionário Python
        3. extrai o campo 'value'
        4. emite esse valor para a interface
        """

        # Cria um socket IPv4 do tipo UDP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Associa o socket ao endereço e porto definidos
        sock.bind((self.host, self.port))

        print(f"[Receiver] listening on {self.host}:{self.port}")

        # Ciclo infinito para escutar mensagens continuamente
        while True:

            # Recebe até 4096 bytes do socket
            # data = conteúdo recebido
            # _ = endereço do remetente (não está a ser usado)
            data, _ = sock.recvfrom(4096)

            # Converte os bytes recebidos para string UTF-8
            # e depois interpreta a string como JSON
            msg = json.loads(data.decode("utf-8"))

            # Obtém o campo "value" do dicionário
            # Se não existir, usa 0 como valor por defeito
            value = float(msg.get("value", 0))

            # Envia o valor para a interface através do sinal
            self.data.emit(value)


# ==========================================
# UI
# ==========================================
class BarApp(QWidget):
    """
    Janela principal da aplicação.
    Mostra:
    - um título
    - um valor numérico
    - uma barra vertical de progresso

    Recebe os valores enviados pela thread UDP e atualiza a interface.
    """

    def __init__(self):
        """
        Construtor da janela principal.
        Aqui são criados todos os elementos gráficos e iniciada a thread UDP.
        """
        super().__init__()

        # Define o título da janela
        self.setWindowTitle("BCI Alpha Feedback")

        # Define o tamanho inicial da janela
        self.resize(300, 500)

        # Intervalo de valores esperado para normalização da barra
        self.vmin = 0
        self.vmax = 6

        # Label do título
        self.title = QLabel("ALPHA POWER")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size:24px;font-weight:bold;")

        # Label que mostra o valor atual em formato numérico
        self.value = QLabel("0.00")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet("font-size:40px;color:#00AEEF;")

        # Barra de progresso vertical
        self.bar = QProgressBar()

        # Valor mínimo interno da barra
        self.bar.setMinimum(0)

        # Valor máximo interno da barra
        self.bar.setMaximum(400)

        # Define a orientação vertical da barra
        self.bar.setOrientation(Qt.Vertical)

        # Esconde o texto percentual padrão da barra
        self.bar.setTextVisible(False)

        # Aplica estilo visual à barra e ao preenchimento
        self.bar.setStyleSheet("""
            QProgressBar {
                border:2px solid grey;
                border-radius:5px;
                background:white;
            }
            QProgressBar::chunk {
                background-color:#00AEEF;
            }
        """)

        # Layout vertical da janela
        layout = QVBoxLayout(self)

        # Adiciona os widgets ao layout por ordem
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.bar)

        # Cria a thread UDP responsável por receber os dados
        self.worker = UdpWorker()

        # Liga o sinal 'data' da thread ao método update_value da interface
        self.worker.data.connect(self.update_value)

        # Inicia a thread; isto faz com que o método run() seja executado
        self.worker.start()

    def update_value(self, val):
        """
        Atualiza o valor mostrado no ecrã e a altura da barra.

        Parâmetros:
        - val: valor float recebido pela thread UDP
        """

        # Mostra o valor numérico com 2 casas decimais
        self.value.setText(f"{val:.2f}\n")
    


        # Normaliza o valor para o intervalo [0, 1]
        # Exemplo:
        # val = vmin  -> 0
        # val = vmax  -> 1
        pct = (val - self.vmin) / (self.vmax - self.vmin)

        # Garante que o valor fica limitado entre 0 e 1
        pct = max(0, min(1, pct))

        # Converte a percentagem para a escala interna da barra [0, 1000]
        self.bar.setValue(int(pct * 400))


# ==========================================
# Ponto de entrada da aplicação
# ==========================================
if __name__ == "__main__":
    """
    Este bloco só corre quando o ficheiro é executado diretamente.
    É responsável por:
    1. criar a aplicação Qt
    2. criar a janela principal
    3. mostrar a janela
    4. iniciar o ciclo de eventos
    """

    # Cria a aplicação Qt e passa os argumentos da linha de comandos
    app = QApplication(sys.argv)

    # Cria a janela principal
    w = BarApp()

    # Mostra a janela no ecrã
    w.show()

    # Inicia o loop principal da aplicação
    # sys.exit garante que o programa termina devolvendo o código correto ao sistema
    sys.exit(app.exec())