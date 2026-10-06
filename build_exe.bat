@echo off
setlocal
cd /d "%~dp0"
echo ==== Anime Astral Monitor: EXE bauen ====
echo.

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version
if errorlevel 1 goto nopython

if not exist ".venv_build\Scripts\activate.bat" (
    echo Erstelle Build-Umgebung ...
    %PY% -m venv .venv_build
    if errorlevel 1 goto failed
)
call ".venv_build\Scripts\activate.bat"

echo Installiere Pakete - das dauert beim ersten Mal ein paar Minuten ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed

python build_exe.py
if errorlevel 1 goto failed

echo.
echo Fertig. Das Programm liegt in:  dist\AnimeAstralMonitor\AnimeAstralMonitor.exe
explorer "dist\AnimeAstralMonitor"
pause
exit /b 0

:nopython
echo Python wurde nicht gefunden. Bitte Python 3.10 bis 3.13 installieren und "Add to PATH" aktivieren.
pause
exit /b 1

:failed
echo.
echo Der Build ist fehlgeschlagen. Bitte die Meldungen oben lesen oder an mich schicken.
pause
exit /b 1
