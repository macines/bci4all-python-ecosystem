#!/usr/bin/env python
"""
Script de instalação de dependências para BCI4ALL Python Ecosystem.

Uso:
    python install_dependencies.py

Este script instala automaticamente todas as dependências necessárias
para executar os projetos em bci4all-python-ecosystem.
"""

import subprocess
import sys

def install_dependencies():
    """Instala as dependências do projeto."""

    print("=" * 60)
    print("BCI4ALL Python Ecosystem - Instalador de Dependências")
    print("=" * 60)
    print()

    # Dependências principais
    packages = [
        "gpype==3.0.9",
        "PySide6==6.9.0",
        "pylsl==1.17.6",
        "numpy>=2.0,<3.0",
    ]

    # Dependências opcionais
    optional_packages = [
        "scipy>=1.0",
        "matplotlib>=3.0",
        "pandas>=1.0",
    ]

    print(f"Python: {sys.version}")
    print(f"Executável: {sys.executable}")
    print()

    # Instala dependências principais
    print("[1/2] Instalando dependências principais...")
    print("-" * 60)

    for package in packages:
        print(f"  Instalando: {package}")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"  ERRO ao instalar {package}:")
            print(result.stderr)
            return False
        print(f"  ✓ {package} instalado")

    print()
    print("[2/2] Instalando dependências opcionais...")
    print("-" * 60)

    for package in optional_packages:
        print(f"  Instalando: {package}")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"  AVISO: {package} não foi instalado (opcional)")
            print(f"  {result.stderr[:100]}")
        else:
            print(f"  ✓ {package} instalado")

    print()
    print("=" * 60)
    print("Instalação concluída com sucesso!")
    print("=" * 60)
    print()
    print("Podes agora executar:")
    print("  python src/bci4all_unicorn/Demos/alpha-feedback-lsl/lsl_launcher.py")
    print("  python src/bci4all_unicorn/pipelines/experiments/p300/parte_5/p300_experiment_controller_lsl.py")

    return True

if __name__ == "__main__":
    success = install_dependencies()
    sys.exit(0 if success else 1)
