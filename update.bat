@echo off
setlocal
cd /d "%~dp0"
title Anime Astral Monitor - Updater

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython

if not exist ".venv_build\Scripts\python.exe" (
    echo Erstelle Arbeitsumgebung - nur beim ersten Mal ...
    %PY% -m venv .venv_build
    if errorlevel 1 goto failed
)

rem Die letzte Zeile enthaelt alles bis zum Ende, damit update.bat sich waehrend des Laufs selbst ersetzen darf.
".venv_build\Scripts\python.exe" update.py %* & echo. & pause & exit /b

:nopython
echo Python wurde nicht gefunden. Bitte Python 3.10 bis 3.13 installieren und "Add to PATH" aktivieren.
pause
exit /b 1

:failed
echo Die Arbeitsumgebung konnte nicht erstellt werden.
pause
exit /b 1
