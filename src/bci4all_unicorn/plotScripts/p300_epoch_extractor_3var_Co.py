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
    - Janela: -200 ms a +800 ms relativamente ao onset
    - A cada onset de evento (transição de 0 para valor != 0 no canal Ch09),
      extraem-se amostras EEG para os 8 canais.
    - É aplicada baseline correction usando a janela pré-estímulo.

Variáveis resultantes:
    shape → (n_canais=8, n_amostras_por_epoch, n_repetições)

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

DEFAULT_CSV          = "p300_full_output_lsl_20260423_174521.csv"
DEFAULT_SRATE     = 250

DEFAULT_PRE_MS    = 200
DEFAULT_POST_MS   = 800

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
# FUNÇÃO: extract_epochs_with_baseline
# =============================================================

def extract_epochs_with_baseline(
    df: pd.DataFrame,
    onsets: pd.Index,
    pre_samples: int,
    post_samples: int,
    eeg_labels: list,
) -> np.ndarray:
    """
    Extrai epochs 3D com shape (n_canais, n_amostras, n_repetições),
    usando uma janela com pré-estímulo e pós-estímulo.

    Aplica baseline correction usando a janela pré-estímulo:
        baseline = média dos samples antes do onset
        epoch_corrigido = epoch - baseline

    Parâmetros:
        df:           DataFrame completo (amostras × canais)
        onsets:       índices dos onsets
        pre_samples:  nº de amostras antes do onset
        post_samples: nº de amostras depois do onset
        eeg_labels:   lista de canais EEG

    Retorna:
        Array 3D de shape (n_canais, pre_samples + post_samples, n_repetições)
    """
    n_canais = len(eeg_labels)
    epoch_len = pre_samples + post_samples
    epochs_list = []

    for onset_idx in onsets:
        onset_idx = int(onset_idx)

        inicio = onset_idx - pre_samples
        fim = onset_idx + post_samples

        # Validar se a janela cabe dentro do sinal
        if inicio < 0:
            print(f"[WARN] Onset em {onset_idx} ignorado: não há amostras suficientes antes do onset.")
            continue

        if fim > len(df):
            print(f"[WARN] Onset em {onset_idx} ignorado: epoch ultrapassa o fim do sinal.")
            continue

        # Extrair epoch: shape (epoch_len, n_canais)
        epoch_data = df.iloc[inicio:fim][eeg_labels].values

        # Transpor para (n_canais, epoch_len)
        epoch_data = epoch_data.T

        # Baseline correction:
        # usa os primeiros pre_samples de cada canal
        baseline = epoch_data[:, :pre_samples].mean(axis=1, keepdims=True)
        epoch_data = epoch_data - baseline

        if epoch_data.shape[1] != epoch_len:
            print(f"[WARN] Epoch com shape inesperada em onset {onset_idx}: {epoch_data.shape}")
            continue

        epochs_list.append(epoch_data)

    if len(epochs_list) == 0:
        print("[WARN] Nenhum epoch extraído para este conjunto de onsets.")
        return np.empty((n_canais, epoch_len, 0))

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
    pre_samples: int,
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
    time_ms = (np.arange(n_amostras) - pre_samples) / srate * 1000

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
    pre_samples: int,
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
    time_ms = (np.arange(n_amostras) - pre_samples) / srate * 1000

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
    pre_ms: int      = DEFAULT_PRE_MS,
    post_ms: int     = DEFAULT_POST_MS,
    save_npz: bool   = True,
    show_plot: bool  = True,
    output_dir: str  = None,
):
    """
    Pipeline completo de extração de epochs P300.

    Regra:
        - target     = onsets em que Ch09 == 70
        - non_target = onsets em que Ch09 != 0 e Ch09 != 70

    Epoch:
        - janela: [-pre_ms, +post_ms[
        - baseline correction usando a janela pré-estímulo
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

    pre_samples = int(pre_ms / 1000 * srate)
    post_samples = int(post_ms / 1000 * srate)
    epoch_len = pre_samples + post_samples

    print(f"[INFO] Janela epoch: -{pre_ms} ms a +{post_ms} ms")
    print(f"[INFO] pre_samples = {pre_samples} | post_samples = {post_samples} | total = {epoch_len}")
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
    # PASSO 4 — Extrair epochs com baseline correction
    # -------------------------------------------------------
    print("\n[INFO] A extrair epochs targets...")
    targets = extract_epochs_with_baseline(
        df=df,
        onsets=target_onsets,
        pre_samples=pre_samples,
        post_samples=post_samples,
        eeg_labels=EEG_CHANNEL_LABELS,
    )

    print("[INFO] A extrair epochs non_targets...")
    non_targets = extract_epochs_with_baseline(
        df=df,
        onsets=non_target_onsets,
        pre_samples=pre_samples,
        post_samples=post_samples,
        eeg_labels=EEG_CHANNEL_LABELS,
    )

    if targets.shape[2] > 0 and non_targets.shape[2] > 0:
        geral = np.concatenate([targets, non_targets], axis=2)
    elif targets.shape[2] > 0:
        geral = targets.copy()
    elif non_targets.shape[2] > 0:
        geral = non_targets.copy()
    else:
        geral = np.empty((N_EEG_CHANNELS, epoch_len, 0))

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
        npz_path = output_dir / (csv_path.stem + "_epochs_baseline.npz")

        np.savez(
            str(npz_path),
            geral=geral,
            targets=targets,
            non_targets=non_targets,
            srate=srate,
            pre_ms=pre_ms,
            post_ms=post_ms,
            pre_samples=pre_samples,
            post_samples=post_samples,
            target_code=TARGET_CODE,
            eeg_labels=np.array(EEG_CHANNEL_LABELS, dtype=object),
        )
        print(f"\n[INFO] Arrays guardadas em: {npz_path}")
        print(f"       Carregar com: data = np.load('{npz_path}', allow_pickle=True)")
        print(f"       Aceder com:   data['targets'], data['non_targets'], data['geral']")

    # -------------------------------------------------------
    # PASSO 7 — Gerar plots
    # -------------------------------------------------------
    if show_plot:
        # Plots simples
        target_plot_path = str(output_dir / (csv_path.stem + "_targets_mean_baseline.png"))
        nontarget_plot_path = str(output_dir / (csv_path.stem + "_nontargets_mean_baseline.png"))

        print("\n[INFO] A gerar plot simples dos targets...")
        plot_erp_condition_simple(
            epochs=targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            pre_samples=pre_samples,
            condition_name="Targets",
            output_path=target_plot_path,
        )

        print("[INFO] A gerar plot simples dos non-targets...")
        plot_erp_condition_simple(
            epochs=non_targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            pre_samples=pre_samples,
            condition_name="Non-targets",
            output_path=nontarget_plot_path,
        )

        # Plots com desvio padrão
        target_std_plot_path = str(output_dir / (csv_path.stem + "_targets_std_baseline.png"))
        nontarget_std_plot_path = str(output_dir / (csv_path.stem + "_nontargets_std_baseline.png"))

        print("[INFO] A gerar plot com desvio padrão dos targets...")
        plot_erp_condition_std(
            epochs=targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            pre_samples=pre_samples,
            condition_name="Targets",
            output_path=target_std_plot_path,
        )

        print("[INFO] A gerar plot com desvio padrão dos non-targets...")
        plot_erp_condition_std(
            epochs=non_targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            pre_samples=pre_samples,
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
        "--pre_ms",
        type=int,
        default=DEFAULT_PRE_MS,
        help=f"Janela antes do onset, em ms. Default: {DEFAULT_PRE_MS}",
    )

    parser.add_argument(
        "--post_ms",
        type=int,
        default=DEFAULT_POST_MS,
        help=f"Janela depois do onset, em ms. Default: {DEFAULT_POST_MS}",
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
        pre_ms     = args.pre_ms,
        post_ms    = args.post_ms,
        save_npz   = not args.no_npz,
        show_plot  = not args.no_plot,
        output_dir = args.output_dir,
    )