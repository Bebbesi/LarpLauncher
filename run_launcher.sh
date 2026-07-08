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
python main.py