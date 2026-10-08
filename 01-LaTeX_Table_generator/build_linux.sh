#!/usr/bin/env bash
# Builds a single-file executable: ./dist/LaTeXTableGen
set -e
cd "$(dirname "$0")"
python3 -m venv .build-venv
source .build-venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --onefile --name LaTeXTableGen \
  --add-data "assets:assets" main.py
echo "Done: dist/LaTeXTableGen"
