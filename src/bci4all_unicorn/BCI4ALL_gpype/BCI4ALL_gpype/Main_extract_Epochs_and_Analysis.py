# -*- coding: utf-8 -*-
"""
Created on Sat Apr 25 12:08:27 2026

@author: Gabriel Pires

Script to extract and analyze epochs (targets and non-targets)

"""

#%%
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

#my libs
#import sys
#sys.path.append("/BCI4ALL_gpylib")
#from BCI4ALL_gpylib.data import df_to_variables,plot_continuous_data, plot_eeg_trigger_overlap  
from BCI4ALL_gpylib import datacsv
from BCI4ALL_gpylib import epochs  

#%% settings
fs = 250
Ts= 1/ fs
N_channels = 8
target_event_code = 70 

#%% Extract csv
# expected CSV structure 
# Timestamps, EEG Channels, Triggers/Events, Targets

# Path CSV file
file_path = "BCIA4ALL_gpydata/p300_20260430_153054.csv"
#file_path = "p300_full_output_lsl_20260423_161538_experiencia23abril.csv"
# Load CSV
df = pd.read_csv(file_path)
print(df.head(15))
print(df.columns)
#plt.plot(df['triggers'])

#%% extract variables
labels, data, timestamps, eeg_data, triggers, targets = datacsv.df_to_variables(df, N_channels)
#plt.plot(triggers)
#plt.plot(targets)

#%% plot continuous eeg and triggers
datacsv.plot_continuous_data(data,fs, N_channels)

#%% plot eeg overlaped on triggers
channel = 1 #selected channel to visualize 
datacsv.plot_eeg_trigger_overlap(eeg_data[1,:], triggers)

#%%  Extract target and non-target triggers 
#target_event_code = 70  #already defined above
target_idx, nontarget_idx, target_codes = epochs.extract_triggers(triggers, target_event_code, targets)
print("Targets:", len(target_idx))
print("Non-targets:", len(nontarget_idx))
print("list of target events:",target_codes)

#%% Extract epochs (target and non-target) from event/triggers
#set the size of the window to extract 
tmin = 0  #-0.2
tmax = 1  #0.8

samp_i = int(round(abs(tmin) * fs))
samp_f = int(round(tmax * fs))
epoch_samples = samp_i + samp_f

# Time vector for each epoch
epoch_time = np.arange(-samp_i, samp_f) / fs

target_epochs, valid_target_idx = epochs.extract_epochs_ch_time_trials(eeg_data,target_idx,samp_i,samp_f)
nontarget_epochs, valid_nontarget_idx = epochs.extract_epochs_ch_time_trials(eeg_data,nontarget_idx,samp_i,samp_f)

y_t = target_epochs
y_nt = nontarget_epochs

print("Target epochs:", target_epochs.shape)
print("Non-target epochs:", nontarget_epochs.shape)

#%% Grouping epochs to increase SNR
group_size = 1
target_epochs_avg = epochs.average_epochs_in_groups(target_epochs, group_size)
nontarget_epochs_avg = epochs.average_epochs_in_groups(nontarget_epochs, group_size)

y_t = target_epochs_avg
y_nt = nontarget_epochs_avg

print(target_epochs.shape, "→", target_epochs_avg.shape)
print(nontarget_epochs.shape, "→", nontarget_epochs_avg.shape)


#%% Plot ERP average and standard deviation
epochs.plot_erp_with_std(y_t, fs, tmin, title="Target ERP")
epochs.plot_erp_with_std(y_nt, fs, tmin, title="Non-target ERP")

#%% Plot target vs non-target
epochs.plot_target_vs_nontarget(y_t, y_nt, fs, tmin, channel=2)


#%% "ANALYSIS OF DRISCRIMINATION"
"ANALYSIS OF DRISCRIMINATION"
from BCI4ALL_gpylib import rsquare_fn

#%% Analysis of feature discrimination with r-square 
#raw data
N_samp = np.size(target_epochs, 1)            #time samples

rsq = rsquare_fn.rsquare_allchannels(N_channels,N_samp,y_t,y_nt)
print(np.shape(rsq))

#rsquare_fn.plot_rsquare(epoch_time,rsq)  #old function
rsquare_fn.plot_r2_heatmap(rsq, fs, tmin=0, channel_labels=None)

