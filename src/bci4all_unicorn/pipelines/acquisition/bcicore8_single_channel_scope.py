import gpype as gp

# Sampling rate
fs = 250

if __name__ == "__main__":

    # === APPLICATION ===
    app = gp.MainApp()
    p = gp.Pipeline()

    # === EEG SOURCE ===
    # g.tec BCI Core-8 amplifier
    source = gp.BCICore8()

    # === SELECT ONLY ONE CHANNEL (ex: POz) ===
    # Change the index depending on where POz is connected
    select_poz = gp.Router(input_channels=[[4]])
    
    # === SIGNAL PROCESSING ===
    bandpass = gp.Bandpass(
        f_lo=1,
        f_hi=30
    )

    notch50 = gp.Bandstop(
        f_lo=48,
        f_hi=52
    )

    notch60 = gp.Bandstop(
        f_lo=58,
        f_hi=62
    )

    # === VISUALIZATION ===
    scope = gp.TimeSeriesScope(
        amplitude_limit=50,
        time_window=10
    )

    # === PIPELINE CONNECTION ===
    p.connect(source, select_poz)
    p.connect(select_poz, bandpass)
    p.connect(bandpass, notch50)
    p.connect(notch50, notch60)
    p.connect(notch60, scope)

    # === GUI ===
    app.add_widget(scope)

    # === RUN ===
    p.start()
    app.run()
    p.stop()