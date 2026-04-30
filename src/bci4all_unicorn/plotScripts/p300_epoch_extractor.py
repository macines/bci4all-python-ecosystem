"""
Script de extração de epochs P300 a partir do CSV gerado pelo pipeline.

Estrutura do CSV (formato transposto):
    Linha 0 : Time        → rótulo das colunas (t1, t2, ...)
    Linha 1 : Timestamp   → timestamps LSL de cada amostra
    Linha 2 : Ch01        → canal EEG 1
    ...
    Linha 9 : Ch08        → canal EEG 8
    Linha 10: Ch09        → canal de eventos (code da célula em flash)
    Linha 11: Ch10        → canal de targets  (não usado neste script)

Lógica de classificação dos eventos (canal Ch09):
    - non_targets : amostras onde Ch09 tem um valor DENTRO do intervalo da interface
                    (ex: 1 a 9 para a grelha 3x3). São os flashes de distractores.
    - targets     : amostras onde Ch09 tem um valor FORA do intervalo da interface
                    (ex: 70, 100, etc.). São os flashes do target real.

Extração de epochs:
    - A cada onset de evento (transição de 0 para valor != 0 no canal de eventos),
      extraem-se 250 amostras (1 segundo a 250 Hz) começando no momento exato do onset.
    - Os 8 canais EEG são extraídos para cada epoch.

Variável 3D resultante:
    shape → (n_canais=8, n_amostras=250, n_repetições)

Outputs:
    - Ficheiro .npz com as arrays geral, targets, non_targets
    - Subplots com média ± desvio padrão por condição para validação visual
"""

# =============================================================
# IMPORTS
# =============================================================

import numpy as np
# numpy: biblioteca de computação numérica.
# Usada para criar e manipular arrays multidimensionais (epochs 3D),
# calcular médias, desvios padrão e guardar os dados em .npz.

import pandas as pd
# pandas: biblioteca de análise de dados tabulares.
# Usada para ler e transpor o CSV, e para localizar os onsets de eventos.

import matplotlib.pyplot as plt
# matplotlib: biblioteca de visualização.
# Usada para criar os subplots de média ± desvio padrão por condição.

from pathlib import Path
# Path: manipulação de caminhos de ficheiros independente do SO.
# Usada para construir os paths dos ficheiros de entrada e saída.

import argparse
# argparse: parsing de argumentos da linha de comandos.
# Permite passar o ficheiro CSV e os parâmetros da interface como argumentos
# sem alterar o código fonte — tornando o script reutilizável para outras interfaces.


# =============================================================
# PARÂMETROS CONFIGURÁVEIS (defaults)
# Podem ser substituídos via argumentos da linha de comandos.
# =============================================================

DEFAULT_CSV          = "p300_full_output_lsl_20260423_161538.csv"
# DEFAULT_CSV: caminho padrão para o ficheiro CSV de entrada.
# Usado se não for passado nenhum argumento --csv na linha de comandos.

DEFAULT_SRATE        = 250
# DEFAULT_SRATE: taxa de amostragem em Hz.
# Define quantas amostras correspondem a 1 segundo de sinal (epoch de 1s = 250 amostras).

DEFAULT_EPOCH_MS     = 1000
# DEFAULT_EPOCH_MS: duração de cada epoch em milissegundos.
# Com 250 Hz, 1000 ms = 250 amostras por epoch.

DEFAULT_IFACE_MIN    = 1
# DEFAULT_IFACE_MIN: valor mínimo do intervalo de códigos da interface.
# Eventos com code >= DEFAULT_IFACE_MIN e <= DEFAULT_IFACE_MAX são non_targets.

DEFAULT_IFACE_MAX    = 9
# DEFAULT_IFACE_MAX: valor máximo do intervalo de códigos da interface.
# Para a grelha 3x3 este valor é 9. Para outras interfaces pode ser diferente.

N_EEG_CHANNELS       = 8
# N_EEG_CHANNELS: número de canais EEG a extrair.
# Corresponde às linhas Ch01 a Ch08 do CSV transposto.

EVENT_CHANNEL_LABEL  = "Ch09"
# EVENT_CHANNEL_LABEL: nome da linha do CSV que contém os códigos de eventos.
# Ch09 no CSV transposto = canal de eventos (code da célula em flash, 0 quando off).

EEG_CHANNEL_LABELS   = [f"Ch{i:02d}" for i in range(1, N_EEG_CHANNELS + 1)]
# EEG_CHANNEL_LABELS: lista ["Ch01", "Ch02", ..., "Ch08"].
# Usada para selecionar as linhas de EEG do CSV transposto de forma programática.


# =============================================================
# FUNÇÃO: load_csv
# Lê e transpõe o CSV, devolvendo um DataFrame orientado por amostras.
# =============================================================

def load_csv(csv_path: str) -> pd.DataFrame:
    """
    Lê o CSV gerado pelo pipeline e transpõe-o para formato (amostras × canais).

    O CSV está no formato transposto:
        - cada LINHA é um canal (Time, Timestamp, Ch01..Ch10)
        - cada COLUNA é uma amostra no tempo

    Após a transposição:
        - cada LINHA é uma amostra no tempo
        - cada COLUNA é um canal

    Parâmetro:
        csv_path: caminho para o ficheiro CSV.

    Retorna:
        DataFrame com colunas [Timestamp, Ch01, Ch02, ..., Ch09, Ch10]
        e uma linha por amostra de EEG.
    """
    # Lê o CSV como está (sem assumir header) — cada linha é um canal.
    # index_col=0: usa a primeira coluna (rótulos dos canais) como índice das linhas.
    raw = pd.read_csv(csv_path, header=0, index_col=0)
    # raw.shape = (n_canais+2, n_amostras)
    # índice das linhas: ["Time", "Timestamp", "Ch01", ..., "Ch10"]
    # colunas: "t1", "t2", ..., "tN" (rótulos das amostras)

    # Transpõe para (n_amostras, n_canais+2).
    # Após transposição, as colunas são os nomes dos canais.
    df = raw.T.copy()
    # df.shape = (n_amostras, n_linhas_originais)
    # colunas: ["Time", "Timestamp", "Ch01", ..., "Ch10"]

    # Remove a coluna "Time" — é apenas o rótulo textual das colunas originais.
    if "Time" in df.columns:
        df = df.drop(columns=["Time"])

    # Converte todas as colunas para numérico.
    # errors="coerce": substitui valores não numéricos por NaN em vez de lançar erro.
    df = df.apply(pd.to_numeric, errors="coerce")

    # Remove linhas com NaN (amostras inválidas ou truncadas no início/fim do CSV).
    df = df.dropna().reset_index(drop=True)

    print(f"[INFO] CSV carregado: {df.shape[0]} amostras × {df.shape[1]} canais")
    return df


# =============================================================
# FUNÇÃO: detect_onsets
# Detecta os instantes de inicio (onset) de cada evento no canal de eventos.
# =============================================================

def detect_onsets(event_channel: pd.Series) -> pd.Series:
    """
    Detecta os índices de onset de cada evento no canal de eventos (Ch09).

    Um onset é definido como uma transição de 0 (sem estímulo) para
    um valor != 0 (célula em flash), ou seja, o primeiro sample do flash.

    Parâmetro:
        event_channel: Series com os valores do canal Ch09 ao longo do tempo.

    Retorna:
        Series com os índices (posições no DataFrame) dos onsets.
    """
    # prev: Series com os valores deslocados 1 amostra para a frente.
    # prev[i] = event_channel[i-1], o valor da amostra anterior.
    # fill_value=0: a amostra "antes" da primeira é tratada como 0 (sem estímulo).
    prev = event_channel.shift(1, fill_value=0)

    # Um onset ocorre quando:
    # - o valor atual é != 0 (há um estímulo ativo agora)
    # - o valor anterior era == 0 (não havia estímulo antes)
    # Isto detecta a borda de subida do pulso de evento.
    onset_mask = (event_channel != 0) & (prev == 0)

    # Devolve os índices das amostras onde onset_mask é True.
    return event_channel[onset_mask].index


# =============================================================
# FUNÇÃO: extract_epochs
# Extrai epochs de EEG a partir de uma lista de onsets.
# =============================================================

def extract_epochs(
    df: pd.DataFrame,
    onsets: pd.Index,
    epoch_samples: int,
    eeg_labels: list,
) -> np.ndarray:
    """
    Extrai epochs de EEG de 3 dimensões: [canais, amostras, repetições].

    Para cada onset, extrai epoch_samples amostras a partir do momento exato
    do onset (inclusive). Epochs que ultrapassem o fim do sinal são ignorados.

    Parâmetros:
        df:            DataFrame completo (amostras × canais).
        onsets:        índices das amostras de onset no DataFrame.
        epoch_samples: número de amostras por epoch (ex: 250 para 1s a 250 Hz).
        eeg_labels:    lista com os nomes das colunas EEG (ex: ["Ch01",...,"Ch08"]).

    Retorna:
        Array numpy 3D de shape (n_canais, epoch_samples, n_repetições).
        Retorna array vazia com shape (n_canais, epoch_samples, 0) se não houver epochs.
    """
    # n_canais: número de canais EEG a extrair.
    n_canais = len(eeg_labels)

    # Lista que vai acumular cada epoch extraído (cada epoch tem shape n_canais × epoch_samples).
    epochs_list = []

    for onset_idx in onsets:
        # inicio: índice da 1ª amostra do epoch (momento exato do onset).
        inicio = int(onset_idx)

        # fim: índice da última amostra do epoch (exclusive no iloc).
        fim = inicio + epoch_samples

        # Ignora epochs que ultrapassem o fim do sinal disponível.
        if fim > len(df):
            print(f"[WARN] Onset em {inicio} ignorado: epoch ultrapassa o fim do sinal.")
            continue

        # Extrai as amostras EEG para este epoch.
        # iloc[inicio:fim]: seleciona as linhas do onset até ao fim do epoch.
        # [eeg_labels]: seleciona apenas as colunas dos canais EEG (Ch01..Ch08).
        # .values: converte para array numpy de shape (epoch_samples, n_canais).
        epoch_data = df.iloc[inicio:fim][eeg_labels].values

        # Transpõe para (n_canais, epoch_samples) para a convenção [canais, amostras].
        epoch_data = epoch_data.T

        # Acumula o epoch na lista.
        epochs_list.append(epoch_data)

    # Se não houver epochs válidos, devolve array vazia com a shape correta.
    if len(epochs_list) == 0:
        print("[WARN] Nenhum epoch extraído para este conjunto de onsets.")
        return np.empty((n_canais, epoch_samples, 0))

    # np.stack: empilha a lista de arrays (n_canais, epoch_samples) ao longo do eixo 2.
    # Resultado: array 3D de shape (n_canais, epoch_samples, n_repetições).
    epochs_array = np.stack(epochs_list, axis=2)

    print(f"[INFO] Epochs extraídos: {epochs_array.shape[2]} | shape: {epochs_array.shape}")
    return epochs_array


# =============================================================
# FUNÇÃO: plot_erp
# Cria subplots com média ± desvio padrão para cada canal e condição.
# =============================================================

def plot_erp(
    targets: np.ndarray,
    non_targets: np.ndarray,
    srate: int,
    eeg_labels: list,
    output_path: str = None,
):
    """
    Cria subplots com a média e o desvio padrão dos epochs por condição.

    Para cada canal EEG, traça duas curvas sobrepostas:
    - Azul: média dos non_targets ± desvio padrão (banda sombreada)
    - Vermelho: média dos targets ± desvio padrão (banda sombreada)

    Parâmetros:
        targets:     array 3D (n_canais, n_amostras, n_reps) dos epochs target.
        non_targets: array 3D (n_canais, n_amostras, n_reps) dos epochs non-target.
        srate:       taxa de amostragem em Hz (para o eixo do tempo em ms).
        eeg_labels:  lista com os nomes dos canais EEG.
        output_path: se fornecido, guarda a figura neste ficheiro em vez de mostrar.
    """
    # n_canais: número de canais EEG (eixo 0 das arrays).
    n_canais = len(eeg_labels)

    # n_amostras: número de amostras por epoch (eixo 1 das arrays).
    # Usa o máximo entre targets e non_targets para garantir compatibilidade.
    n_amostras = max(
        targets.shape[1] if targets.shape[2] > 0 else 0,
        non_targets.shape[1] if non_targets.shape[2] > 0 else 0,
    )

    # time_ms: eixo temporal em milissegundos, do onset (0 ms) até ao fim do epoch.
    # linspace(0, n_amostras/srate * 1000, n_amostras) dá os instantes de cada amostra.
    time_ms = np.linspace(0, n_amostras / srate * 1000, n_amostras)

    # Cria a figura com uma linha de subplots por canal.
    # figsize adapta-se ao número de canais.
    fig, axes = plt.subplots(
        nrows=n_canais,
        ncols=1,
        figsize=(12, 2.5 * n_canais),
        sharex=True,  # todos os subplots partilham o mesmo eixo X
    )

    # Garante que axes é sempre uma lista, mesmo com um único canal.
    if n_canais == 1:
        axes = [axes]

    # Itera sobre cada canal EEG.
    for ch_idx, (ax, label) in enumerate(zip(axes, eeg_labels)):

        # --- Non-targets (azul) ---
        if non_targets.shape[2] > 0:
            # Extrai os epochs deste canal: shape (n_amostras, n_reps).
            nt_data = non_targets[ch_idx, :, :]

            # Calcula a média ao longo das repetições (eixo 1).
            nt_mean = nt_data.mean(axis=1)

            # Calcula o desvio padrão ao longo das repetições.
            nt_std  = nt_data.std(axis=1)

            # Traça a curva da média como linha sólida azul.
            ax.plot(time_ms, nt_mean, color="steelblue", linewidth=1.5,
                    label=f"Non-target (n={non_targets.shape[2]})")

            # Adiciona a banda de ±1 desvio padrão como área sombreada semi-transparente.
            ax.fill_between(time_ms,
                            nt_mean - nt_std,
                            nt_mean + nt_std,
                            color="steelblue", alpha=0.2)

        # --- Targets (vermelho) ---
        if targets.shape[2] > 0:
            # Extrai os epochs deste canal: shape (n_amostras, n_reps).
            t_data = targets[ch_idx, :, :]

            # Calcula a média ao longo das repetições.
            t_mean = t_data.mean(axis=1)

            # Calcula o desvio padrão ao longo das repetições.
            t_std  = t_data.std(axis=1)

            # Traça a curva da média como linha sólida vermelha.
            ax.plot(time_ms, t_mean, color="crimson", linewidth=1.5,
                    label=f"Target (n={targets.shape[2]})")

            # Adiciona a banda de ±1 desvio padrão.
            ax.fill_between(time_ms,
                            t_mean - t_std,
                            t_mean + t_std,
                            color="crimson", alpha=0.2)

        # Linha vertical a tracejado a marcar o onset do estímulo (t=0).
        ax.axvline(x=0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)

        # Linha horizontal a marcar o zero do sinal (baseline).
        ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5, alpha=0.4)

        # Label do eixo Y com o nome do canal.
        ax.set_ylabel(f"{label}\n(µV)", fontsize=8)

        # Legenda no canto superior direito de cada subplot.
        ax.legend(fontsize=7, loc="upper right")

        # Grelha de fundo para facilitar a leitura.
        ax.grid(True, alpha=0.3)

    # Label do eixo X apenas no subplot mais em baixo (sharex=True).
    axes[-1].set_xlabel("Tempo (ms)", fontsize=9)

    # Título geral da figura.
    fig.suptitle(
        "ERP P300 — Média ± Desvio Padrão por Canal\n"
        f"Targets: {targets.shape[2]} epochs | Non-targets: {non_targets.shape[2]} epochs",
        fontsize=11,
        fontweight="bold",
    )

    # Ajusta o espaçamento entre subplots.
    plt.tight_layout()

    if output_path:
        # Guarda a figura em disco no caminho especificado.
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"[INFO] Figura guardada em: {output_path}")
    else:
        # Mostra a figura numa janela interativa.
        plt.show()


# =============================================================
# FUNÇÃO PRINCIPAL: extract_p300_epochs
# Coordena todo o pipeline de extração e análise.
# =============================================================

def extract_p300_epochs(
    csv_path: str,
    iface_min: int   = DEFAULT_IFACE_MIN,
    iface_max: int   = DEFAULT_IFACE_MAX,
    srate: int       = DEFAULT_SRATE,
    epoch_ms: int    = DEFAULT_EPOCH_MS,
    save_npz: bool   = True,
    show_plot: bool  = True,
    output_dir: str  = None,
):
    """
    Pipeline completo de extração de epochs P300 a partir de um ficheiro CSV.

    Parâmetros:
        csv_path:   caminho para o ficheiro CSV do pipeline.
        iface_min:  valor mínimo do intervalo de códigos da interface (ex: 1).
        iface_max:  valor máximo do intervalo de códigos da interface (ex: 9).
        srate:      taxa de amostragem em Hz (ex: 250).
        epoch_ms:   duração de cada epoch em ms (ex: 1000).
        save_npz:   se True, guarda os arrays em ficheiro .npz.
        show_plot:  se True, gera e mostra/guarda os subplots ERP.
        output_dir: pasta de saída para .npz e .png. Se None, usa a pasta do CSV.

    Retorna:
        Dicionário com:
        - "geral":       array 3D com TODOS os epochs (targets + non_targets)
        - "targets":     array 3D com epochs de eventos FORA do intervalo da interface
        - "non_targets": array 3D com epochs de eventos DENTRO do intervalo da interface
    """
    # -------------------------------------------------------
    # PASSO 1 — Carregar e preparar o CSV
    # -------------------------------------------------------
    csv_path = Path(csv_path)

    # Verifica se o ficheiro CSV existe antes de tentar abrir.
    if not csv_path.exists():
        raise FileNotFoundError(f"Ficheiro CSV não encontrado: {csv_path}")

    # Carrega o CSV e transpõe para (amostras × canais).
    df = load_csv(str(csv_path))

    # Verifica se o canal de eventos existe no DataFrame.
    if EVENT_CHANNEL_LABEL not in df.columns:
        raise ValueError(
            f"Canal de eventos '{EVENT_CHANNEL_LABEL}' não encontrado no CSV.\n"
            f"Colunas disponíveis: {list(df.columns)}"
        )

    # Verifica se os canais EEG existem no DataFrame.
    missing = [c for c in EEG_CHANNEL_LABELS if c not in df.columns]
    if missing:
        raise ValueError(f"Canais EEG em falta no CSV: {missing}")

    # -------------------------------------------------------
    # PASSO 2 — Extrair o canal de eventos
    # -------------------------------------------------------

    # event_ch: Series com os valores do canal de eventos (Ch09) ao longo do tempo.
    # Arredonda para inteiro para evitar flutuações de vírgula flutuante (ex: 1.0000001 → 1).
    event_ch = df[EVENT_CHANNEL_LABEL].round().astype(int)

    # epoch_samples: número de amostras por epoch.
    # Ex: 1000 ms / 1000 * 250 Hz = 250 amostras.
    epoch_samples = int(epoch_ms / 1000 * srate)
    print(f"[INFO] Epoch: {epoch_ms} ms = {epoch_samples} amostras @ {srate} Hz")
    print(f"[INFO] Intervalo da interface: [{iface_min}, {iface_max}]")

    # -------------------------------------------------------
    # PASSO 3 — Detectar onsets e classificar em targets / non_targets
    # -------------------------------------------------------

    # Todos os onsets: qualquer transição de 0 → valor != 0 no canal de eventos.
    all_onsets = detect_onsets(event_ch)
    print(f"[INFO] Total de onsets detectados: {len(all_onsets)}")

    # Obtém o valor do código em cada onset (o code da célula que começou a piscar).
    onset_codes = event_ch.loc[all_onsets]

    # non_target_onsets: onsets onde o code está DENTRO do intervalo da interface.
    # São os flashes de células distractoras (não são o target deste trial).
    nt_mask = (onset_codes >= iface_min) & (onset_codes <= iface_max)
    non_target_onsets = onset_codes[nt_mask].index
    print(f"[INFO] Non-target onsets (code {iface_min}–{iface_max}): {len(non_target_onsets)}")

    # target_onsets: onsets onde o code está FORA do intervalo da interface.
    # São os flashes da célula target (identificados por um código especial, ex: 70).
    t_mask = (onset_codes < iface_min) | (onset_codes > iface_max)
    target_onsets = onset_codes[t_mask].index
    print(f"[INFO] Target onsets (code fora de [{iface_min},{iface_max}]): {len(target_onsets)}")

    # -------------------------------------------------------
    # PASSO 4 — Extrair epochs 3D para cada condição
    # -------------------------------------------------------

    print("\n[INFO] A extrair epochs non_targets...")
    # non_targets: array 3D (8, 250, n_nt) com os epochs dos distractores.
    non_targets = extract_epochs(df, non_target_onsets, epoch_samples, EEG_CHANNEL_LABELS)

    print("[INFO] A extrair epochs targets...")
    # targets: array 3D (8, 250, n_t) com os epochs do target real.
    targets = extract_epochs(df, target_onsets, epoch_samples, EEG_CHANNEL_LABELS)

    # geral: concatenação de targets e non_targets ao longo do eixo das repetições (eixo 2).
    # Útil para análises que não distinguem condição.
    if targets.shape[2] > 0 and non_targets.shape[2] > 0:
        geral = np.concatenate([targets, non_targets], axis=2)
    elif targets.shape[2] > 0:
        geral = targets.copy()
    elif non_targets.shape[2] > 0:
        geral = non_targets.copy()
    else:
        # Nenhum epoch foi extraído — array vazia com a shape correta.
        geral = np.empty((N_EEG_CHANNELS, epoch_samples, 0))

    print(f"\n[RESUMO] geral:       shape = {geral.shape}")
    print(f"[RESUMO] targets:     shape = {targets.shape}")
    print(f"[RESUMO] non_targets: shape = {non_targets.shape}")

    # -------------------------------------------------------
    # PASSO 5 — Guardar arrays em ficheiro .npz
    # -------------------------------------------------------

    # output_dir: pasta onde os ficheiros de saída serão guardados.
    if output_dir is None:
        output_dir = csv_path.parent
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    if save_npz:
        # Constrói o nome do ficheiro .npz a partir do nome do CSV.
        npz_path = output_dir / (csv_path.stem + "_epochs.npz")

        # np.savez: guarda múltiplas arrays num único ficheiro .npz (ZIP de .npy).
        # Cada array é acessível por nome ao carregar com np.load().
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
    # PASSO 6 — Gerar subplots ERP para validação visual
    # -------------------------------------------------------

    if show_plot:
        # Constrói o caminho do ficheiro de imagem (PNG).
        plot_path = str(output_dir / (csv_path.stem + "_erp.png"))

        print(f"\n[INFO] A gerar subplots ERP...")
        plot_erp(
            targets=targets,
            non_targets=non_targets,
            srate=srate,
            eeg_labels=EEG_CHANNEL_LABELS,
            output_path=plot_path,
        )

    # Devolve as três variáveis principais para uso em notebooks ou outros scripts.
    return {
        "geral":       geral,
        "targets":     targets,
        "non_targets": non_targets,
    }


# =============================================================
# INTERFACE DE LINHA DE COMANDOS
# Permite correr o script diretamente com argumentos configuráveis.
# =============================================================

def _parse_args():
    """
    Define e faz o parsing dos argumentos da linha de comandos.

    Exemplos de uso:
        python p300_epoch_extractor.py --csv outputs/User01/sessao.csv
        python p300_epoch_extractor.py --csv sessao.csv --iface_min 1 --iface_max 9
        python p300_epoch_extractor.py --csv sessao.csv --iface_min 1 --iface_max 36 --srate 250
    """
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
        "--iface_min",
        type=int,
        default=DEFAULT_IFACE_MIN,
        help=f"Código mínimo da interface (non_targets >= este valor). Default: {DEFAULT_IFACE_MIN}",
    )

    parser.add_argument(
        "--iface_max",
        type=int,
        default=DEFAULT_IFACE_MAX,
        help=f"Código máximo da interface (non_targets <= este valor). Default: {DEFAULT_IFACE_MAX}",
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
        help="Se indicado, não gera os subplots ERP.",
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
    # Faz o parsing dos argumentos da linha de comandos.
    args = _parse_args()

    # Chama a função principal com os parâmetros fornecidos.
    result = extract_p300_epochs(
        csv_path   = args.csv,
        iface_min  = args.iface_min,
        iface_max  = args.iface_max,
        srate      = args.srate,
        epoch_ms   = args.epoch_ms,
        save_npz   = not args.no_npz,
        show_plot  = not args.no_plot,
        output_dir = args.output_dir,
    )

    # As variáveis estão disponíveis em result["geral"], result["targets"], result["non_targets"].
    # Exemplo de uso após correr o script:
    #   data = np.load("sessao_epochs.npz")
    #   targets     = data["targets"]       # shape (8, 250, n_t)
    #   non_targets = data["non_targets"]   # shape (8, 250, n_nt)
    #   geral       = data["geral"]         # shape (8, 250, n_t + n_nt)