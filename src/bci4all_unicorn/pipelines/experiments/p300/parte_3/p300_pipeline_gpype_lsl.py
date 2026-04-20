"""
Nome do ficheiro:
    p300_pipeline_gpype_lsl.py

Descrição:
    Camada 3 do protótipo P300 com marcadores LSL.

Função:
    - adquirir EEG
    - filtrar sinal
    - receber marcadores LSL (P300_Markers)
    - receber controlo LSL (P300_Control)
    - anexar Ch09 e Ch10 ao EEG
    - mostrar EEG num scope
    - mostrar eventos noutro scope
    - gravar CSV único com:
        Time, Timestamp, Ch01..Ch10
"""

import csv
import json
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import gpype as gp
from pylsl import resolve_byprop, StreamInlet

from gpype.backend.core.io_node import IONode
from gpype.common.constants import Constants

PORT_IN = Constants.Defaults.PORT_IN
PORT_OUT = Constants.Defaults.PORT_OUT

SAMPLING_RATE = 250
EEG_CHANNEL_COUNT = 8
CSV_FILE = "p300_full_output_lsl.csv"

USE_GENERATOR = True


@dataclass
class TimedMarker:
    code: float
    trigger: float
    timestamp_lsl: float


@dataclass
class SharedMarkers:
    events: deque = field(default_factory=deque)
    lock: threading.Lock = field(default_factory=threading.Lock)


class LSLMarkerListener(threading.Thread):
    """
    Lê marcadores LSL irregulares do stream P300_Markers.
    """

    def __init__(self, shared_state, stream_name="P300_Markers"):
        super().__init__(daemon=True)
        self.shared_state = shared_state
        self.stream_name = str(stream_name)
        self.running = True
        self.inlet = None
        self.time_offset = 0.0

    def stop(self):
        self.running = False

    def run(self):
        try:
            print(f"[INFO] À procura do stream LSL '{self.stream_name}'...")
            streams = resolve_byprop("name", self.stream_name, timeout=10)
            if not streams:
                print(f"[WARN] Stream LSL '{self.stream_name}' não encontrado.")
                return

            self.inlet = StreamInlet(streams[0], max_buflen=5)
            self.time_offset = self.inlet.time_correction()
            print(f"[INFO] Stream LSL '{self.stream_name}' ligado.")
            print(f"[INFO] time_correction = {self.time_offset:.6f}s")

            while self.running:
                sample, ts = self.inlet.pull_sample(timeout=0.2)
                if sample is None:
                    continue

                try:
                    msg = json.loads(sample[0])
                    code = float(msg.get("code", 0.0))
                    trigger = float(msg.get("trigger", 0.0))

                    # converte para domínio temporal local do recetor
                    corrected_ts = float(ts + self.time_offset)

                    evt = TimedMarker(
                        code=code,
                        trigger=trigger,
                        timestamp_lsl=corrected_ts,
                    )

                    with self.shared_state.lock:
                        self.shared_state.events.append(evt)

                except Exception as e:
                    print(f"[WARN] Marcador LSL inválido: {e}")

        except Exception as e:
            print(f"[ERROR] LSLMarkerListener: {e}")


class CsvWriterWithTimestamp(IONode):
    """
    Writer customizado para gravar:
        Time, Timestamp, Ch01..Ch10

    Continua a calcular o eixo temporal com sample_idx/fs.
    """
    def __init__(self, file_name: str, sampling_rate: int, channel_count: int = 10):
        super().__init__(target=None)

        self.file_name = str(file_name)
        self.sampling_rate = int(sampling_rate)
        self.channel_count = int(channel_count)

        self.sample_idx = 0
        self.start_dt = None

        self._fh = None
        self._writer = None
        self.is_recording = False
        self.file_opened = False

    def _open_file(self):
        self.start_dt = datetime.now()
        self.sample_idx = 0

        self._fh = open(self.file_name, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(
            ["Time", "Timestamp"] + [f"Ch{i:02d}" for i in range(1, self.channel_count + 1)]
        )
        self.file_opened = True
        self.is_recording = True
        print(f"[INFO] CSV iniciado: {self.file_name}")

    def _close_file(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass

        self._fh = None
        self._writer = None
        self.file_opened = False
        self.is_recording = False
        print("[INFO] CSV terminado.")

    def _normalize_to_samples_channels(self, arr):
        arr = np.asarray(arr)

        if arr.ndim == 1:
            if arr.size == self.channel_count:
                arr = arr.reshape(1, -1)
            else:
                arr = arr.reshape(-1, 1)

        if arr.ndim != 2:
            return None

        if arr.shape[1] == self.channel_count:
            return arr

        if arr.shape[0] == self.channel_count:
            return arr.T

        return None

    def step(self, data):
        if PORT_IN not in data:
            return

        arr = self._normalize_to_samples_channels(data[PORT_IN])
        if arr is None:
            return

        if not self.is_recording:
            return

        for row in arr:
            time_s = self.sample_idx / self.sampling_rate
            ts = self.start_dt + timedelta(seconds=time_s)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")

            self._writer.writerow(
                [f"{time_s:.3f}", ts_str] + [f"{float(v):.6f}" for v in row]
            )
            self.sample_idx += 1

        if self._fh is not None:
            self._fh.flush()

    def start_recording(self):
        if not self.file_opened:
            self._open_file()
        else:
            self.is_recording = True

    def stop_recording(self):
        if self.file_opened:
            self._close_file()

    def __del__(self):
        try:
            self._close_file()
        except Exception:
            pass


class LSLControlListener(threading.Thread):
    """
    Escuta o stream LSL P300_Control e controla START/STOP do CSV.
    """

    def __init__(self, writer, stream_name="P300_Control"):
        super().__init__(daemon=True)
        self.writer = writer
        self.stream_name = str(stream_name)
        self.running = True
        self.inlet = None

    def stop(self):
        self.running = False

    def run(self):
        try:
            print(f"[INFO] À procura do stream LSL '{self.stream_name}'...")
            streams = resolve_byprop("name", self.stream_name, timeout=10)
            if not streams:
                print(f"[WARN] Stream LSL '{self.stream_name}' não encontrado.")
                return

            self.inlet = StreamInlet(streams[0], max_buflen=5)
            print(f"[INFO] Stream LSL '{self.stream_name}' ligado.")

            while self.running:
                sample, _ = self.inlet.pull_sample(timeout=0.2)
                if sample is None:
                    continue

                cmd = str(sample[0]).strip().upper()

                if cmd == "START_CSV":
                    self.writer.start_recording()
                elif cmd == "STOP_CSV":
                    self.writer.stop_recording()

        except Exception as e:
            print(f"[ERROR] LSLControlListener: {e}")


class AppendTimedLSLMarkers(IONode):
    """
    Recebe EEG e injeta Ch09 e Ch10 usando timestamps LSL dos marcadores.

    Estratégia:
        - o eixo temporal do bloco é reconstruído por sample count / fs
        - os marcadores têm timestamp LSL corrigido
        - cada evento é colocado no índice de amostra correspondente
    """

    def __init__(self, shared_markers, eeg_channel_count=8, sampling_rate=250):
        super().__init__(target=None)
        self.shared_markers = shared_markers
        self.eeg_channel_count = int(eeg_channel_count)
        self.sampling_rate = int(sampling_rate)

        self.total_samples_processed = 0
        self.pipeline_lsl_t0 = None

        self.current_code = 0.0
        self.current_trigger = 0.0

    def setup(self, data, port_context_in):
        port_context_out = super().setup(data, port_context_in)
        port_context_out[PORT_OUT][Constants.Keys.CHANNEL_COUNT] = self.eeg_channel_count + 2

        # usa o instante do setup como referência temporal do stream processado
        # é uma aproximação robusta quando não tens timestamp explícito por amostra do source
        from pylsl import local_clock
        self.pipeline_lsl_t0 = local_clock()
        self.total_samples_processed = 0

        return port_context_out

    def _normalize_to_samples_channels(self, arr):
        arr = np.asarray(arr)

        if arr.ndim == 1:
            if arr.size == self.eeg_channel_count:
                arr = arr.reshape(1, -1)
            else:
                arr = arr.reshape(-1, 1)

        if arr.ndim != 2:
            return None

        if arr.shape[1] == self.eeg_channel_count:
            return arr

        if arr.shape[0] == self.eeg_channel_count:
            return arr.T

        return None

    def step(self, data):
        if PORT_IN not in data:
            return None

        eeg = self._normalize_to_samples_channels(data[PORT_IN])
        if eeg is None:
            return None

        n_samples = eeg.shape[0]

        block_start_lsl = self.pipeline_lsl_t0 + (
            self.total_samples_processed / self.sampling_rate
        )
        block_end_lsl = self.pipeline_lsl_t0 + (
            (self.total_samples_processed + n_samples) / self.sampling_rate
        )

        code_col = np.full((n_samples, 1), self.current_code, dtype=float)
        trigger_col = np.full((n_samples, 1), self.current_trigger, dtype=float)

        events_to_apply = []

        with self.shared_markers.lock:
            while self.shared_markers.events and self.shared_markers.events[0].timestamp_lsl <= block_end_lsl:
                events_to_apply.append(self.shared_markers.events.popleft())

        for evt in events_to_apply:
            if evt.timestamp_lsl < block_start_lsl:
                self.current_code = evt.code
                self.current_trigger = evt.trigger
                code_col[:, 0] = self.current_code
                trigger_col[:, 0] = self.current_trigger
                continue

            sample_offset = int(round((evt.timestamp_lsl - block_start_lsl) * self.sampling_rate))
            sample_offset = max(0, min(sample_offset, n_samples - 1))

            code_col[sample_offset:, 0] = evt.code
            trigger_col[sample_offset:, 0] = evt.trigger

            self.current_code = evt.code
            self.current_trigger = evt.trigger

        merged = np.hstack((eeg, code_col, trigger_col))
        self.total_samples_processed += n_samples

        return {PORT_OUT: merged}


def main():
    app = gp.MainApp()
    pipeline = gp.Pipeline()

    if USE_GENERATOR:
        amp = gp.Generator(
            sampling_rate=SAMPLING_RATE,
            channel_count=EEG_CHANNEL_COUNT,
            signal_frequency=10,
            signal_amplitude=15,
            signal_shape="sine",
            noise_amplitude=10,
        )
        print("[INFO] Fonte EEG: Generator")
    else:
        amp = gp.BCICore8()
        print("[INFO] Fonte EEG: BCICore8")

    bandpass = gp.Bandpass(f_lo=1, f_hi=30)
    notch50 = gp.Bandstop(f_lo=48, f_hi=52)
    notch60 = gp.Bandstop(f_lo=58, f_hi=62)

    shared_markers = SharedMarkers()

    marker_listener = LSLMarkerListener(
        shared_state=shared_markers,
        stream_name="P300_Markers",
    )

    merge_markers = AppendTimedLSLMarkers(
        shared_markers=shared_markers,
        eeg_channel_count=EEG_CHANNEL_COUNT,
        sampling_rate=SAMPLING_RATE,
    )

    writer = CsvWriterWithTimestamp(
        file_name=CSV_FILE,
        sampling_rate=SAMPLING_RATE,
        channel_count=10,
    )

    control_listener = LSLControlListener(
        writer=writer,
        stream_name="P300_Control",
    )

    scope_eeg = gp.TimeSeriesScope(
        amplitude_limit=50,
        time_window=10,
        hidden_channels=[8, 9],
    )

    scope_events = gp.TimeSeriesScope(
        amplitude_limit=12,
        time_window=10,
        hidden_channels=[0, 1, 2, 3, 4, 5, 6, 7],
    )

    marker_listener.start()
    control_listener.start()

    pipeline.connect(amp, bandpass)
    pipeline.connect(bandpass, notch50)
    pipeline.connect(notch50, notch60)
    pipeline.connect(notch60, merge_markers)

    pipeline.connect(merge_markers, scope_eeg)
    pipeline.connect(merge_markers, scope_events)
    pipeline.connect(merge_markers, writer)

    app.add_widget(scope_eeg)
    app.add_widget(scope_events)

    print("[INFO] Pipeline pronta.")
    print("[INFO] LSL marker stream: P300_Markers")
    print("[INFO] LSL control stream: P300_Control")
    print("[INFO] Ch09 = code (0..9)")
    print("[INFO] Ch10 = trigger (0/1)")

    try:
        pipeline.start()
        app.run()
    finally:
        pipeline.stop()

        control_listener.stop()
        marker_listener.stop()

        control_listener.join(timeout=1.0)
        marker_listener.join(timeout=1.0)


if __name__ == "__main__":
    main()