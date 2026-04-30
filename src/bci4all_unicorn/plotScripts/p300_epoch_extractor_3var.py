"""
Script de extração de epochs P300 a partir do CSV gerado pelo pipeline.

Estrutura esperada do CSV (formato transposto):
    Linha 0 : Time        → rótulo/tempo relativo
    Linha 1 : Timestamp   → timestamps por amostra
    Linha 2 : Ch01        → canal EEG 1
    ...
    Linha 9 : Ch08        → canal EEG 8
    Linha 10: Ch09        → canal de eventos

Lógica de classificação dos eventos (canal Ch09):
    - targets     : onsets em que Ch09 == 70
    - non_targets : onsets em que Ch09 != 0 e Ch09 != 70

Extração de epochs:
    - A cada onset de evento (transição de 0 para valor != 0 no canal Ch09),
      extraem-se 250 amostras (1 segundo a 250 Hz) começando no momento exato do onset.
    - Os 8 canais EEG são extraídos para cada epoch.

Variáveis resultantes:
    shape → (n_canais=8, n_amostras=250, n_repetições)

Outputs:
    - Ficheiro .npz com arrays geral, targets, non_targets
    - Plots simples (sem desvio padrão) para targets e non_targets
    - Plots com média ± desvio padrão para targets e non_targets
"""

# =============================================================
# IMPORTS
# =============================================================

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import argparse


# =============================================================
# PARÂMETROS CONFIGURÁVEIS
# =============================================================

DEFAULT_CSV          = "p300_full_output_lsl_20260423_161538.csv"
DEFAULT_SRATE     = 250
DEFAULT_EPOCH_MS  = 1000
TARGET_CODE       = 70

N_EEG_CHANNELS      = 8
EVENT_CHANNEL_LABEL = "Ch09"
EEG_CHANNEL_LABELS  = [f"Ch{i:02d}" for i in range(1, N_EEG_CHANNELS + 1)]


# =============================================================
# FUNÇÃO: load_csv
# =============================================================

def load_csv(csv_path: str) -> pd.DataFrame:
    """
    Lê o CSV gerado pelo pipeline e transpõe-o para formato (amostras × canais).
    """
    raw = pd.read_csv(csv_path, header=0, index_col=0)
    df = raw.T.copy()

    if "Time" in df.columns:
        df = df.drop(columns=["Time"])

    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna().reset_index(drop=True)

    print(f"[INFO] CSV carregado: {df.shape[0]} amostras × {df.shape[1]} canais")
    return df


# =============================================================
# FUNÇÃO: detect_onsets
# =============================================================

def detect_onsets(event_channel: pd.Series) -> pd.Index:
    """
    Deteta onsets como transições 0 -> valor != 0.
    """
    prev = event_channel.shift(1, fill_value=0)
    onset_mask = (event_channel != 0) & (prev == 0)
    return event_channel[onset_mask].index


# =============================================================
# FUNÇÃO: extract_epochs
# =============================================================

def extract_epochs(
    df: pd.DataFrame,
    onsets: pd.Index,
    epoch_samples: int,
    eeg_labels: list,
) -> np.ndarray:
    """
    Extrai epochs 3D com shape (n_canais, n_amostras, n_repetições).
    """
    n_canais = len(eeg_labels)
    epochs_list = []

    for onset_idx in onsets:
        inicio = int(onset_idx)
        fim = inicio + epoch_samples

        if fim > len(df):
            print(f"[WARN] Onset em {inicio} ignorado: epoch ultrapassa o fim do sinal.")
            continue

        epoch_data = df.iloc[inicio:fim][eeg_labels].values
        epoch_data = epoch_data.T
        epochs_list.append(epoch_data)

    if len(epochs_list) == 0:
        print("[WARN] Nenhum epoch extraído para este conjunto de onsets.")
        return np.empty((n_canais, epoch_samples, 0))

    epochs_array = np.stack(epochs_list, axis=2)
    print(f"[INFO] Epochs extraídos: {epochs_array.shape[2]} | shape: {epochs_array.shape}")
    return epochs_array


# =============================================================
# FUNÇÃO: plot simples (sem desvio padrão)
# =============================================================

def plot_erp_condition_simple(
    epochs: np.ndarray,
    srate: int,
    eeg_labels: list,
    condition_name: str = "ERP",
    output_path: str = None,
):
    """
    Cria subplots com apenas a média dos epochs por canal, sem desvio padrão.
    """
    n_canais = len(eeg_labels)

    if epochs.shape[2] == 0:
        print(f"[WARN] Sem epochs para plotar na condição: {condition_name}")
        return

    n_amostras = epochs.shape[1]
    time_ms = np.arange(n_amostras) / srate * 1000

    fig, axes = plt.subplots(
        nrows=n_canais,
        ncols=1,
        figsize=(12, 2.5 * n_canais),
        sharex=True,
    )

    if n_canais == 1:
        axes = [axes]

    for ch_idx, (ax, label) in enumerate(zip(axes, eeg_labels)):
        ch_data = epochs[ch_idx, :, :]
        ch_mean = ch_data.mean(axis=1)

        ax.plot(
            time_ms,
            ch_mean,
            linewidth=1.5,
            label=f"{condition_name} (n={epochs.shape[2]})"
        )

        ax.axvline(x=0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5, alpha=0.4)

        ax.set_ylabel(f"{label}\n(µV)", fontsize=8)
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Tempo (ms)", fontsize=9)

    fig.suptitle(
        f"{condition_name} — Média por Canal (sem desvio padrão)\n"
        f"Epochs: {epochs.shape[2]}",
        fontsize=11,
        fontweight="bold",
    )

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"[INFO] Figura guardada em: {output_path}")
        plt.close(fig)
    else:
        plt.show()


# =============================================================
# FUNÇÃO: plot com desvio padrão
# =============================================================

def plot_erp_condition_std(
    epochs: np.ndarray,
    srate: int,
    eeg_labels: list,
    condition_name: str = "ERP",
    output_path: str = None,
):
    """
    Cria subplots com média ± desvio padrão para uma única condição.
    """
    n_canais = len(eeg_labels)

    if epochs.shape[2] == 0:
        print(f"[WARN] Sem epochs para plotar na condição: {condition_name}")
        return

    n_amostras = epochs.shape[1]
    time_ms = np.arange(n_amostras) / srate * 1000

    fig, axes = plt.subplots(
        nrows=n_canais,
        ncols=1,
        figsize=(12, 2.5 * n_canais),
        sharex=True,
    )

    if n_canais == 1:
        axes = [axes]

    for ch_idx, (ax, label) in enumerate(zip(axes, eeg_labels)):
        ch_data = epochs[ch_idx, :, :]
        ch_mean = ch_data.mean(axis=1)
        ch_std = ch_data.std(axis=1)

        ax.plot(
            time_ms,
            ch_mean,
            linewidth=1.5,
            label=f"{condition_name} (n={epochs.shape[2]})"
        )

        ax.fill_between(
            time_ms,
            ch_mean - ch_std,
            ch_mean + ch_std,
            alpha=0.2
        )

        ax.axvline(x=0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5, alpha=0.4)

        ax.set_ylabel(f"{label}\n(µV)", fontsize=8)
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Tempo (ms)", fontsize=9)

    fig.suptitle(
        f"{condition_name} — Média ± Desvio Padrão por Canal\n"
        f"Epochs: {epochs.shape[2]}",
        fontsize=11,
        fontweight="bold",
    )

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"[INFO] Figura guardada em: {output_path}")
        plt.close(fig)
    else:
        plt.show()


# =============================================================
# FUNÇÃO PRINCIPAL
# =============================================================

def extract_p300_epochs(
    csv_path: str,
    srate: int       = DEFAULT_SRATE,
    epoch_ms: int    = DEFAULT_EPOCH_MS,
    save_npz: bool   = True,
    show_plot: bool  = True,
    output_dir: str  = None,
):
    """
    Pipeline completo de extração de epochs P300.

    Regra:
        - target     = onsets em que Ch09 == 70
        - non_target = onsets em que Ch09 != 0 e Ch09 != 70
    """
    # -------------------------------------------------------
    # PASSO 1 — Carregar CSV
    # -------------------------------------------------------
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"Ficheiro CSV não encontrado: {csv_path}")

    df = load_csv(str(csv_path))

    if EVENT_CHANNEL_LABEL not in df.columns:
        raise ValueError(
            f"Canal de eventos '{EVENT_CHANNEL_LABEL}' não encontrado no CSV.\n"
            f"Colunas disponíveis: {list(df.columns)}"
        )

    missing = [c for c in EEG_CHANNEL_LABELS if c not in df.columns]
    if missing:
        raise ValueError(f"Canais EEG em falta no CSV: {missing}")

    # -------------------------------------------------------
    # PASSO 2 — Canal de eventos
    # -------------------------------------------------------
    event_ch = df[EVENT_CHANNEL_LABEL].round().astype(int)

    epoch_samples = int(epoch_ms / 1000 * srate)
    print(f"[INFO] Epoch: {epoch_ms} ms = {epoch_samples} amostras @ {srate} Hz")
    print(f"[INFO] Código target: {TARGET_CODE}")

    # -------------------------------------------------------
    # PASSO 3 — Detetar onsets
    # -------------------------------------------------------
    all_onsets = detect_onsets(event_ch)
    print(f"[INFO] Total de onsets detectados: {len(all_onsets)}")

    onset_codes = event_ch.loc[all_onsets]

    target_onsets = onset_codes[onset_codes == TARGET_CODE].index
    print(f"[INFO] Target onsets (code == {TARGET_CODE}): {len(target_onsets)}")

    non_target_onsets = onset_codes[(onset_codes != 0) & (onset_codes != TARGET_CODE)].index
    print(f"[INFO] Non-target onsets (code != 0 e != {TARGET_CODE}): {len(non_target_onsets)}")

    # -------------------------------------------------------
    # PASSO 4 — Extrair epochs
    # -------------------------------------------------------
    print("\n[INFO] A extrair epochs targets...")
    targets = extract_epochs(df, target_onsets, epoch_samples, EEG_CHANNEL_LABELS)

    print("[INFO] A extrair epochs non_targets...")
    non_targets = extract_epochs(df, non_target_onsets, epoch_samples, EEG_CHANNEL_LABELS)

    if targets.shape[2] > 0 and non_targets.shape[2] > 0:
        geral = np.concatenate([targets, non_targets], axis=2)
    elif targets.shape[2] > 0:
        geral = targets.copy()
    elif non_targets.shape[2] > 0:
        geral = non_targets.copy()
    else:
        geral = np.empty((N_EEG_CHANNELS, epoch_samples, 0))

    print(f"\n[RESUMO] geral:       shape = {geral.shape}")
    print(f"[RESUMO] targets:     shape = {targets.shape}")
    print(f"[RESUMO] non_targets: shape = {non_targets.shape}")

    # -------------------------------------------------------
    # PASSO 5 — Pasta de saída
    # -------------------------------------------------------
    if output_dir is None:
        output_dir = csv_path.parent
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------
    # PASSO 6 — Guardar .npz
    # -------------------------------------------------------
    if save_npz:
        npz_path = output_dir / (csv_path.stem + "_epochs.npz")

        np.savez(
            str(npz_path),
            geral=geral,
            targets=targets,
            non_targets=non_targets,
        )
        print(f"\n[INFO] Arrays guardadas em: {npz_path}")
        print(f"       Carregar com: data = np.load('{npz_path}')")
        print(f"       Aceder com:   data['targets'], data['non_targets'], data['geral']")

    # -------------------------------------------------------
    # PASSO 7 — Gerar plots
    # -------------------------------------------------------
    if show_plot:
        # Plots simples
        target_plot_path = str(output_dir / (csv_path.stem + "_targets_mean.png"))
        nontarget_plot_path = str(output_dir / (csv_path.stem + "_nontargets_mean.png"))

        print("\n[INFO] A gerar plot simples dos targets...")
        plot_erp_condition_simple(
            epochs=targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            condition_name="Targets",
            output_path=target_plot_path,
        )

        print("[INFO] A gerar plot simples dos non-targets...")
        plot_erp_condition_simple(
            epochs=non_targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            condition_name="Non-targets",
            output_path=nontarget_plot_path,
        )

        # Plots com desvio padrão
        target_std_plot_path = str(output_dir / (csv_path.stem + "_targets_std.png"))
        nontarget_std_plot_path = str(output_dir / (csv_path.stem + "_nontargets_std.png"))

        print("[INFO] A gerar plot com desvio padrão dos targets...")
        plot_erp_condition_std(
            epochs=targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            condition_name="Targets",
            output_path=target_std_plot_path,
        )

        print("[INFO] A gerar plot com desvio padrão dos non-targets...")
        plot_erp_condition_std(
            epochs=non_targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            condition_name="Non-targets",
            output_path=nontarget_std_plot_path,
        )

    return {
        "geral": geral,
        "targets": targets,
        "non_targets": non_targets,
    }


# =============================================================
# INTERFACE DE LINHA DE COMANDOS
# =============================================================

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Extração de epochs P300 a partir do CSV do pipeline BCI4ALL."
    )

    parser.add_argument(
        "--csv",
        type=str,
        default=DEFAULT_CSV,
        help=f"Caminho para o ficheiro CSV (default: {DEFAULT_CSV})",
    )

    parser.add_argument(
        "--srate",
        type=int,
        default=DEFAULT_SRATE,
        help=f"Taxa de amostragem em Hz. Default: {DEFAULT_SRATE}",
    )

    parser.add_argument(
        "--epoch_ms",
        type=int,
        default=DEFAULT_EPOCH_MS,
        help=f"Duração do epoch em ms. Default: {DEFAULT_EPOCH_MS}",
    )

    parser.add_argument(
        "--no_npz",
        action="store_true",
        help="Se indicado, não guarda o ficheiro .npz.",
    )

    parser.add_argument(
        "--no_plot",
        action="store_true",
        help="Se indicado, não gera os plots.",
    )

    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Pasta de saída para .npz e .png. Default: mesma pasta do CSV.",
    )

    return parser.parse_args()


# =============================================================
# PONTO DE ENTRADA
# =============================================================

if __name__ == "__main__":
    args = _parse_args()

    result = extract_p300_epochs(
        csv_path   = args.csv,
        srate      = args.srate,
        epoch_ms   = args.epoch_ms,
        save_npz   = not args.no_npz,
        show_plot  = not args.no_plot,
        output_dir = args.output_dir,
    )