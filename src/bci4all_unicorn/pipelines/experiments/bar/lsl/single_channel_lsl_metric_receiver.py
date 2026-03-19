"""
Nome do ficheiro: single_channel_lsl_metric_receiver.py

Descrição:
    Receiver LSL para feedback EEG de um único canal.
    Descobre automaticamente o stream LSL com a métrica
    AlphaRMS e apresenta o valor recebido numa interface
    gráfica simples e intuitiva.

Objetivo:
    Disponibilizar feedback visual em tempo real da métrica
    RMS da banda alfa calculada no sender, permitindo ao
    utilizador ajustar a escala máxima da barra sem alterar
    o código.

Funcionalidades:
    - procura automática do stream LSL pelo nome "AlphaRMS"
    - ligação ao stream e receção contínua de amostras
    - apresentação do valor numérico atual
    - barra vertical de feedback em tempo real
    - ajuste dinâmico da escala máxima pelo utilizador
    - indicação visual do estado da ligação LSL

Fluxo:
    Stream LSL AlphaRMS -> receção -> atualização da interface -> feedback visual
"""
# Importa o módulo sys, usado aqui para terminar corretamente a aplicação Qt.
import sys

# Importa o módulo time, usado para fazer pequenas pausas
# quando não é encontrado nenhum stream ou ocorre erro.
import time

# Importa:
# - StreamInlet: objeto que recebe dados de um stream LSL
# - resolve_byprop: função que procura streams LSL por uma propriedade específica
from pylsl import StreamInlet, resolve_byprop

# Importa componentes do Qt:
# - Qt: constantes de alinhamento e interface
# - QThread: thread separada para não bloquear a interface
# - Signal: sinais Qt para comunicar entre thread e interface
from PySide6.QtCore import Qt, QThread, Signal

# Importa widgets Qt usados na interface gráfica:
# - QApplication: aplicação principal Qt
# - QWidget: janela base
# - QLabel: textos/etiquetas
# - QVBoxLayout: layout vertical
# - QProgressBar: barra de progresso
# - QDoubleSpinBox: campo numérico decimal
# - QHBoxLayout: layout horizontal
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QProgressBar,
    QDoubleSpinBox,
    QHBoxLayout,
)


# Classe que corre numa thread separada para procurar e receber dados LSL.
# Isto evita bloquear a interface gráfica enquanto espera por streams.
class LSLWorker(QThread):

    # Sinal que envia um valor float recebido do stream para a interface.
    data = Signal(float)

    # Sinal que envia mensagens de estado para a interface.
    status = Signal(str)

    # Construtor da thread.
    def __init__(self):
        # Chama o construtor da classe base QThread.
        super().__init__()

        # Variável de controlo usada para manter a thread a correr.
        self.running = True

    # Método principal executado quando a thread é iniciada com start().
    def run(self):
        # Envia uma mensagem inicial para a interface.
        self.status.emit("À procura de stream LSL AlphaRMS...")

        # Variável que irá guardar o inlet quando o stream for encontrado.
        inlet = None

        # Enquanto a thread estiver ativa e ainda não houver ligação ao stream...
        while self.running and inlet is None:
            try:
                # Procura um stream com a propriedade "name" igual a "AlphaRMS".
                # timeout=1.0 faz a pesquisa durante até 1 segundo.
                streams = resolve_byprop("name", "AlphaRMS", timeout=1.0)

                # Se encontrou pelo menos um stream...
                if streams:
                    # Cria um inlet para receber dados do primeiro stream encontrado.
                    inlet = StreamInlet(streams[0])

                    # Obtém a informação do stream.
                    info = inlet.info()

                    # Atualiza o estado com nome, tipo e número de canais.
                    self.status.emit(
                        f"Ligado a {info.name()} | {info.type()} | {info.channel_count()} canal"
                    )
                else:
                    # Se não encontrou stream, espera 1 segundo antes de tentar novamente.
                    time.sleep(1.0)

            except Exception as e:
                # Se ocorrer erro na procura do stream, envia a mensagem de erro.
                self.status.emit(f"Erro na descoberta LSL: {e}")

                # Espera 1 segundo antes de voltar a tentar.
                time.sleep(1.0)

        # Depois de estabelecer ligação ao stream, entra no ciclo de receção.
        while self.running and inlet is not None:
            try:
                # Tenta receber uma amostra do stream.
                # timeout=0.5 evita ficar bloqueado indefinidamente.
                sample, _timestamp = inlet.pull_sample(timeout=0.5)

                # Se recebeu uma amostra válida e com pelo menos um valor...
                if sample is not None and len(sample) > 0:
                    # Envia o primeiro valor da amostra para a interface.
                    self.data.emit(float(sample[0]))

            except Exception as e:
                # Se ocorrer erro na receção, envia a mensagem para a interface.
                self.status.emit(f"Erro de receção: {e}")

                # Espera 1 segundo antes de continuar.
                time.sleep(1.0)

    # Método chamado para parar a thread de forma controlada.
    def stop(self):
        # Indica à thread para sair dos ciclos while.
        self.running = False

        # Espera que a thread termine corretamente antes de continuar.
        self.wait()


# Classe principal da aplicação gráfica.
class LSLBarApp(QWidget):

    # Construtor da janela principal.
    def __init__(self):
        # Chama o construtor da classe base QWidget.
        super().__init__()

        # Define o título da janela.
        self.setWindowTitle("BCI Alpha Feedback - LSL")

        # Define o tamanho inicial da janela.
        self.resize(320, 540)

        # Valor mínimo da escala da barra.
        self.vmin = 0.0

        # Valor máximo inicial da escala da barra.
        self.vmax = 10.0

        # Último valor recebido do stream.
        self.last_value = 0.0

        # Cria o título principal da interface.
        self.title = QLabel("ALPHA RMS FEEDBACK")

        # Centra o texto horizontalmente.
        self.title.setAlignment(Qt.AlignCenter)

        # Define o estilo visual do título.
        self.title.setStyleSheet("font-size:24px;font-weight:bold;")

        # Cria a etiqueta de estado inicial.
        self.status_label = QLabel("A iniciar...")

        # Centra o texto da etiqueta de estado.
        self.status_label.setAlignment(Qt.AlignCenter)

        # Define o estilo visual da etiqueta de estado.
        self.status_label.setStyleSheet("font-size:14px;color:gray;")

        # Cria a etiqueta descritiva do controlo de escala.
        self.scale_label = QLabel("Escala máxima:")

        # Cria um campo numérico decimal para ajustar o valor máximo da barra.
        self.scale_spin = QDoubleSpinBox()

        # Define o intervalo permitido de valores.
        self.scale_spin.setRange(0.1, 100.0)

        # Define o incremento/decremento ao usar setas.
        self.scale_spin.setSingleStep(0.1)

        # Define o valor inicial do controlo como sendo vmax.
        self.scale_spin.setValue(self.vmax)

        # Liga a alteração do valor ao método que atualiza a escala.
        self.scale_spin.valueChanged.connect(self.on_scale_changed)

        # Cria um layout horizontal para a linha da escala.
        scale_row = QHBoxLayout()

        # Adiciona a etiqueta da escala ao layout horizontal.
        scale_row.addWidget(self.scale_label)

        # Adiciona o campo numérico ao layout horizontal.
        scale_row.addWidget(self.scale_spin)

        # Cria a etiqueta que mostra o valor atual da métrica.
        self.value = QLabel("0.00")

        # Centra o valor na interface.
        self.value.setAlignment(Qt.AlignCenter)

        # Define o estilo visual do valor numérico.
        self.value.setStyleSheet("font-size:40px;color:#00AEEF;font-weight:bold;")

        # Cria a barra de progresso vertical.
        self.bar = QProgressBar()

        # Define o valor mínimo da barra.
        self.bar.setMinimum(0)

        # Define o valor máximo da barra.
        self.bar.setMaximum(400)

        # Define a orientação da barra como vertical.
        self.bar.setOrientation(Qt.Vertical)

        # Esconde o texto interno padrão da barra.
        self.bar.setTextVisible(False)

        # Define o estilo visual da barra e da parte preenchida.
        self.bar.setStyleSheet("""
            QProgressBar {
                border:2px solid grey;
                border-radius:6px;
                background:white;
                padding:2px;
            }
            QProgressBar::chunk {
                background-color:#00AEEF;
                border-radius:4px;
            }
        """)

        # Cria o layout vertical principal da janela.
        layout = QVBoxLayout(self)

        # Adiciona o título ao layout.
        layout.addWidget(self.title)

        # Adiciona a etiqueta de estado ao layout.
        layout.addWidget(self.status_label)

        # Adiciona a linha da escala ao layout.
        layout.addLayout(scale_row)

        # Adiciona a etiqueta do valor atual ao layout.
        layout.addWidget(self.value)

        # Adiciona a barra ao layout.
        layout.addWidget(self.bar)

        # Cria a thread que vai procurar e receber o stream LSL.
        self.worker = LSLWorker()

        # Liga o sinal de dados recebidos ao método que atualiza o valor.
        self.worker.data.connect(self.update_value)

        # Liga o sinal de estado à atualização direta da etiqueta de estado.
        self.worker.status.connect(self.status_label.setText)

        # Inicia a thread.
        self.worker.start()

    # Método chamado quando o utilizador altera a escala máxima.
    def on_scale_changed(self, val):
        # Atualiza o valor máximo da escala.
        self.vmax = float(val)

        # Atualiza a visualização da barra com a nova escala.
        self.refresh_display()

    # Método chamado quando chega um novo valor do stream.
    def update_value(self, val):
        # Guarda o valor mais recente.
        self.last_value = float(val)

        # Atualiza os elementos visuais com o novo valor.
        self.refresh_display()

    # Atualiza o valor numérico e a barra de feedback.
    def refresh_display(self):
        # Obtém o último valor recebido.
        val = self.last_value

        # Mostra o valor com 2 casas decimais.
        self.value.setText(f"{val:.2f}")

        # Calcula o denominador da normalização.
        denom = self.vmax - self.vmin

        # Calcula a percentagem normalizada entre 0 e 1.
        # Se a escala for inválida, usa 0.
        pct = 0.0 if denom <= 0 else (val - self.vmin) / denom

        # Garante que a percentagem fica limitada entre 0 e 1.
        pct = max(0.0, min(1.0, pct))

        # Converte a percentagem para a escala da barra (0 a 400).
        self.bar.setValue(int(pct * 400))

    # Método chamado quando a janela é fechada.
    def closeEvent(self, event):
        # Pede à thread para parar de forma segura.
        self.worker.stop()

        # Chama o comportamento padrão de fecho da janela.
        super().closeEvent(event)


# Bloco principal executado apenas quando o ficheiro é corrido diretamente.
if __name__ == "__main__":
    # Cria a aplicação Qt.
    app = QApplication(sys.argv)

    # Cria a janela principal.
    w = LSLBarApp()

    # Mostra a janela no ecrã.
    w.show()

    # Inicia o ciclo principal da aplicação e termina o programa quando a janela fechar.
    sys.exit(app.exec())