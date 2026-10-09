@echo off
setlocal
cd /d "%~dp0"
echo ==== Anime Astral Monitor: build the EXE ====
echo.

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version
if errorlevel 1 goto nopython

if not exist ".venv_build\Scripts\activate.bat" (
    echo Creating the build environment ...
    %PY% -m venv .venv_build
    if errorlevel 1 goto failed
)
call ".venv_build\Scripts\activate.bat"

echo Installing packages - the first time this takes a few minutes ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed

python build_exe.py
if errorlevel 1 goto failed

echo.
echo Done. The program is in:  dist\AnimeAstralMonitor\AnimeAstralMonitor.exe
explorer "dist\AnimeAstralMonitor"
pause
exit /b 0

:nopython
echo Python was not found. Please install Python 3.13 and enable "Add to PATH".
pause
exit /b 1

:failed
echo.
echo The build failed. Please read the messages above or send them to the developer.
pause
exit /b 1
