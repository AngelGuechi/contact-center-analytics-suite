@echo off
setlocal
set "BOOK=%~dp0..\AHT_Review.xlsx"
echo Updating AHT. Keep AHT_Review.xlsx closed in Excel.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh.ps1" -WorkbookPath "%BOOK%" -MoveUpdates -UseToday -PromptForIntervals
if errorlevel 1 (
  echo Update failed. The files remain in Update or History for correction and retry.
  pause
  exit /b 1
)
echo Update complete. New interval files were moved to History.
pause
