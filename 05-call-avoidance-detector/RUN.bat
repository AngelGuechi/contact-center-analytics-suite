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
"%~dp0.venv\Scripts\python.exe" -u "%~dp0launch.py" run %*
set "CA_SHORTCUT_RESULT=%errorlevel%"
goto finished

:missing_environment
echo This computer's app environment is not installed yet.
echo Run INSTALL.bat once, then open RUN.bat again.
goto finished

:folder_error
echo The app folder cannot be opened. Extract or copy the complete app folder.
goto finish_without_pop

:finished
if not "%CA_SHORTCUT_RESULT%"=="0" echo The app needs attention. Run CHECK.bat and read HOW_TO_RUN.md.
popd
:finish_without_pop
if "%CA_SHORTCUT_NOPAUSE%"=="0" pause
exit /b %CA_SHORTCUT_RESULT%
