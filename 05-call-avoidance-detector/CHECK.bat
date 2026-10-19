@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "CA_SHORTCUT_NOPAUSE=0"
set "CA_SHORTCUT_RESULT=1"
:scan_arguments
if "%~1"=="" goto start
if /I "%~1"=="/nopause" set "CA_SHORTCUT_NOPAUSE=1"
shift /1
goto scan_arguments

:start
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto folder_error
if not exist "%~dp0.venv\Scripts\python.exe" goto missing_environment
"%~dp0.venv\Scripts\python.exe" -u "%~dp0launch.py" check %*
set "CA_SHORTCUT_RESULT=%errorlevel%"
goto finished

:missing_environment
echo NEEDS ACTION: The local Python environment is missing.
echo Run INSTALL.bat once on this computer. CHECK.bat never installs packages.
echo If setup failed, read runtime\install.log and HOW_TO_RUN.md.
goto finished

:folder_error
echo NEEDS ACTION: The app folder cannot be opened. Extract the complete app folder.
goto finish_without_pop

:finished
popd
:finish_without_pop
if "%CA_SHORTCUT_NOPAUSE%"=="0" pause
exit /b %CA_SHORTCUT_RESULT%
