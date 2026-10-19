function Get-QAPython {
    param([string[]]$Modules = @('openpyxl'))
    $qaCandidates = @()
    if ($env:QA_PYTHON) { $qaCandidates += $env:QA_PYTHON }
    $qaCandidates += Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $qaCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($qaCommand) { $qaCandidates += $qaCommand.Source }
    $qaLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($qaLauncher) {
        $qaResolved = & $qaLauncher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) { $qaCandidates += $qaResolved }
    }
    $qaImports = 'import sys; assert sys.version_info >= (3, 11); import tzdata; import ' + ($Modules -join ',')
    foreach ($qaCandidate in $qaCandidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $qaCandidate) {
            & $qaCandidate -c $qaImports 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $qaCandidate }
        }
    }
    throw 'Install Python and the packages in requirements.txt, or set QA_PYTHON to your Python executable.'
}
