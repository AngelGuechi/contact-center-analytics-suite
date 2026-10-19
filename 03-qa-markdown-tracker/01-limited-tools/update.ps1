param([switch]$NoOpen, [switch]$NoForm, [string]$InputFolder)
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path $PSScriptRoot -Parent) 'find-python.ps1')
$qaPython = Get-QAPython
$qaArguments = @((Join-Path $PSScriptRoot 'run.py'))
if ($InputFolder) { $qaArguments += @('--input', $InputFolder) }
if (-not $NoForm) { $qaArguments += '--interactive' }
& $qaPython @qaArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$qaDataRoot = if ($env:QA_DATA_DIR) { $env:QA_DATA_DIR } else { Split-Path $PSScriptRoot -Parent }
$qaWorkbook = Join-Path $qaDataRoot '01-limited-tools/output/QA_Review.xlsx'
if ((-not $NoOpen) -and (Test-Path -LiteralPath $qaWorkbook)) { Invoke-Item -LiteralPath $qaWorkbook }
