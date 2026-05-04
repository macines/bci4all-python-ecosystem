# BCI4ALL — Unicorn Core-8 LSL Alpha Feedback

Real-time EEG neurofeedback system using the g.tec Unicorn Core-8 BCI headset.
Extracts the alpha band (8–12 Hz) from a selected EEG channel, computes the RMS,
and streams it via LSL for live visual and auditory feedback.

---

## Overview

```
BCICore8 → channel selector → bandpass (1–30 Hz) → notch (48–52 Hz)
        → alpha bandpass (8–12 Hz) → RMS → LSL stream (AlphaRMS)
                                              ↓
                                     receiver → bar + sound alert
```

The system is split into two independent processes communicating via LSL:

| File | Role |
|------|------|
| `single_channel_lsl_metric_sender.py` | Acquires EEG, computes alpha RMS, publishes LSL stream |
| `single_channel_lsl_metric_receiver.py` | Receives LSL stream, displays bar + triggers sound |
| `lsl_launcher.py` | GUI launcher to start/stop both processes |

---

## Requirements

```bash
pip install gpype pylsl numpy PySide6 sounddevice
```

> The `gpype` package must be installed from the project environment.
> Run all scripts using the project virtual environment Python.

---

## Usage

### Option A — Launcher (recommended)

```bash
python lsl_launcher.py
```

Use the buttons to start/stop the sender and receiver independently.

### Option B — Manual

```bash
# Terminal 1
python single_channel_lsl_metric_sender.py

# Terminal 2
python single_channel_lsl_metric_receiver.py
```

---

## Sender — `single_channel_lsl_metric_sender.py`

**Pipeline:**
1. Acquires 8-channel EEG at 250 Hz from the Unicorn Core-8
2. Selects one channel dynamically via the UI dropdown
3. Bandpass filter: 1–30 Hz (general cleaning)
4. Notch filter: 48–52 Hz (removes 50 Hz powerline noise)
5. Alpha bandpass: 8–12 Hz
6. RMS over a 1-second sliding window (250 samples)
7. Publishes the scalar RMS value to the `AlphaRMS` LSL stream at irregular rate

**LSL stream:**

| Property | Value |
|----------|-------|
| Name | `AlphaRMS` |
| Type | `METRIC` |
| Channels | 1 |
| Format | `float32` |
| Rate | irregular (event-like) |

**UI controls:**
- Dropdown to select EEG channel (0–7) during runtime
- Three time-series scopes: clean signal, alpha band, RMS

---

## Receiver — `single_channel_lsl_metric_receiver.py`

Discovers the `AlphaRMS` LSL stream automatically and displays:

- Current numeric value
- Vertical progress bar (green = normal, dark green = relaxed)
- Sound alert when value drops **below** the threshold (relaxation achieved)
- Badge `✓ RELAXADO` when below threshold

**UI controls:**

| Control | Description |
|---------|-------------|
| Escala máxima | Sets the top of the bar scale |
| Limiar do som | Threshold below which the sound fires (default: 1.5) |
| Alerta sonoro ativo | Enable/disable the sound (default: off) |

**Sound behaviour:**
- Fires on the **falling edge** of the threshold (once per crossing)
- Cooldown of 2 seconds between consecutive beeps
- Uses `sounddevice` if available; falls back to `winsound` (Windows) or system bell

---

## Configuration

Key constants in `single_channel_lsl_metric_sender.py`:

```python
fs = 250          # Sampling rate (Hz)
N  = fs           # RMS window size (1 second)
initial_channel = 7  # Default EEG channel on startup
```

Key constants in `single_channel_lsl_metric_receiver.py`:

```python
sound_threshold = 1.5   # Default relaxation threshold
sound_enabled   = False  # Sound off by default
BEEP_COOLDOWN   = 2.0   # Minimum seconds between beeps
```

---

## Project Structure

```
experiments/bar/lsl/
├── lsl_launcher.py
├── single_channel_lsl_metric_sender.py
└── single_channel_lsl_metric_receiver.py
```

---

## Notes

- The sender requires the Unicorn Core-8 to be paired and connected via Bluetooth.
- Both processes must run on the same machine (LSL uses local network discovery).
- The receiver starts searching for the LSL stream automatically on launch.
- If `sounddevice` is not installed, the sound falls back to the platform default beep.

---

## Authors

BCI4ALL Project — Unicorn Core-8 EEG Neurofeedback System