import pandas as pd
import matplotlib.pyplot as plt

# Ler o CSV
df = pd.read_csv(r"C:\BCI4ALL\UnicornCore8\unicorn_project\p300_full_output.csv")

# Garantir que a coluna Time é numérica
df["Time"] = pd.to_numeric(df["Time"], errors="coerce")

# Criar figura com 3 subplots
fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)

# Subplot 1 - Canal 1
axes[0].plot(df["Time"], df["Ch01"], linewidth=0.8)
axes[0].set_title("Canal 1 (Ch01)")
axes[0].set_ylabel("Amplitude")
axes[0].grid(True)

# Subplot 2 - Canal 9
axes[1].step(df["Time"], df["Ch09"], where="post")
axes[1].set_title("Canal 9 (Ch09) - Eventos")
axes[1].set_ylabel("ID")
axes[1].grid(True)

# Subplot 3 - Canal 10
axes[2].step(df["Time"], df["Ch10"], where="post")
axes[2].set_title("Canal 10 (Ch10) - Target / Non-target")
axes[2].set_ylabel("Valor")
axes[2].set_xlabel("Tempo (s)")
axes[2].grid(True)

plt.tight_layout()
plt.show()