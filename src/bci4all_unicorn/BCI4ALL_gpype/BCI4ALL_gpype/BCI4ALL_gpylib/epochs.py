# -*- coding: utf-8 -*-
"""
Created on Sat Apr 25 18:07:44 2026

@author: gpires
"""

import numpy as np
import matplotlib.pyplot as plt

def extract_triggers(triggers, target_event_code, targets):
    """
    Extracts the indices of targets, non-targets and target codes 
    """
    
    #all events (target and non-targets)
    all_event_idx = np.where((triggers[:-1] == 0) & (triggers[1:] != 0))[0] + 1
    event_codes = triggers[all_event_idx].astype(int)
    
    # Target events
    target_mask = event_codes == target_event_code
    target_idx = all_event_idx[target_mask]
    # Non-target events (exclude zeros just in case)
    nontarget_mask = (event_codes != 0) & (event_codes != target_event_code)
    nontarget_idx = all_event_idx[nontarget_mask]
    
    # print("Targets:", len(target_idx))
    # print("Non-targets:", len(nontarget_idx))
    
    #A simple test for verification 
    #all_event_idx[0]
    #triggers[target_idx[0]+1]
    
    target_codes = targets[target_idx]
    #print("list of target events:",target_codes)
    return target_idx, nontarget_idx, target_codes



def extract_epochs_ch_time_trials(eeg_data, event_idx, pre_samples, post_samples):
    """
    Extract epochs from EEG data.

    Parameters
    ----------
    eeg_data : ndarray
        EEG data with shape (channels, samples).
    event_idx : ndarray
        Event onset sample indices.
    pre_samples : int
        Number of samples before event onset.
    post_samples : int
        Number of samples after event onset.

    Returns
    -------
    epochs : ndarray
        Epochs with shape (channels, time_samples, trials).
    valid_event_idx : ndarray
        Event indices for which complete epochs were extracted.
    """

    n_channels, n_samples = eeg_data.shape
    epoch_len = pre_samples + post_samples

    epochs = []
    valid_event_idx = []

    for idx in event_idx:
        start = idx - pre_samples
        stop = idx + post_samples

        if start >= 0 and stop <= n_samples:
            epoch = eeg_data[:, start:stop]  # channels x time
            epochs.append(epoch)
            valid_event_idx.append(idx)

    if len(epochs) == 0:
        return np.empty((n_channels, epoch_len, 0)), np.array([])

    # Current shape after stacking: trials x channels x time
    epochs = np.stack(epochs, axis=0)

    # Convert to channels x time x trials
    epochs = np.transpose(epochs, (1, 2, 0))

    return epochs, np.array(valid_event_idx)


def average_epochs_in_groups(epochs, group_size):
    """
    Average epochs in non-overlapping groups.

    Parameters
    ----------
    epochs : ndarray
        Shape (channels, time_samples, trials)
    group_size : int
        Number of epochs to average per group

    Returns
    -------
    grouped_epochs : ndarray
        Shape (channels, time_samples, new_trials)
    """

    n_channels, n_times, n_trials = epochs.shape

    # Number of full groups
    n_groups = n_trials // group_size

    if n_groups == 0:
        raise ValueError("group_size is larger than number of trials")

    # Trim excess trials
    trimmed_epochs = epochs[:, :, :n_groups * group_size]

    # Reshape: (channels, time, groups, group_size)
    reshaped = trimmed_epochs.reshape(
        n_channels,
        n_times,
        n_groups,
        group_size
    )

    # Average over group_size dimension
    grouped_epochs = np.mean(reshaped, axis=3)

    return grouped_epochs


def plot_erp_with_std(epochs, fs, tmin, channels=None, title="ERP"):
    """
    Plot ERP (mean) and mean ± std for selected channels.

    Parameters
    ----------
    epochs : ndarray
        Shape (channels, time_samples, trials)
    fs : int
        Sampling frequency
    tmin : float
        Start time of epoch (seconds)
    channels : list or None
        Channels to plot (indices). If None, plot all.
    title : str
        Figure title
    """

    n_channels, n_times, n_trials = epochs.shape

    if channels is None:
        channels = list(range(n_channels))

    # Time vector
    t = np.arange(n_times) / fs + tmin

    # Compute statistics
    mean_erp = np.mean(epochs, axis=2)
    std_erp = np.std(epochs, axis=2)

    # Create subplots
    fig, axes = plt.subplots(len(channels), 1, figsize=(10, 2*len(channels)), sharex=True)

    if len(channels) == 1:
        axes = [axes]

    for i, ch in enumerate(channels):
        ax = axes[i]

        mean = mean_erp[ch, :]
        std = std_erp[ch, :]

        # Mean line
        ax.plot(t, mean, label='Mean')

        # Shaded std
        ax.fill_between(t, mean - std, mean + std, alpha=0.3)

        # Zero lines (important for ERP)
        ax.axvline(0, linestyle='--', linewidth=1)
        ax.axhline(0, linewidth=0.8)

        ax.set_ylabel(f'Ch{ch+1}')
        ax.grid(True)

    axes[-1].set_xlabel("Time (s)")
    plt.suptitle(title)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    plt.show()
    
    
def plot_target_vs_nontarget(target_epochs, nontarget_epochs, fs, tmin, channel=0):
    t = np.arange(target_epochs.shape[1]) / fs + tmin

    mean_t = np.mean(target_epochs[channel, :, :], axis=1)
    std_t = np.std(target_epochs[channel, :, :], axis=1)

    mean_nt = np.mean(nontarget_epochs[channel, :, :], axis=1)
    std_nt = np.std(nontarget_epochs[channel, :, :], axis=1)

    plt.figure(figsize=(8, 4))

    # Target
    plt.plot(t, mean_t, label='Target')
    plt.fill_between(t, mean_t - std_t, mean_t + std_t, alpha=0.3)

    # Non-target
    plt.plot(t, mean_nt, label='Non-target')
    plt.fill_between(t, mean_nt - std_nt, mean_nt + std_nt, alpha=0.2)

    plt.axvline(0, linestyle='--')
    plt.axhline(0)

    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.title(f"ERP Comparison - Channel {channel+1}")
    plt.legend()
    plt.grid(True)

    plt.show()    

