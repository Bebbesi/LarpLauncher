it@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || exit /b 1
)

call ".venv\Scripts\activate.bat" || exit /b 1
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt || exit /b 1
pyinstaller --clean --noconfirm LarpLauncher.spec || exit /b 1

if exist "dist\LarpLauncher.exe" (
    echo.
    echo Built dist\LarpLauncher.exe
)
