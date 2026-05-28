#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Análise básica de ERP P300 a partir de CSV transposto BCI4ALL/gpype.

Formato esperado do CSV:
    Time, t1, t2, t3, ...
    Timestamp, ts1, ts2, ts3, ...
    Ch01, ...
    ...
    Ch08, ...
    Ch09, ...   # código do evento
    Ch10, ...   # trigger/código target

Codificação esperada:
    Ch09 = 1..9  -> non-target / distractor
    Ch09 = 70    -> target
    Ch09 = 0     -> sem evento
    Ch10 != 0    -> célula target correspondente

O script:
    1. Lê o CSV transposto.
    2. Converte para DataFrame normal: uma linha por amostra.
    3. Deteta eventos pontuais em Ch09.
    4. Conta targets e non-targets.
    5. Extrai epochs à volta de cada evento.
    6. Aplica baseline correction.
    7. Calcula ERP target e non-target.
    8. Gera gráficos por canal e média global.
    9. Guarda um resumo em CSV.

Uso:
    python analyze_p300_erp.py p300_full_output_lsl_20260520_122211.csv

Ou com parâmetros:
    python analyze_p300_erp.py ficheiro.csv --fs 250 --baseline-ms 200 --epoch-ms 1000 --target-code 70
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


EEG_CHANNELS = [f"Ch{i:02d}" for i in range(1, 9)]
EVENT_CODE_CH = "Ch09"
TRIGGER_CH = "Ch10"


def read_transposed_csv(csv_path: Path) -> pd.DataFrame:
    """
    Lê CSV transposto:
        linha 0 = Time
        linha 1 = Timestamp
        linhas seguintes = Ch01..Ch10

    Devolve DataFrame com:
        Time, Timestamp, Ch01..Ch10
    """
    raw = pd.read_csv(csv_path, header=None)

    names = raw.iloc[:, 0].astype(str).tolist()
    values = raw.iloc[:, 1:]

    data = {}
    for row_name, row_values in zip(names, values.to_numpy()):
        data[row_name] = pd.to_numeric(pd.Series(row_values), errors="coerce").to_numpy()

    df = pd.DataFrame(data)

    required = ["Time", "Timestamp"] + EEG_CHANNELS + [EVENT_CODE_CH, TRIGGER_CH]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltam colunas/linhas no CSV: {missing}")

    return df


def detect_events(
    df: pd.DataFrame,
    target_code: float = 70.0,
    min_code: float = 1.0,
    max_code: float = 9.0,
) -> pd.DataFrame:
    """
    Deteta eventos em Ch09.

    Assume que, após a correção de alinhamento, os eventos são pontuais:
        Ch09 != 0 numa única amostra.

    Também funciona se houver pequenos segmentos, porque deteta transições 0 -> não-zero.
    """
    code = df[EVENT_CODE_CH].to_numpy(dtype=float)
    trigger = df[TRIGGER_CH].to_numpy(dtype=float)
    time_s = df["Time"].to_numpy(dtype=float)
    timestamp = df["Timestamp"].to_numpy(dtype=float)

    prev_code = np.r_[0.0, code[:-1]]

    # Evento quando Ch09 fica não-zero.
    onset_mask = (code != 0) & (prev_code == 0)

    # Se os eventos forem pontuais, isto é equivalente a code != 0.
    event_indices = np.where(onset_mask)[0]

    rows = []
    for idx in event_indices:
        c = float(code[idx])
        t = float(trigger[idx])

        if c == target_code:
            event_type = "target"
        elif min_code <= c <= max_code:
            event_type = "non_target"
        else:
            event_type = "other"

        rows.append(
            {
                "sample_index": int(idx),
                "time_s": float(time_s[idx]),
                "timestamp": float(timestamp[idx]),
                "code": c,
                "trigger": t,
                "event_type": event_type,
            }
        )

    return pd.DataFrame(rows)


def extract_epochs(
    df: pd.DataFrame,
    events: pd.DataFrame,
    fs: int = 250,
    pre_ms: int = 200,
    epoch_ms: int = 1000,
    baseline_ms: int = 200,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """
    Extrai epochs EEG.

    Epoch:
        começa pre_ms antes do evento
        termina epoch_ms depois do evento

    Exemplo:
        pre_ms = 200
        epoch_ms = 1000
        janela = -200 ms até +1000 ms

    Baseline:
        média entre -baseline_ms e 0 ms subtraída a cada canal
    """
    eeg = df[EEG_CHANNELS].to_numpy(dtype=float)

    pre_samples = int(round(pre_ms / 1000 * fs))
    post_samples = int(round(epoch_ms / 1000 * fs))
    n_epoch_samples = pre_samples + post_samples + 1

    baseline_samples = int(round(baseline_ms / 1000 * fs))

    times_ms = (np.arange(n_epoch_samples) - pre_samples) / fs * 1000

    epochs = []
    meta_rows = []

    for _, ev in events.iterrows():
        idx = int(ev["sample_index"])
        start = idx - pre_samples
        end = idx + post_samples

        if start < 0 or end >= len(df):
            continue

        ep = eeg[start:end + 1, :].copy()

        # baseline: últimos baseline_samples antes do evento.
        baseline_start = pre_samples - baseline_samples
        baseline_end = pre_samples

        if baseline_start < 0:
            baseline_start = 0

        baseline = ep[baseline_start:baseline_end, :].mean(axis=0)
        ep = ep - baseline

        epochs.append(ep)

        row = ev.to_dict()
        row["epoch_start_sample"] = int(start)
        row["epoch_end_sample"] = int(end)
        meta_rows.append(row)

    if not epochs:
        raise ValueError("Não foi possível extrair epochs válidos. Verifica eventos e duração do CSV.")

    return np.stack(epochs, axis=0), times_ms, pd.DataFrame(meta_rows)


def summarize_events(events: pd.DataFrame, epochs_meta: pd.DataFrame) -> pd.DataFrame:
    counts = []

    for label, data in [
        ("events_detected", events),
        ("epochs_valid", epochs_meta),
    ]:
        counts.append(
            {
                "metric": label,
                "total": len(data),
                "targets": int((data["event_type"] == "target").sum()) if len(data) else 0,
                "non_targets": int((data["event_type"] == "non_target").sum()) if len(data) else 0,
                "other": int((data["event_type"] == "other").sum()) if len(data) else 0,
            }
        )

    return pd.DataFrame(counts)


def compute_peak_table(
    epochs: np.ndarray,
    epochs_meta: pd.DataFrame,
    times_ms: np.ndarray,
    window_start_ms: int = 250,
    window_end_ms: int = 700,
) -> pd.DataFrame:
    """
    Calcula pico positivo target - non-target por canal numa janela temporal.
    """
    target_mask = epochs_meta["event_type"].to_numpy() == "target"
    non_target_mask = epochs_meta["event_type"].to_numpy() == "non_target"

    target_epochs = epochs[target_mask]
    non_target_epochs = epochs[non_target_mask]

    if len(target_epochs) == 0 or len(non_target_epochs) == 0:
        raise ValueError("É necessário ter epochs target e non-target.")

    target_erp = target_epochs.mean(axis=0)
    non_target_erp = non_target_epochs.mean(axis=0)
    diff_erp = target_erp - non_target_erp

    w = (times_ms >= window_start_ms) & (times_ms <= window_end_ms)

    rows = []

    for ch_idx, ch_name in enumerate(EEG_CHANNELS):
        y = diff_erp[w, ch_idx]
        t = times_ms[w]
        peak_idx = int(np.argmax(y))

        rows.append(
            {
                "channel": ch_name,
                "positive_peak_ms": float(t[peak_idx]),
                "positive_peak_uV": float(y[peak_idx]),
            }
        )

    # média global
    y_global = diff_erp[:, :].mean(axis=1)
    y_w = y_global[w]
    t_w = times_ms[w]
    peak_idx = int(np.argmax(y_w))

    rows.append(
        {
            "channel": "GlobalMean_Ch01_Ch08",
            "positive_peak_ms": float(t_w[peak_idx]),
            "positive_peak_uV": float(y_w[peak_idx]),
        }
    )

    return pd.DataFrame(rows)


def plot_erp_channel(
    times_ms: np.ndarray,
    target_erp: np.ndarray,
    non_target_erp: np.ndarray,
    ch_idx: int,
    out_path: Path,
):
    ch_name = EEG_CHANNELS[ch_idx]

    plt.figure(figsize=(10, 5))
    plt.plot(times_ms, target_erp[:, ch_idx], label="Target")
    plt.plot(times_ms, non_target_erp[:, ch_idx], label="Non-target")
    plt.axvline(0, linestyle="--", linewidth=1)
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xlabel("Tempo após estímulo (ms)")
    plt.ylabel("Amplitude EEG baseline-corrected")
    plt.title(f"ERP P300 - {ch_name}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_global_erp(
    times_ms: np.ndarray,
    target_erp: np.ndarray,
    non_target_erp: np.ndarray,
    out_path: Path,
):
    target_global = target_erp.mean(axis=1)
    non_target_global = non_target_erp.mean(axis=1)
    diff_global = target_global - non_target_global

    plt.figure(figsize=(10, 5))
    plt.plot(times_ms, target_global, label="Target - média Ch01..Ch08")
    plt.plot(times_ms, non_target_global, label="Non-target - média Ch01..Ch08")
    plt.plot(times_ms, diff_global, label="Diferença Target - Non-target")
    plt.axvline(0, linestyle="--", linewidth=1)
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xlabel("Tempo após estímulo (ms)")
    plt.ylabel("Amplitude EEG baseline-corrected")
    plt.title("ERP P300 - Média global")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_event_intervals(events: pd.DataFrame, out_path: Path):
    if len(events) < 2:
        return

    intervals_ms = np.diff(events["time_s"].to_numpy(dtype=float)) * 1000

    plt.figure(figsize=(10, 5))
    plt.plot(np.arange(1, len(intervals_ms) + 1), intervals_ms)
    plt.axhline(300, linestyle="--", linewidth=1, label="Referência ~300 ms")
    plt.xlabel("Intervalo entre eventos")
    plt.ylabel("Intervalo ON-ON (ms)")
    plt.title("Intervalos entre onsets de eventos")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Análise ERP P300 para CSV transposto BCI4ALL.")
    parser.add_argument("csv_file", type=str, help="Caminho para o CSV transposto.")
    parser.add_argument("--fs", type=int, default=250, help="Frequência de amostragem em Hz.")
    parser.add_argument("--pre-ms", type=int, default=200, help="Tempo antes do evento em ms.")
    parser.add_argument("--epoch-ms", type=int, default=1000, help="Tempo depois do evento em ms.")
    parser.add_argument("--baseline-ms", type=int, default=200, help="Janela de baseline antes do evento em ms.")
    parser.add_argument("--target-code", type=float, default=70.0, help="Código usado para eventos target em Ch09.")
    parser.add_argument("--peak-start-ms", type=int, default=250, help="Início da janela para procurar pico.")
    parser.add_argument("--peak-end-ms", type=int, default=700, help="Fim da janela para procurar pico.")
    parser.add_argument("--out-dir", type=str, default="", help="Pasta de saída. Por defeito cria pasta ao lado do CSV.")

    args = parser.parse_args()

    csv_path = Path(args.csv_file).resolve()
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        out_dir = csv_path.parent / f"{csv_path.stem}_erp_analysis"

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] A ler CSV: {csv_path}")
    df = read_transposed_csv(csv_path)

    print(f"[INFO] Amostras: {len(df)}")
    print(f"[INFO] Duração aproximada: {df['Time'].iloc[-1] - df['Time'].iloc[0]:.2f} s")

    events = detect_events(df, target_code=args.target_code)
    events.to_csv(out_dir / "events_detected.csv", index=False)

    print(f"[INFO] Eventos detetados: {len(events)}")
    print(events["event_type"].value_counts(dropna=False).to_string())

    epochs, times_ms, epochs_meta = extract_epochs(
        df,
        events,
        fs=args.fs,
        pre_ms=args.pre_ms,
        epoch_ms=args.epoch_ms,
        baseline_ms=args.baseline_ms,
    )

    epochs_meta.to_csv(out_dir / "epochs_valid.csv", index=False)

    summary = summarize_events(events, epochs_meta)
    summary.to_csv(out_dir / "summary_counts.csv", index=False)

    target_mask = epochs_meta["event_type"].to_numpy() == "target"
    non_target_mask = epochs_meta["event_type"].to_numpy() == "non_target"

    target_erp = epochs[target_mask].mean(axis=0)
    non_target_erp = epochs[non_target_mask].mean(axis=0)

    peak_table = compute_peak_table(
        epochs,
        epochs_meta,
        times_ms,
        window_start_ms=args.peak_start_ms,
        window_end_ms=args.peak_end_ms,
    )
    peak_table.to_csv(out_dir / "p300_peak_table.csv", index=False)

    print("\n[RESUMO]")
    print(summary.to_string(index=False))

    print("\n[PICOS POSITIVOS TARGET - NON-TARGET]")
    print(peak_table.to_string(index=False))

    # Guardar ERPs médios em CSV para análise posterior.
    erp_out = pd.DataFrame({"time_ms": times_ms})
    for ch_idx, ch_name in enumerate(EEG_CHANNELS):
        erp_out[f"{ch_name}_target"] = target_erp[:, ch_idx]
        erp_out[f"{ch_name}_non_target"] = non_target_erp[:, ch_idx]
        erp_out[f"{ch_name}_diff"] = target_erp[:, ch_idx] - non_target_erp[:, ch_idx]
    erp_out.to_csv(out_dir / "erp_waveforms.csv", index=False)

    # Plots.
    for ch_idx, ch_name in enumerate(EEG_CHANNELS):
        plot_erp_channel(
            times_ms,
            target_erp,
            non_target_erp,
            ch_idx,
            out_dir / f"erp_{ch_name}.png",
        )

    plot_global_erp(
        times_ms,
        target_erp,
        non_target_erp,
        out_dir / "erp_global_mean.png",
    )

    plot_event_intervals(events, out_dir / "event_intervals.png")

    print(f"\n[OK] Análise concluída. Resultados guardados em:")
    print(out_dir)


if __name__ == "__main__":
    main()
