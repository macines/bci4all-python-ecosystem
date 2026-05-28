# -*- coding: utf-8 -*-
"""
Script to extract and analyze epochs (targets and non-targets)

Adaptado para ler o CSV transposto gerado pelo pipeline BCI4ALL/gpype:

Formato do vosso CSV:
    Time, t1, t2, t3, ...
    Timestamp, ts1, ts2, ts3, ...
    Ch01, ...
    ...
    Ch08, ...
    Ch09, ...   # triggers/event codes
    Ch10, ...   # targets

Após leitura, o CSV é convertido para formato normal:
    Time | Timestamp | Ch01 | ... | Ch08 | Ch09 | Ch10
    uma linha por amostra
"""

# %%
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# my libs
from BCI4ALL_gpylib import datacsv
from BCI4ALL_gpylib import epochs

# %%
# Settings
fs = 250
Ts = 1 / fs
N_channels = 8
target_event_code = 70

# %%
# Extract CSV

# Path CSV file
file_path = "p300_full_output_lsl_20260520_122211.csv"

# ------------------------------------------------------------
# Leitura ao CSV transposto
# ------------------------------------------------------------
# O vosso CSV não vem em formato "uma amostra por linha".
# Vem transposto:
#   linha 1 -> Time
#   linha 2 -> Timestamp
#   linha 3 -> Ch01
#   ...
#   linha 11 -> Ch09
#   linha 12 -> Ch10
#
# Por isso, primeiro lemos sem header e depois convertemos para DataFrame normal.
# ------------------------------------------------------------

raw = pd.read_csv(file_path, header=None)

# Primeira coluna contém os nomes das variáveis:
# Time, Timestamp, Ch01, ..., Ch10
row_names = raw.iloc[:, 0].astype(str).tolist()

# Restantes colunas são as amostras temporais
values = raw.iloc[:, 1:]

# Converter para DataFrame normal:
# cada coluna passa a ser uma variável/canal
# cada linha passa a ser uma amostra temporal
df = pd.DataFrame({
    row_name: pd.to_numeric(values.iloc[i, :], errors="coerce").to_numpy()
    for i, row_name in enumerate(row_names)
})

print(df.head(15))
print(df.columns)

# Verificações básicas
expected_columns = ["Time", "Timestamp"] + [f"Ch{i:02d}" for i in range(1, 11)]
missing_columns = [col for col in expected_columns if col not in df.columns]

if missing_columns:
    raise ValueError(f"Faltam colunas esperadas no CSV: {missing_columns}")

print("Número de amostras:", len(df))
print("Duração aproximada:", df["Time"].iloc[-1] - df["Time"].iloc[0], "s")
print("Eventos em Ch09:", np.count_nonzero(df["Ch09"].to_numpy()))
print("Targets Ch09 == 70:", np.sum(df["Ch09"].to_numpy() == target_event_code))
print("Targets em Ch10:", np.count_nonzero(df["Ch10"].to_numpy()))

# %%
# Extract variables
# ------------------------------------------------------------
# Em vez de usar diretamente datacsv.df_to_variables(df, N_channels),
# extraímos manualmente para garantir compatibilidade com os nomes Ch01..Ch10.
#
# Mantemos as mesmas variáveis usadas no restante código:
# labels, data, timestamps, eeg_data, triggers, targets
# ------------------------------------------------------------

labels = df.columns.tolist()

# Timestamp absoluto vindo do CSV
timestamps = df["Timestamp"].to_numpy(dtype=float)

# Dados EEG no formato esperado pelas funções:
# canais x amostras
eeg_data = df[[f"Ch{i:02d}" for i in range(1, N_channels + 1)]].to_numpy(dtype=float).T

# Ch09 contém o código do evento:
# 1..9 = non-target
# 70 = target
triggers = df["Ch09"].to_numpy(dtype=float)

# Ch10 contém o identificador da célula target quando Ch09 == 70
targets = df["Ch10"].to_numpy(dtype=float)

# data completo, caso seja necessário para plots genéricos
data = df.to_numpy(dtype=float).T

print("labels:", labels)
print("data shape:", data.shape)
print("timestamps shape:", timestamps.shape)
print("eeg_data shape:", eeg_data.shape)
print("triggers shape:", triggers.shape)
print("targets shape:", targets.shape)

# plt.plot(triggers)
# plt.plot(targets)

# %%
# Plot continuous EEG and triggers

# Se a função datacsv.plot_continuous_data assumir um formato específico
# diferente, pode ser necessário ajustar. Mantemos a chamada original.
datacsv.plot_continuous_data(data, fs, N_channels)

# %%
# Plot EEG overlapped on triggers

channel = 1  # selected channel to visualize
datacsv.plot_eeg_trigger_overlap(eeg_data[channel, :], triggers)

# %%
# Extract target and non-target triggers

target_idx, nontarget_idx, target_codes = epochs.extract_triggers(
    triggers,
    target_event_code,
    targets
)

print("Targets:", len(target_idx))
print("Non-targets:", len(nontarget_idx))
print("List of target events:", target_codes)

# %%
# Extract epochs target and non-target from events/triggers

# Sugestão:
# Para ERP, é útil ter baseline antes do estímulo.
# Se quiseres manter exatamente a lógica original, usa:
#     tmin = 0
#     tmax = 1
#
# Mas para análise ERP mais correta, recomendo:
#     tmin = -0.2
#     tmax = 1.0

tmin = -0.2
tmax = 1.0

samp_i = int(round(abs(tmin) * fs))
samp_f = int(round(tmax * fs))
epoch_samples = samp_i + samp_f

# Time vector for each epoch
epoch_time = np.arange(-samp_i, samp_f) / fs

target_epochs, valid_target_idx = epochs.extract_epochs_ch_time_trials(
    eeg_data,
    target_idx,
    samp_i,
    samp_f
)

nontarget_epochs, valid_nontarget_idx = epochs.extract_epochs_ch_time_trials(
    eeg_data,
    nontarget_idx,
    samp_i,
    samp_f
)

y_t = target_epochs
y_nt = nontarget_epochs

print("Target epochs:", target_epochs.shape)
print("Non-target epochs:", nontarget_epochs.shape)

# %%
# Grouping epochs to increase SNR

group_size = 1

target_epochs_avg = epochs.average_epochs_in_groups(target_epochs, group_size)
nontarget_epochs_avg = epochs.average_epochs_in_groups(nontarget_epochs, group_size)

y_t = target_epochs_avg
y_nt = nontarget_epochs_avg

print(target_epochs.shape, "→", target_epochs_avg.shape)
print(nontarget_epochs.shape, "→", nontarget_epochs_avg.shape)

# %%
# Plot ERP average and standard deviation

epochs.plot_erp_with_std(y_t, fs, tmin, title="Target ERP")
epochs.plot_erp_with_std(y_nt, fs, tmin, title="Non-target ERP")

# %%
# Plot target vs non-target

epochs.plot_target_vs_nontarget(y_t, y_nt, fs, tmin, channel=2)

# %%
# ANALYSIS OF DISCRIMINATION

from BCI4ALL_gpylib import rsquare_fn

# %%
# Analysis of feature discrimination with r-square

N_samp = np.size(target_epochs, 1)

rsq = rsquare_fn.rsquare_allchannels(
    N_channels,
    N_samp,
    y_t,
    y_nt
)

print(np.shape(rsq))

rsquare_fn.plot_r2_heatmap(
    rsq,
    fs,
    tmin=tmin,
    channel_labels=None
)