@echo off
setlocal
cd /d "%~dp0"
set "CAMPO_PYTHON=%USERPROFILE%\.conda\envs\campo-reader\pythonw.exe"
if exist "%CAMPO_PYTHON%" (
  start "" "%CAMPO_PYTHON%" "%~dp0main.py"
  exit /b
)
where conda >nul 2>nul
if errorlevel 1 (
  echo Please open Anaconda Prompt and follow README.md to install campo-reader.
  pause
  exit /b 1
)
call conda run --no-capture-output -n campo-reader python "%~dp0main.py"
if errorlevel 1 pause
