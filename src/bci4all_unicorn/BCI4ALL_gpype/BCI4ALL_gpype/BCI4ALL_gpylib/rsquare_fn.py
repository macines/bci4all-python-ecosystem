# -*- coding: utf-8 -*-
"""
version Python 3.8.8
Created on Tue Jun  7 14:31:56 2022

RSQU   erg=rsqu(r, q) computes the r2-value for
       two one-dimensional distributions given by
       the vectors q and r

r2 version adapted to Python
and r2 color map visualization

@author: Gabriel Pires, June 2022
"""
import numpy as np
#from matplotlib.colors import Normalize
#from matplotlib import cm
import matplotlib.pyplot as plt
import pylab

"""
r2 computation
"""
def rsquare(q,r):
    sum1 = np.sum(q);
    sum2 = np.sum(r);
    n1=np.size(q, axis=0);
    n2=np.size(r, axis=0);
    sumsqu1=np.sum(np.multiply(q,q));
    sumsqu2=np.sum(np.multiply(r,r));

    G=((sum1+sum2)**2)/(n1+n2);

    erg=(sum1**2/n1+sum2**2/n2-G)/(sumsqu1+sumsqu2-G);
    return erg


def rsquare_allchannels(N_ch,N_samp,target_epochs,nontarget_epochs):
    rsq = np.zeros((N_samp, N_ch))
    print(np.shape(rsq))
    for ch in np.arange(N_ch):
        for samp in np.arange(N_samp):
            rsq[samp, ch] = rsquare(target_epochs[ch, samp,:],nontarget_epochs[ch, samp,:])
            
    return rsq



"""
Color map to visualize r2
"""
def plot_rsquare(t,ressq):
    data2plot = np.transpose(ressq)
    
    tamx=np.shape(data2plot)
    #print(tamx[0])  
    data2plot = np.concatenate( (data2plot, np.zeros((tamx[0],1)) ), 1)
    tamx=np.shape(data2plot)

    #print(np.shape(data2plot))  
    data2plot = np.concatenate( (data2plot, np.zeros((1,tamx[1])) ), 0)
    xData=t;
    xData=np.append(xData, xData[-1] + np.diff(xData[len(xData)-2 : len(xData)]));

    Nch=np.size(ressq, axis=1)

    #ax.pcolormesh(xData,np.arange(Nch+1),data2plot, vmin=-0.5, vmax=1.0)
    # ax.plot_surface(x, y, z, cmap=plt.cm.YlGnBu_r)
    pylab.pcolor(xData, np.arange(Nch+1), data2plot, cmap=plt.cm.jet )
    pylab.colorbar()
    pylab.ylabel('Channels')
    pylab.xlabel('time (s)')
    pylab.title('Statistical r^2 between class1 and class2')
    pylab.show() 
    
    return 1

def plot_r2_heatmap(rsq, fs, tmin=-0.2, channel_labels=None):
    """
    Plot R² heatmap (time x channels).

    Parameters
    ----------
    rsq : ndarray
        Shape (time_samples, channels)
    fs : int
        Sampling frequency
    tmin : float
        Start time (seconds)
    channel_labels : list or None
        Channel names
    """

    n_times, n_channels = rsq.shape

    # Time vector
    t = np.arange(n_times) / fs + tmin

    plt.figure(figsize=(10, 4))

    im = plt.imshow(
        rsq.T,                # transpose → channels x time
        aspect='auto',
        origin='lower',
        extent=[t[0], t[-1], 0, n_channels],
        interpolation='nearest',
        cmap='jet'
    )

    plt.colorbar(im, label='R²')

    plt.xlabel('Time (s)')
    plt.ylabel('Channels')

    # Optional channel labels
    if channel_labels is not None:
        plt.yticks(np.arange(n_channels), channel_labels)
    else:
        plt.yticks(np.arange(n_channels), [f'Ch{i+1}' for i in range(n_channels)])

    # Mark stimulus onset
    plt.axvline(0, color='white', linestyle='--', linewidth=1)

    plt.title('R² Heatmap (Target vs Non-target)')
    plt.tight_layout()
    plt.show()    
