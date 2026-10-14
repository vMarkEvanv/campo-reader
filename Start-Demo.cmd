@echo off
setlocal
cd /d "%~dp0"
set "CAMPO_PYTHON=%USERPROFILE%\.conda\envs\campo-reader\pythonw.exe"
if exist "%CAMPO_PYTHON%" (
  start "" "%CAMPO_PYTHON%" "%~dp0main.py" --demo
  exit /b
)
call conda run --no-capture-output -n campo-reader python "%~dp0main.py" --demo
if errorlevel 1 pause
