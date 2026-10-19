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
if defined CA_PYTHON goto override_python
where py.exe >nul 2>&1
if errorlevel 1 goto find_python
py -3.12 -I -c "import sys; raise SystemExit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
if not errorlevel 1 goto python312
py -3.13 -I -c "import sys; raise SystemExit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
if not errorlevel 1 goto python313
py -3.14 -I -c "import sys; raise SystemExit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
if not errorlevel 1 goto python314

:find_python
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    set "CA_SETUP_CANDIDATE=%%P"
    call :probe_candidate
    if not errorlevel 1 goto found_python
)
goto missing_python

:probe_candidate
if /I "%CA_SETUP_CANDIDATE%"=="%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" exit /b 1
"%CA_SETUP_CANDIDATE%" -I -c "import sys; raise SystemExit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
exit /b %errorlevel%

:found_python
"%CA_SETUP_CANDIDATE%" -I "%~dp0setup.py" %*
set "CA_SHORTCUT_RESULT=%errorlevel%"
goto finished

:override_python
rem CA_PYTHON is an executable path, never a command with arguments.
rem Strip optional surrounding quotes before keeping the complete path quoted.
set "CA_SETUP_CANDIDATE=%CA_PYTHON:"=%"
if not exist "%CA_SETUP_CANDIDATE%" goto override_error
"%CA_SETUP_CANDIDATE%" -I "%~dp0setup.py" %*
set "CA_SHORTCUT_RESULT=%errorlevel%"
goto finished

:python312
py -3.12 -I "%~dp0setup.py" %*
set "CA_SHORTCUT_RESULT=%errorlevel%"
goto finished

:python314
py -3.14 -I "%~dp0setup.py" %*
set "CA_SHORTCUT_RESULT=%errorlevel%"
goto finished

:python313
py -3.13 -I "%~dp0setup.py" %*
set "CA_SHORTCUT_RESULT=%errorlevel%"
goto finished

:missing_python
echo Python 3.12, 3.13 or 3.14 could not be found. Python 3.12 is preferred.
echo Install Python for your user account from https://www.python.org/downloads/windows/
echo Include the Python launcher, then run INSTALL.bat again.
echo You can also set CA_PYTHON to the full path of a supported python.exe.
echo No administrator access or PowerShell policy change is needed by this app.
goto finished

:override_error
echo CA_PYTHON does not point to an existing Python executable.
echo Set it to the full python.exe path without extra arguments, or clear it.
goto finished

:folder_error
echo The app folder cannot be opened. Extract the complete folder to a writable location.
goto finish_without_pop

:finished
if not "%CA_SHORTCUT_RESULT%"=="0" echo Setup did not finish. Read HOW_TO_RUN.md and runtime\install.log for help.
popd
:finish_without_pop
if "%CA_SHORTCUT_NOPAUSE%"=="0" pause
exit /b %CA_SHORTCUT_RESULT%
