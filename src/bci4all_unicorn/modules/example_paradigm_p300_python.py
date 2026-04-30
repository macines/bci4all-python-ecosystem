"""
Nome do ficheiro:
    example_paradigm_p300_python.py

Descrição:
    Versão inicial de um paradigma tipo P300/oddball em Python, sem
    Paradigm Presenter. A aquisição/processamento corre em gpype e os
    estímulos são apresentados por um script externo em PySide6.

Fluxo:
    EEG source -> bandpass -> notch50 -> notch60 -> scopes / trigger epochs
                                   ^
                                   |
                           UDPReceiver (triggers)

Objetivo:
    Criar uma base simples e escalável para experiências ERP/P300.
"""

from pathlib import Path
import os
import subprocess
import sys

import gpype as gp

# -----------------------------
# CONFIGURAÇÃO GERAL
# -----------------------------
sampling_rate = 250
channel_count = 8

id_target = 1
id_nontarget = 2

udp_port = 12345

USE_GENERATOR = True
AUTO_START_PRESENTER = True

base_dir = os.path.dirname(os.path.abspath(__file__))
presenter_script = os.path.join(base_dir, "simple_visual_oddball_presenter.py")

# Nome do ficheiro CSV de saída
output_name = "p300_python_oddball"


if __name__ == "__main__":

    # -----------------------------
    # APP E PIPELINE
    # -----------------------------
    app = gp.MainApp()
    p = gp.Pipeline()

    # -----------------------------
    # FONTE DE SINAL
    # -----------------------------
    if USE_GENERATOR:
        amp = gp.Generator(
            sampling_rate=sampling_rate,
            channel_count=channel_count,
            signal_frequency=10,
            signal_amplitude=15,
            signal_shape="sine",
            noise_amplitude=10,
        )
        print("[INFO] A usar Generator para testes.")
    else:
        amp = gp.BCICore8()
        print("[INFO] A usar BCI Core-8.")

    # -----------------------------
    # FILTROS
    # -----------------------------
    bandpass = gp.Bandpass(f_lo=1, f_hi=30)
    notch50 = gp.Bandstop(f_lo=48, f_hi=52)
    notch60 = gp.Bandstop(f_lo=58, f_hi=62)

    # -----------------------------
    # TRIGGERS
    # -----------------------------
    trig_receiver = gp.UDPReceiver(port=udp_port)

    trig_node_target = gp.Trigger(time_pre=0.2, time_post=0.7, target=id_target)
    trig_node_nontarget = gp.Trigger(time_pre=0.2, time_post=0.7, target=id_nontarget)

    key_capture = gp.Keyboard()

    # -----------------------------
    # MARCADORES DO SCOPE
    # -----------------------------
    mk = gp.TimeSeriesScope.Markers
    markers = [
        mk(
            color="#ff0000",
            label="Target",
            channel=channel_count,
            value=id_target,
        ),
        mk(
            color="#00aa00",
            label="Nontarget",
            channel=channel_count,
            value=id_nontarget,
        ),
        mk(
            color="#0000ff",
            label="Keyboard",
            channel=channel_count + 1,
            value=77,
        ),
    ]

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
    # ROUTERS
    # -----------------------------
    router_scope = gp.Router(
        input_channels=[gp.Router.ALL, gp.Router.ALL, gp.Router.ALL]
    )
    router_raw = gp.Router(
        input_channels=[gp.Router.ALL, gp.Router.ALL, gp.Router.ALL]
    )

    # -----------------------------
    # WRITER
    # -----------------------------
    writer = gp.CsvWriter(file_name=f"{output_name}.csv")

    # -----------------------------
    # LIGAÇÕES PRINCIPAIS
    # -----------------------------
    p.connect(amp, bandpass)
    p.connect(bandpass, notch50)
    p.connect(notch50, notch60)

    # Scope data
    p.connect(notch60, router_scope["in1"])
    p.connect(trig_receiver, router_scope["in2"])
    p.connect(key_capture, router_scope["in3"])

    # Raw data
    p.connect(amp, router_raw["in1"])
    p.connect(trig_receiver, router_raw["in2"])
    p.connect(key_capture, router_raw["in3"])

    p.connect(router_scope, scope)
    p.connect(router_raw, writer)

    # Trigger extraction
    p.connect(notch60, trig_node_target[gp.Constants.Defaults.PORT_IN])
    p.connect(trig_receiver, trig_node_target[gp.Trigger.PORT_TRIGGER])

    p.connect(notch60, trig_node_nontarget[gp.Constants.Defaults.PORT_IN])
    p.connect(trig_receiver, trig_node_nontarget[gp.Trigger.PORT_TRIGGER])

    p.connect(trig_node_target, trig_scope["target"])
    p.connect(trig_node_nontarget, trig_scope["nontarget"])

    # -----------------------------
    # WIDGETS
    # -----------------------------
    app.add_widget(scope)
    app.add_widget(trig_scope)

    # -----------------------------
    # ARRANQUE OPCIONAL DO APRESENTADOR
    # -----------------------------
    presenter_process = None
    if AUTO_START_PRESENTER and os.path.exists(presenter_script):
        try:
            presenter_process = subprocess.Popen([sys.executable, presenter_script])
            print("[INFO] Presenter visual iniciado.")
        except Exception as e:
            print(f"[AVISO] Não foi possível iniciar o presenter: {e}")

    # -----------------------------
    # EXECUÇÃO
    # -----------------------------
    p.start()
    app.run()
    p.stop()

    if presenter_process is not None:
        try:
            presenter_process.terminate()
        except Exception:
            pass