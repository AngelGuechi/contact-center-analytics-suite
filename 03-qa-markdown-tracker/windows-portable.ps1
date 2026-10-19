param(
    [ValidateSet('Install', 'Run')][string]$Action = 'Run',
    [string]$Mode = ''
)
$ErrorActionPreference = 'Stop'
$qaRoot = $PSScriptRoot
$qaEnvironmentPython = Join-Path $qaRoot '.venv/Scripts/python.exe'

function Test-Python([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    try {
        & $Candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-Python {
    $qaCandidates = @($env:QA_PYTHON, $qaEnvironmentPython)
    $qaLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($qaLauncher) {
        foreach ($qaVersion in @('-3.12', '-3')) {
            try {
                $qaResolved = & $qaLauncher.Source $qaVersion -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0) { $qaCandidates += $qaResolved }
            } catch { }
        }
    }
    if ($env:LOCALAPPDATA) { $qaCandidates += Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe' }
    $qaCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($qaCommand) { $qaCandidates += $qaCommand.Source }
    foreach ($qaCandidate in $qaCandidates | Select-Object -Unique) {
        if (Test-Python $qaCandidate) { return $qaCandidate }
    }
    return $null
}

function Install-QA {
    Write-Host ''
    Write-Host 'Installing both QA solutions for this Windows computer.'
    Write-Host 'Your source files, reports and coaching will be kept.'
    $qaPython = Find-Python
    if (-not $qaPython) {
        $qaWinget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $qaWinget) {
            throw 'Python was not found. Install Python 3.12 from https://www.python.org/downloads/windows/ and run portable.bat again.'
        }
        Write-Host 'Installing Python 3.12 using Windows Package Manager...'
        & $qaWinget.Source install --id Python.Python.3.12 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw 'Windows could not install Python. Install Python 3.12 from python.org, then run portable.bat again.' }
        $qaPython = Find-Python
        if (-not $qaPython) { throw 'Python was installed, but is not available yet. Close this window and run portable.bat again.' }
    }
    $qaLogFolder = Join-Path $qaRoot 'runtime'
    New-Item -ItemType Directory -Path $qaLogFolder -Force | Out-Null
    Write-Host 'Installing the project packages. The first installation needs internet access.'
    Write-Host 'Please wait; this can take a few minutes.'
    $qaInstaller = Start-Process -FilePath $qaPython -ArgumentList @('setup.py') -WorkingDirectory $qaRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $qaLogFolder 'install.log') -RedirectStandardError (Join-Path $qaLogFolder 'install-errors.log')
    if ($qaInstaller.ExitCode -ne 0) {
        throw 'Installation did not finish. See runtime/install.log and runtime/install-errors.log, then run portable.bat again.'
    }
    & $qaEnvironmentPython (Join-Path $qaRoot 'launch.py') doctor
    if ($LASTEXITCODE -ne 0) { throw 'Some packages are still missing. Run portable.bat again.' }
    Write-Host ''
    Write-Host 'Installation complete. Double-click run.bat to choose a solution.'
    Write-Host 'When moving to a different computer, run portable.bat there once.'
}

function Run-QA([string]$Choice) {
    $qaPython = $qaEnvironmentPython
    if ($env:QA_PYTHON) { $qaPython = $env:QA_PYTHON }
    if (-not (Test-Python $qaPython)) { throw 'The QA environment is not ready. Double-click portable.bat first.' }
    $qaChoice = $Choice.Trim().ToLowerInvariant()
    if (-not $qaChoice) {
        Write-Host ''
        Write-Host 'QA - Choose a solution'
        Write-Host '  1. Open the AI dashboard'
        Write-Host '  2. Create the Excel report'
        Write-Host '  3. Open both solution presentations'
        Write-Host '  4. Check the installation'
        Write-Host '  0. Exit'
        $qaChoice = Read-Host 'Enter a number'
    }
    switch ($qaChoice) {
        { $_ -in @('1', 'ai') } {
            $qaPort = 8503
            if ($env:QA_PORT) {
                if (-not [int]::TryParse($env:QA_PORT, [ref]$qaPort) -or $qaPort -lt 1 -or $qaPort -gt 65535) {
                    throw 'QA_PORT must be a number between 1 and 65535.'
                }
            }
            & $qaPython (Join-Path $qaRoot 'launch.py') doctor | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'Run portable.bat to install the missing packages.' }
            Write-Host "Dashboard: http://localhost:$qaPort"
            Write-Host 'Keep this window open while using the dashboard. Press Ctrl+C to stop it.'
            $qaHeadless = if ($env:QA_NO_UI -eq '1') { 'true' } else { 'false' }
            Push-Location (Join-Path $qaRoot '02-modern-ai')
            try {
                & $qaPython -m streamlit run 'app.py' --server.address 127.0.0.1 --server.port $qaPort --server.headless $qaHeadless --browser.gatherUsageStats false | Out-Host
                return $LASTEXITCODE
            } finally { Pop-Location }
        }
        { $_ -in @('2', 'limited') } {
            & $qaPython (Join-Path $qaRoot 'launch.py') limited | Out-Host
            if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
            $qaDataRoot = if ($env:QA_DATA_DIR) { $env:QA_DATA_DIR } else { $qaRoot }
            $qaWorkbook = Join-Path $qaDataRoot '01-limited-tools/output/QA_Review.xlsx'
            if ($env:QA_NO_UI -ne '1') { Invoke-Item -LiteralPath $qaWorkbook }
            return 0
        }
        { $_ -in @('3', 'presentations') } {
            if ($env:QA_NO_UI -ne '1') {
                Invoke-Item -LiteralPath (Join-Path $qaRoot '01-limited-tools/presentation.html')
                Invoke-Item -LiteralPath (Join-Path $qaRoot '02-modern-ai/presentation.html')
            }
            Write-Host 'Both presentation.html files are in the solution folders.'
            return 0
        }
        { $_ -in @('4', 'check', 'doctor') } {
            & $qaPython (Join-Path $qaRoot 'launch.py') doctor | Out-Host
            return $LASTEXITCODE
        }
        'test' {
            & $qaPython (Join-Path $qaRoot 'launch.py') test | Out-Host
            return $LASTEXITCODE
        }
        { $_ -in @('0', 'exit') } { return 0 }
        default { throw 'Choose 1, 2, 3, 4 or 0. Commands: run.bat ai, limited, presentations, check or test.' }
    }
}

try {
    if ($Action -eq 'Install') { Install-QA; exit 0 }
    exit (Run-QA $Mode)
} catch {
    Write-Host ''
    Write-Host ('QA stopped: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
