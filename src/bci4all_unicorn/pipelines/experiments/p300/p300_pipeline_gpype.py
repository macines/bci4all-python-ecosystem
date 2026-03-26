"""
Nome do ficheiro:
    p300_pipeline_gpype.py

Descrição:
    Camada 3 do protótipo P300.
    
    Este script implementa um pipeline em g.Pype responsável por:
    - adquirir sinal EEG (real ou simulado)
    - aplicar filtros ao sinal
    - receber triggers via UDP
    - preparar dados para epoching (segmentação)
    - visualizar o sinal e os eventos em tempo real
    - guardar dados em ficheiro CSV

Fluxo geral:
    EEG -> filtros -> visualização + triggers + gravação

Notas:
    - Versão inicial para integração do sistema
    - Triggers:
        1 = target
        2 = non-target
"""

# Importa a biblioteca principal do g.Pype
import gpype as gp


# -----------------------------
# CONFIGURAÇÃO GERAL
# -----------------------------

# Frequência de amostragem do sinal EEG (250 Hz típico do Unicorn)
SAMPLING_RATE = 250

# Número de canais EEG
CHANNEL_COUNT = 8

# Definição dos códigos de trigger
TRIGGER_TARGET = 1
TRIGGER_NONTARGET = 2

# Porta UDP onde os triggers vão ser recebidos
UDP_PORT = 12345

# Define se usamos sinal simulado (Generator) ou real (BCICore8)
USE_GENERATOR = True

# Nome do ficheiro onde os dados vão ser guardados
CSV_FILE = "p300_pipeline_output.csv"

# Parâmetros de epoching (janela temporal em segundos)
TIME_PRE = 0.2   # tempo antes do trigger
TIME_POST = 0.7  # tempo depois do trigger


def main():

    # Cria a aplicação gráfica
    app = gp.MainApp()

    # Cria o pipeline de processamento
    pipeline = gp.Pipeline()


    # -----------------------------
    # FONTE EEG
    # -----------------------------

    if USE_GENERATOR:
        # Cria um gerador de sinal artificial (simulação EEG)
        amp = gp.Generator(
            sampling_rate=SAMPLING_RATE,   # taxa de amostragem
            channel_count=CHANNEL_COUNT,   # número de canais
            signal_frequency=10,           # frequência da onda
            signal_amplitude=15,           # amplitude do sinal (µV)
            signal_shape="sine",           # forma do sinal (seno)
            noise_amplitude=10,            # ruído adicionado
        )
        print("[INFO] Fonte EEG: Generator")

    else:
        # Usa o dispositivo real Unicorn / BCICore8
        amp = gp.BCICore8()
        print("[INFO] Fonte EEG: BCICore8")


    # -----------------------------
    # FILTROS
    # -----------------------------

    # Filtro passa-banda (1–30 Hz)
    # Remove drift lento (<1 Hz) e ruído de alta frequência (>30 Hz)
    bandpass = gp.Bandpass(f_lo=1, f_hi=30)

    # Filtro notch 50 Hz (Europa)
    notch50 = gp.Bandstop(f_lo=48, f_hi=52, order=4)

    # Filtro notch 60 Hz (EUA)
    # notch60 = gp.Bandstop(f_lo=58, f_hi=62, order=4)


    # -----------------------------
    # RECEÇÃO DE TRIGGERS (UDP)
    # -----------------------------

    # Recebe mensagens UDP vindas da camada 2
    # Estas mensagens representam eventos (target / non-target)
    trig_receiver = gp.UDPReceiver(port=UDP_PORT)


    # -----------------------------
    # CAPTURA DE TECLADO
    # -----------------------------

    # Permite gerar eventos manualmente através do teclado
    key_capture = gp.Keyboard()


    # -----------------------------
    # NÓS DE EPOCHING (Trigger)
    # -----------------------------

    # Nó que extrai segmentos (épocas) quando recebe trigger TARGET
    trig_node_target = gp.Trigger(
        time_pre=TIME_PRE,       # tempo antes do evento
        time_post=TIME_POST,     # tempo depois do evento
        target=TRIGGER_TARGET,   # valor do trigger
    )

    # Nó que extrai segmentos para NON-TARGET
    trig_node_nontarget = gp.Trigger(
        time_pre=TIME_PRE,
        time_post=TIME_POST,
        target=TRIGGER_NONTARGET,
    )


    # -----------------------------
    # ROUTERS
    # -----------------------------

    # Router para juntar:
    # EEG + triggers UDP + teclado → para visualização
    router_scope = gp.Router(
        input_channels=[gp.Router.ALL, gp.Router.ALL, gp.Router.ALL]
    )

    # Router para juntar:
    # EEG bruto + triggers + teclado → para gravação
    router_raw = gp.Router(
        input_channels=[gp.Router.ALL, gp.Router.ALL, gp.Router.ALL]
    )


    # -----------------------------
    # MARCADORES VISUAIS
    # -----------------------------

    # Classe interna para criar marcadores no gráfico
    mk = gp.TimeSeriesScope.Markers

    # Lista de marcadores a mostrar no gráfico
    markers = [
        mk(
            color="#ff0000",        # vermelho
            label="Target",
            channel=CHANNEL_COUNT, # canal virtual
            value=TRIGGER_TARGET,
        ),
        mk(
            color="#00aa00",        # verde
            label="Nontarget",
            channel=CHANNEL_COUNT,
            value=TRIGGER_NONTARGET,
        ),
        mk(
            color="#0000ff",        # azul
            label="Keyboard",
            channel=CHANNEL_COUNT + 1,
            value=77,
        ),
    ]


    # -----------------------------
    # WIDGETS (VISUALIZAÇÃO)
    # -----------------------------

    # Scope principal (EEG em tempo real)
    scope = gp.TimeSeriesScope(
        amplitude_limit=50,  # escala vertical (µV)
        time_window=10,      # janela temporal (segundos)
        markers=markers,     # marcadores visuais
    )

    # Scope específico para triggers (ERP)
    trig_scope = gp.TriggerScope(
        amplitude_limit=10,
        plots=["target", "nontarget", "target-nontarget"],
    )


    # -----------------------------
    # GRAVAÇÃO
    # -----------------------------

    # Nó que grava dados em CSV
    writer = gp.CsvWriter(file_name=CSV_FILE)


    # -----------------------------
    # LIGAÇÕES DO PIPELINE
    # -----------------------------

    # Pipeline principal de filtragem
    pipeline.connect(amp, bandpass)
    pipeline.connect(bandpass, notch50)
    pipeline.connect(notch50, notch60)

    # Envia sinal filtrado + triggers + teclado para o scope
    pipeline.connect(notch60, router_scope["in1"])
    pipeline.connect(trig_receiver, router_scope["in2"])
    pipeline.connect(key_capture, router_scope["in3"])

    # Envia dados brutos + triggers + teclado para gravação
    pipeline.connect(amp, router_raw["in1"])
    pipeline.connect(trig_receiver, router_raw["in2"])
    pipeline.connect(key_capture, router_raw["in3"])

    # Liga routers aos destinos
    pipeline.connect(router_scope, scope)
    pipeline.connect(router_raw, writer)


    # -----------------------------
    # TRIGGER NODES (DESATIVADOS)
    # -----------------------------

    # Estes blocos estão comentados porque ainda não estão a ser usados
    # Servem para criar épocas (ERP) alinhadas com triggers

    # pipeline.connect(notch60, trig_node_target["in"])
    # pipeline.connect(trig_receiver, trig_node_target["trigger"])

    # pipeline.connect(notch60, trig_node_nontarget["in"])
    # pipeline.connect(trig_receiver, trig_node_nontarget["trigger"])

    # pipeline.connect(trig_node_target, trig_scope["target"])
    # pipeline.connect(trig_node_nontarget, trig_scope["nontarget"])


    # -----------------------------
    # INTERFACE GRÁFICA
    # -----------------------------

    # Adiciona os widgets à aplicação
    app.add_widget(scope)
    app.add_widget(trig_scope)


    # -----------------------------
    # INFORMAÇÃO NO TERMINAL
    # -----------------------------

    print("[INFO] Pipeline pronta.")
    print(f"[INFO] À escuta de triggers UDP na porta {UDP_PORT}")
    print(f"[INFO] Trigger {TRIGGER_TARGET} = TARGET")
    print(f"[INFO] Trigger {TRIGGER_NONTARGET} = NON-TARGET")


    # -----------------------------
    # EXECUÇÃO
    # -----------------------------

    # Inicia o pipeline (começa aquisição e processamento)
    pipeline.start()

    # Abre a interface gráfica (bloqueia execução)
    app.run()

    # Para o pipeline quando a app fecha
    pipeline.stop()


# Ponto de entrada do programa
if __name__ == "__main__":
    main()
