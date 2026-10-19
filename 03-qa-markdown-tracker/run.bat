@echo off
setlocal
title QA - Run portable version
pushd "%~dp0"
if errorlevel 1 exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-portable.ps1" -Action Run -Mode "%~1"
set "qaExit=%ERRORLEVEL%"
popd
if "%~1"=="" pause
exit /b %qaExit%
