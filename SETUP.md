# BCI4ALL Python Ecosystem — Configuração do Ambiente

## Quick Start (3 passos)

### 1. Clona ou obtém o repositório
```bash
cd /caminho/para/bci4all-python-ecosystem
```

### 2. Instala as dependências (cria venv automaticamente)
```powershell
py -3.10 install_dependencies.py
```

O script cria `./venv` com Python 3.10 e instala lá todas as dependências.

> **Importante:** usa obrigatoriamente Python 3.10 — `gpype 3.0.9` não tem wheels para 3.11+.

**Alternativa manual:**
```powershell
py -3.10 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Activa o venv e valida a instalação
```powershell
venv\Scripts\activate
python -c "import gpype; import PySide6; from pylsl import StreamInfo; print('OK: Tudo instalado')"
```

---

## Requisitos

- **Python 3.10** (obrigatório — `gpype 3.0.9` não tem wheels para 3.11/3.12/3.14, testado em 3.10.11)
- **pip** (gestor de pacotes)
- **Conexão com internet** (para baixar pacotes)

---

## Pacotes Instalados

### Obrigatórios
| Pacote | Versão | Descrição |
|--------|--------|-----------|
| `gpype` | 3.0.9 | Framework de processamento de sinal em pipeline |
| `PySide6` | 6.9.0 | Interface Qt para GUI |
| `pylsl` | 1.17.6 | Lab Streaming Layer — comunicação BCI em tempo real |
| `numpy` | ≥2.0 | Cálculo numérico |

### Opcionais (para análises)
- `scipy` — processamento de sinal científico
- `matplotlib` — visualização gráfica
- `pandas` — manipulação de dados

---

## Estrutura do Projeto

```
bci4all-python-ecosystem/
├── src/bci4all_unicorn/
│   ├── Demos/
│   │   ├── alpha-feedback-lsl/    ← Demo de feedback Alpha
│   │   │   └── lsl_launcher.py
│   │   └── ...
│   └── pipelines/
│       ├── experiments/
│       │   └── p300/
│       │       └── parte_5/       ← Versão 5 com clock único LSL
│       │           ├── p300_experiment_controller_lsl.py
│       │           ├── p300_pipeline_gpype_lsl.py
│       │           ├── p300_experiment_setup.py
│       │           ├── p300_single_cell_grid.py
│       │           └── p300_sequence.py
│       └── ...
├── requirements.txt               ← Dependências
├── install_dependencies.py        ← Script de instalação
└── README.md
```

---

## Executar Demo P300 (Parte 5)

```bash
python src/bci4all_unicorn/pipelines/experiments/p300/parte_5/p300_experiment_controller_lsl.py
```

**Fluxo:**
1. Menu principal — seleciona condição (Offline/Online) + ID do utilizador
2. Diálogo de configuração — ajusta parâmetros (rondas, flash, ISI, targets)
3. Interface visual — grelha 3×3 com feedback visual
4. Pipeline paralelo — processa EEG e grava CSV

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'PySide6'"
**Causa:** Dependências não instaladas ou instaladas em Python diferente.
**Solução:**
```bash
python -m pip install PySide6 gpype pylsl
```

### "ImportError: DLL load failed"
**Causa:** Versão incompatível de PySide6 com Windows/Visual C++.
**Solução:** Reinstala PySide6
```bash
pip uninstall PySide6 -y
pip install PySide6==6.9.0
```

### LSL streams não aparecem
**Causa:** Processes não estão em execução.
**Verificação:** Abre dois terminais:
```bash
# Terminal 1
python src/bci4all_unicorn/pipelines/experiments/p300/parte_5/p300_experiment_controller_lsl.py

# Terminal 2 — lista streams disponíveis
python -c "from pylsl import resolve_byprop; print(resolve_byprop('type', 'Markers'))"
```

---

## Notas para Colega

- **Virtual Environment:** O `install_dependencies.py` cria `./venv` automaticamente com Python 3.10. Activa-o sempre antes de correr scripts:
  ```powershell
  venv\Scripts\activate     # Windows
  source venv/bin/activate  # Linux/Mac
  ```
- **Re-criar o venv:** Se mudares versão de Python ou quiseres ambiente limpo, apaga `venv/` e corre o script outra vez.
- **Documentação do Código:** Os ficheiros em `parte_5/` têm comentários extensos explicando a arquitectura
- **Timestamp LSL:** O pipeline usa `local_clock()` como referencial único — sem deriva acumulada

---

**Última actualização:** 2026-05-19
