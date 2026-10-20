@echo off
REM Builds DussehraGarland.exe (single file, no console window) into the "dist" folder.
REM Run this from the folder that contains dussehra_garland.py and garland.ico.
cd /d "%~dp0"
python -m pip install --upgrade PySide6 numpy pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name DussehraGarland ^
  --icon garland.ico ^
  --exclude-module tkinter ^
  dussehra_garland.py
echo.
echo Done. Your app is at: %~dp0dist\DussehraGarland.exe
pause
