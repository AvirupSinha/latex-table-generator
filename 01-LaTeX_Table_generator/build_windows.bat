@echo off
REM Double-click to build dist\LaTeXTableGen.exe (single file)
cd /d "%~dp0"
py -3 -m venv .build-venv || goto :err
call .build-venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto :err
pyinstaller --noconfirm --clean --windowed --onefile --name LaTeXTableGen --add-data "assets;assets" main.py || goto :err
echo.
echo Done. Opening dist folder...
explorer dist
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
