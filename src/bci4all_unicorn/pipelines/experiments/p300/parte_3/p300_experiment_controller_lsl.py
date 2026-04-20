"""
Nome do ficheiro:
    p300_experiment_controller_lsl.py

Descrição:
    Controller do protótipo P300 com eventos por LSL.

Streams LSL:
    1) P300_Markers   -> stream irregular de strings JSON
    2) P300_Control   -> stream irregular de strings ("START_CSV", "STOP_CSV")

Lógica:
    - a grelha faz flash a uma célula de cada vez
    - no início do flash envia marcador LSL com timestamp explícito
    - no fim do ensaio envia STOP_CSV
"""

import json
import sys

from pylsl import StreamInfo, StreamOutlet, local_clock
from PySide6.QtCore import QTimer
import gpype as gp

from p300_single_cell_grid import P300SingleCellGrid


LABELS = [
    "CASA", "SOL", "MAR",
    "GATO", "PÃO", "FLOR",
    "LUA", "RIO", "VIDA",
]

ROWS = 3
COLS = 3

FLASH_MS = 200
ISI_MS = 100

TARGET_IDX = 4           # centro, por exemplo
SHOW_TARGET_HINT = True

# duração total do ensaio em milissegundos
RUN_DURATION_MS = 30000


class LSLMarkerSender:
    """
    Envia marcadores e controlo via LSL.
    """

    def __init__(self):
        # stream de marcadores: irregular, 1 canal string
        marker_info = StreamInfo(
            name="P300_Markers",
            type="Markers",
            channel_count=1,
            nominal_srate=0.0,   # irregular stream
            channel_format="string",
            source_id="p300_markers_v1",
        )
        self.marker_outlet = StreamOutlet(marker_info)

        # stream de controlo: irregular, 1 canal string
        control_info = StreamInfo(
            name="P300_Control",
            type="Markers",
            channel_count=1,
            nominal_srate=0.0,
            channel_format="string",
            source_id="p300_control_v1",
        )
        self.control_outlet = StreamOutlet(control_info)

    def send_control(self, command: str):
        ts = local_clock()
        self.control_outlet.push_sample([str(command)], timestamp=ts)
        print(f"[LSL][CONTROL] {command} @ {ts:.6f}")

    def send_marker_start(self, idx: int, is_target: bool, label_text: str):
        ts = local_clock()

        payload = {
            "event": "stim_on",
            "code": int(idx + 1),                  # Ch09 -> 1..9
            "trigger": 1 if is_target else 0,      # Ch10 -> 0/1
            "idx": int(idx),
            "label": str(label_text),
            "is_target": bool(is_target),
        }

        self.marker_outlet.push_sample([json.dumps(payload)], timestamp=ts)
        print(f"[LSL][MARKER] stim_on {payload} @ {ts:.6f}")

    def send_marker_end(self):
        ts = local_clock()

        payload = {
            "event": "stim_off",
            "code": 0,
            "trigger": 0,
        }

        self.marker_outlet.push_sample([json.dumps(payload)], timestamp=ts)
        print(f"[LSL][MARKER] stim_off @ {ts:.6f}")


def main():
    app = gp.MainApp()

    sender = LSLMarkerSender()

    grid = P300SingleCellGrid(
        labels=LABELS,
        rows=ROWS,
        cols=COLS,
        title="P300 Single-Cell Grid (LSL)",
        flash_ms=FLASH_MS,
        isi_ms=ISI_MS,
        rng_seed=42,
        avoid_immediate_repeat=True,
        target_idx=TARGET_IDX,
        show_target_hint=SHOW_TARGET_HINT,
    )

    def on_stimulus_start(idx, is_target, label_text):
        sender.send_marker_start(
            idx=idx,
            is_target=is_target,
            label_text=label_text,
        )

    def on_stimulus_end():
        sender.send_marker_end()

    grid.on_stimulus_start = on_stimulus_start
    grid.on_stimulus_end = on_stimulus_end

    app.add_widget(grid)

    # arranque do ensaio
    def start_experiment():
        sender.send_control("START_CSV")
        grid.start()

    # paragem do ensaio
    def stop_experiment():
        grid.stop()
        sender.send_control("STOP_CSV")

    QTimer.singleShot(500, start_experiment)
    QTimer.singleShot(500 + RUN_DURATION_MS, stop_experiment)

    print("[INFO] Controller P300 com LSL pronto.")
    print("[INFO] Stream markers: P300_Markers")
    print("[INFO] Stream control: P300_Control")

    app.run()


if __name__ == "__main__":
    main()