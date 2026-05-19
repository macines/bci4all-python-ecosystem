#!/usr/bin/env python
"""
Script de instalação de dependências para BCI4ALL Python Ecosystem.

Uso:
    python install_dependencies.py

Cria um ambiente virtual em ./venv (se ainda não existir) e instala
nele todas as dependências necessárias. No fim, mostra o comando de
activação do venv.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
VENV_DIR = REPO_ROOT / "venv"


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def activate_hint(venv_dir: Path) -> str:
    if os.name == "nt":
        return f"{venv_dir.name}\\Scripts\\activate"
    return f"source {venv_dir.name}/bin/activate"


def ensure_venv(venv_dir: Path) -> Path:
    py = venv_python(venv_dir)
    if py.exists():
        print(f"venv já existe em: {venv_dir}")
        return py

    print(f"Criando venv em: {venv_dir}")
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("ERRO ao criar venv:")
        print(result.stderr)
        sys.exit(1)
    print("venv criado.")
    return py


def pip_install(python: Path, package: str) -> tuple[bool, str]:
    result = subprocess.run(
        [str(python), "-m", "pip", "install", package],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr


def install_dependencies() -> bool:
    print("=" * 60)
    print("BCI4ALL Python Ecosystem - Instalador de Dependências")
    print("=" * 60)
    print()

    packages = [
        "gpype==3.0.9",
        "PySide6==6.9.0",
        "pylsl==1.17.6",
        "numpy>=2.0,<3.0",
    ]

    optional_packages = [
        "scipy>=1.0",
        "matplotlib>=3.0",
        "pandas>=1.0",
    ]

    print(f"Python (host):   {sys.version.split()[0]}")
    print(f"Executável host: {sys.executable}")
    print()

    py = ensure_venv(VENV_DIR)
    print(f"Python do venv:  {py}")
    print()

    print("Actualizando pip no venv...")
    subprocess.run(
        [str(py), "-m", "pip", "install", "--upgrade", "pip"],
        check=False,
    )
    print()

    print("[1/2] Instalando dependências principais...")
    print("-" * 60)
    for package in packages:
        print(f"  Instalando: {package}")
        ok, err = pip_install(py, package)
        if not ok:
            print(f"  ERRO ao instalar {package}:")
            print(err)
            return False
        print(f"  ✓ {package} instalado")

    print()
    print("[2/2] Instalando dependências opcionais...")
    print("-" * 60)
    for package in optional_packages:
        print(f"  Instalando: {package}")
        ok, err = pip_install(py, package)
        if not ok:
            print(f"  AVISO: {package} não foi instalado (opcional)")
            print(f"  {err[:200]}")
        else:
            print(f"  ✓ {package} instalado")

    print()
    print("=" * 60)
    print("Instalação concluída com sucesso!")
    print("=" * 60)
    print()
    print("Activa o venv antes de executar os scripts:")
    print(f"  {activate_hint(VENV_DIR)}")
    print()
    print("Depois podes executar:")
    print("  python src/bci4all_unicorn/Demos/alpha-feedback-lsl/lsl_launcher.py")
    print("  python src/bci4all_unicorn/pipelines/experiments/p300/parte_5/p300_experiment_controller_lsl.py")

    return True


if __name__ == "__main__":
    success = install_dependencies()
    sys.exit(0 if success else 1)
