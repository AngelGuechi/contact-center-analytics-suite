. (Join-Path $PSScriptRoot '../find-python.ps1')
$qaPython = Get-QAPython -Modules @('openpyxl','streamlit','pandas','requests')
Write-Host 'QA workspace: http://127.0.0.1:8503'
Push-Location $PSScriptRoot
try {
    & $qaPython -m streamlit run 'app.py' --server.address 127.0.0.1 --server.port 8503 --server.headless true --browser.gatherUsageStats false
    $qaExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $qaExitCode
