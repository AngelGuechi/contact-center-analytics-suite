@echo off
setlocal
cd /d "%~dp0"
echo Installing optional local audio tools. Close the app first.
if /I "%~1"=="/nopause" (
  py -3.12 audio_setup.py
) else (
  py -3.12 audio_setup.py %*
)
if errorlevel 1 (
  echo Installation needs attention. Read the message above and AUDIO_HOW_TO_RUN.md.
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)
if /I not "%~1"=="/nopause" pause
