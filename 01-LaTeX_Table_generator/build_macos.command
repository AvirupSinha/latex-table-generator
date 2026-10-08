#!/usr/bin/env bash
# Double-click this file on macOS to build "LaTeX Table Generator.app" into ./dist
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -m venv .build-venv
source .build-venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name "LaTeX Table Generator" \
  --add-data "assets:assets" main.py
echo
echo "Done. Opening dist/ - drag 'LaTeX Table Generator.app' into Applications."
open dist
