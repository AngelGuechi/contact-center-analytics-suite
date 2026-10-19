@echo off
setlocal
cd /d "%~dp0"
py -3.12 audio_setup.py --check
set "audio_result=%errorlevel%"
if /I not "%~1"=="/nopause" pause
exit /b %audio_result%
