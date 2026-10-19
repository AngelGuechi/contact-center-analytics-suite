@echo off
setlocal
title QA - Install portable version
pushd "%~dp0"
if errorlevel 1 exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-portable.ps1" -Action Install
set "qaExit=%ERRORLEVEL%"
popd
if /I not "%~1"=="/nopause" pause
exit /b %qaExit%
