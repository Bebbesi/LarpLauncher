#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source ".venv/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt
pyinstaller --clean --noconfirm LarpLauncher.spec

if [ -f "dist/LarpLauncher" ]; then
    echo ""
    echo "Built dist/LarpLauncher"
fi