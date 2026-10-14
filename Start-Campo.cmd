@echo off
setlocal
cd /d "%~dp0"
set "CAMPO_BOOTSTRAP="
for %%D in ("%USERPROFILE%\.conda\envs\campo-reader" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3" "%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\Programs\anaconda3" "%LOCALAPPDATA%\Programs\miniconda3" "%ProgramFiles%\anaconda3" "%ProgramFiles%\miniconda3") do (
  if not defined CAMPO_BOOTSTRAP if exist "%%~D\python.exe" set "CAMPO_BOOTSTRAP=%%~D\python.exe"
)
if not defined CAMPO_BOOTSTRAP (
  for /f "delims=" %%C in ('where conda.bat 2^>nul') do (
    if not defined CAMPO_BOOTSTRAP if exist "%%~dpC..\python.exe" set "CAMPO_BOOTSTRAP=%%~dpC..\python.exe"
  )
)
if not defined CAMPO_BOOTSTRAP (
  echo Anaconda or Miniconda was not found. Install it first, then double-click this file again.
  echo https://www.anaconda.com/docs/getting-started/miniconda/main
  pause
  exit /b 1
)
"%CAMPO_BOOTSTRAP%" "%~dp0launch.py" %*
if errorlevel 1 pause
