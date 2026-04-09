"""
CAMADA 3

Nome do ficheiro:
    p300_pipeline_gpype.py

Descrição:
    Camada 3 do protótipo P300.
    Pipeline gpype para:
    - adquirir EEG
    - filtrar sinal
    - receber triggers UDP vindos da camada 2
    - segmentar épocas target / non-target
    - visualizar ERP inicial em TriggerScope
    - gravar dados em CSV

Fluxo:
    EEG source -> bandpass -> notch50 -> notch60 -> scope / trigger nodes
                                           ^
                                           |
                                     UDPReceiver

Notas:
    - Esta versão é inicial e serve para validar a integração.
    - Usa triggers:
        1 = target
        2 = non-target
"""

import gpype as gp

# -----------------------------
# CONFIGURAÇÃO GERAL
# -----------------------------
SAMPLING_RATE = 250
CHANNEL_COUNT = 8

TRIGGER_TARGET = 1
TRIGGER_NONTARGET = 2

UDP_PORT = 12345

USE_GENERATOR = True  
CSV_FILE = "p300_pipeline_output.csv"

# Janelas para ERP / epoching
TIME_PRE = 0.2
TIME_POST = 0.7


def main():
    app = gp.MainApp()
    pipeline = gp.Pipeline()

    # -----------------------------
    # FONTE EEG
    # -----------------------------
    if USE_GENERATOR:
        amp = gp.Generator(
            sampling_rate=SAMPLING_RATE,
            channel_count=CHANNEL_COUNT,
            signal_frequency=10,
            signal_amplitude=15,
            signal_shape="sine",
            noise_amplitude=10,
        )
        print("[INFO] Fonte EEG: Generator")
    else:
        amp = gp.BCICore8()
        print("[INFO] Fonte EEG: BCICore8")

    # -----------------------------
    # FILTROS
    # -----------------------------
    bandpass = gp.Bandpass(f_lo=1, f_hi=30)
    notch50 = gp.Bandstop(f_lo=48, f_hi=52)
    notch60 = gp.Bandstop(f_lo=58, f_hi=62)

    # -----------------------------
    # RECEÇÃO DE TRIGGERS
    # -----------------------------
    trig_receiver = gp.UDPReceiver(port=UDP_PORT)

    # -----------------------------
    # CAPTURA DE TECLADO (opcional)
    # -----------------------------
    key_capture = gp.Keyboard()

    # -----------------------------
    # NÓS DE EPOCHING
    # -----------------------------
    trig_node_target = gp.Trigger(
        time_pre=TIME_PRE,
        time_post=TIME_POST,
        target=TRIGGER_TARGET,
    )

    trig_node_nontarget = gp.Trigger(
        time_pre=TIME_PRE,
        time_post=TIME_POST,
        target=TRIGGER_NONTARGET,
    )

    # -----------------------------
    # ROUTERS PARA SCOPE E GRAVAÇÃO
    # -----------------------------
    router_scope = gp.Router(
        input_channels=[gp.Router.ALL, gp.Router.ALL, gp.Router.ALL]
    )

    router_raw = gp.Router(
        input_channels=[gp.Router.ALL, gp.Router.ALL, gp.Router.ALL]
    )

    # -----------------------------
    # MARCADORES VISUAIS NO SCOPE
    # -----------------------------
    mk = gp.TimeSeriesScope.Markers
    markers = [
        mk(
            color="#ff0000",
            label="Target",
            channel=CHANNEL_COUNT,
            value=TRIGGER_TARGET,
        ),
        mk(
            color="#00aa00",
            label="Nontarget",
            channel=CHANNEL_COUNT,
            value=TRIGGER_NONTARGET,
        ),
        mk(
            color="#0000ff",
            label="Keyboard",
            channel=CHANNEL_COUNT + 1,
            value=77,
        ),
    ]

    # -----------------------------
    # WIDGETS DE VISUALIZAÇÃO
    # -----------------------------
    scope = gp.TimeSeriesScope(
        amplitude_limit=50,
        time_window=10,
        markers=markers,
    )

    trig_scope = gp.TriggerScope(
        amplitude_limit=10,
        plots=["target", "nontarget", "target-nontarget"],
    )

    # -----------------------------
    # GRAVAÇÃO
    # -----------------------------
    writer = gp.CsvWriter(file_name=CSV_FILE)

    # -----------------------------
    # LIGAÇÕES PRINCIPAIS
    # -----------------------------
    pipeline.connect(amp, bandpass)
    pipeline.connect(bandpass, notch50)
    pipeline.connect(notch50, notch60)

    # Scope com EEG + triggers + keyboard
    pipeline.connect(notch60, router_scope["in1"])
    pipeline.connect(trig_receiver, router_scope["in2"])
    pipeline.connect(key_capture, router_scope["in3"])

    # Raw writer com EEG + triggers + keyboard
    pipeline.connect(amp, router_raw["in1"])
    pipeline.connect(trig_receiver, router_raw["in2"])
    pipeline.connect(key_capture, router_raw["in3"])

    pipeline.connect(router_scope, scope)
    pipeline.connect(router_raw, writer)

    # Trigger nodes
    #
    # pipeline.connect(notch60, trig_node_target[gp.Constants.Defaults.PORT_IN])
    # pipeline.connect(trig_receiver, trig_node_target[gp.Trigger.PORT_TRIGGER])

    # pipeline.connect(notch60, trig_node_nontarget[gp.Constants.Defaults.PORT_IN])
    # pipeline.connect(trig_receiver, trig_node_nontarget[gp.Trigger.PORT_TRIGGER])

    # pipeline.connect(trig_node_target, trig_scope["target"])
    # pipeline.connect(trig_node_nontarget, trig_scope["nontarget"])

    # -----------------------------
    # UI
    # -----------------------------
    app.add_widget(scope)
    app.add_widget(trig_scope)

    print("[INFO] Pipeline pronta.")
    print(f"[INFO] À escuta de triggers UDP na porta {UDP_PORT}")
    print(f"[INFO] Trigger {TRIGGER_TARGET} = TARGET")
    print(f"[INFO] Trigger {TRIGGER_NONTARGET} = NON-TARGET")

    # -----------------------------
    # EXECUÇÃO
    # -----------------------------
    pipeline.start()
    app.run()
    pipeline.stop()


if __name__ == "__main__":
    main()