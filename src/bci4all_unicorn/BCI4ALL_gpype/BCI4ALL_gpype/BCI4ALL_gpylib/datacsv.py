# -*- coding: utf-8 -*-
"""
Created on Sat Apr 25 17:02:24 2026

@author: IPT
"""
import matplotlib.pyplot as plt
import numpy as np


#%% extract variables
# First column = labels
def  df_to_variables(df, N_channels):
    """
    This functions extracts the variables from pandas dataframe
    gpires - BCI4ALL 
    """
    labels = df.iloc[:, 0].values
    print(labels)
    # Remaining columns = data
    data = df.iloc[:, 1:].values.astype(float)
    # Timestamp row (first row)
    timestamps = data[0, :]   # shape: (samples,)
    # EEG channels 
    eeg_data = data[1:N_channels+1, :]   # shape: (channels, samples)
    print('EEG dimensions: ',eeg_data.shape)
    
    # Triggers
    triggers = data[N_channels+1, :]     # shape: (channels, samples)
    print(triggers)
    # targets
    targets = data[N_channels+2, :]      # shape: (channels, samples)
    print(targets)
    return labels, data, timestamps, eeg_data, triggers, targets


def plot_continuous_data(data,fs, N_channels):
    eeg_data = data[1:N_channels+1, :]   # shape: (channels, samples)
    # Triggers
    triggers = data[N_channels+1, :]     # shape: (channels, samples)
    # targets
    targets = data[N_channels+2, :]      # shape: (channels, samples)
    
    plt.figure(figsize=(12, 8))
    plt.suptitle('Countinuous data: eeg, triggers and target symbols')
    
    Ts=1/fs
    t=np.arange(data.shape[1])*Ts
    
    dim_y = np.shape(data)[0]
    #plot eeg
    for i in range(N_channels):
        plt.subplot(dim_y,1,i+1)
        plt.plot(t,eeg_data[i,:])
    
    #plot triggers and events    
    plt.subplot(dim_y,1,9)
    plt.plot(t,triggers)
    plt.subplot(dim_y,1,10)
    plt.plot(t,targets)
    
    plt.xlabel('Time(s)')
    
    plt.show()
    return 1

def plot_eeg_trigger_overlap(eeg_data, triggers):
    plt.figure(figsize=(12, 8))
    plt.plot(eeg_data)
    plt.plot(triggers)