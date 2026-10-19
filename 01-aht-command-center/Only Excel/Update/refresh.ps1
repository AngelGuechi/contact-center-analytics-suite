param(
    [string]$WorkbookPath = (Join-Path $PSScriptRoot '..\AHT_Review.xlsx'),
    [switch]$MoveUpdates,
    [switch]$UseToday,
    [switch]$PromptForIntervals
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
function Get-HistoryTarget {
    param([string]$HistoryRoot, [string]$FileName)
    if ($FileName -notmatch '^Calls_(\d{4}-\d{2}-\d{2})_\d{4}_\d{4}-\d{2}-\d{2}_\d{4}_r\d+\.xlsx$') { throw "Invalid interval filename: $FileName" }
    $day = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
    $root = [System.IO.Path]::GetFullPath($HistoryRoot)
    $folder = Join-Path $root ($day.ToString('yyyy'))
    $folder = Join-Path $folder ($day.ToString('MM'))
    $folder = [System.IO.Path]::GetFullPath((Join-Path $folder ($day.ToString('dd'))))
    if (-not $folder.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected History target path.' }
    return (Join-Path $folder $FileName)
}
$path = [System.IO.Path]::GetFullPath($WorkbookPath)
if (-not (Test-Path $path)) { throw "Workbook not found: $path" }
$excel = $null
$wb = $null
$timer = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $wb = $excel.Workbooks.Open($path)
    if ($wb.ReadOnly) { throw "Workbook is already open for editing: $path. Close it before refreshing." }
    $packageRoot = [System.IO.Path]::GetFullPath((Split-Path -Path $path -Parent)).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $settings = $wb.Worksheets.Item('Settings')
    if ([string]$settings.Range('B7').Value2 -eq 'LocalFolder') {
        # CELL("filename") resolves beside the saved workbook after a Git clone or folder move.
        $sourceFormula = '=LEFT(CELL("filename",Settings!$A$1),FIND("[",CELL("filename",Settings!$A$1))-1)'
        if ([string]$settings.Range('B6').Formula -ne $sourceFormula) { $settings.Range('B6').Formula = $sourceFormula }
        $excel.CalculateFullRebuild()
        $calculatedRoot = [string]$settings.Range('B6').Value2
        if ([string]::IsNullOrWhiteSpace($calculatedRoot) -or [System.IO.Path]::GetFullPath($calculatedRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar) -ne $packageRoot) {
            throw "Workbook source folder did not resolve beside the workbook: $calculatedRoot"
        }
    }
    if ($UseToday) {
        $wb.Worksheets.Item('Settings').Range('B4').Formula = '=TODAY()'
        $excel.CalculateFull()
    }
    $pending = @()
    $historyPath = $null
    if ($MoveUpdates) {
        if ([string]$settings.Range('B7').Value2 -ne 'LocalFolder') { throw 'Automatic file movement requires LocalFolder source mode.' }
        $sourceRoot = $packageRoot
        $updatePath = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot 'Update'))
        $historyPath = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot 'History'))
        $separator = [System.IO.Path]::DirectorySeparatorChar
        if (-not $updatePath.StartsWith($sourceRoot + $separator, [System.StringComparison]::OrdinalIgnoreCase) -or -not $historyPath.StartsWith($sourceRoot + $separator, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected update or history path.' }
        if (-not (Test-Path -LiteralPath $updatePath -PathType Container) -or -not (Test-Path -LiteralPath $historyPath -PathType Container)) { throw 'Update and History folders are required.' }
        $filePattern = '^Calls_(\d{4}-\d{2}-\d{2})_(\d{4})_(\d{4}-\d{2}-\d{2})_(\d{4})_r\d+\.xlsx$'
        $pending = @(Get-ChildItem -LiteralPath $updatePath -File -Filter '*.xlsx' | Where-Object { -not $_.Name.StartsWith('~$') })
        $historyFiles = @(Get-ChildItem -LiteralPath $historyPath -Recurse -File -Filter 'Calls_*.xlsx')
        $historyNames = @{}
        foreach ($historyFile in $historyFiles) {
            if ($historyNames.ContainsKey($historyFile.Name)) { throw "Duplicate filename in History: $($historyFile.Name)" }
            $historyNames[$historyFile.Name] = $true
        }
        foreach ($file in $pending) {
            if ($file.Name -match $filePattern) { continue }
            if (-not $PromptForIntervals) { throw "Invalid download filename in Update: $($file.Name)" }
            Write-Host "New download: $($file.Name)"
            $startText = Read-Host 'Interval start (YYYY-MM-DD HH:MM)'
            $endText = Read-Host 'Interval end (YYYY-MM-DD HH:MM)'
            $start = [datetime]::MinValue
            $end = [datetime]::MinValue
            $format = 'yyyy-MM-dd HH:mm'
            if (-not [datetime]::TryParseExact($startText, $format, [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$start) -or -not [datetime]::TryParseExact($endText, $format, [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$end)) { throw "Enter both interval times as YYYY-MM-DD HH:MM for $($file.Name)" }
            if ($end -le $start) { throw "Interval end must be later than start for $($file.Name)" }
            $window = 'Calls_{0}_{1}_{2}_{3}' -f $start.ToString('yyyy-MM-dd'),$start.ToString('HHmm'),$end.ToString('yyyy-MM-dd'),$end.ToString('HHmm')
            $revision = 1
            do {
                $newName = '{0}_r{1:00}.xlsx' -f $window,$revision
                $revision++
            } while ((Test-Path -LiteralPath (Join-Path $updatePath $newName)) -or $historyNames.ContainsKey($newName))
            Rename-Item -LiteralPath $file.FullName -NewName $newName
            Write-Host "Named $newName"
        }
        $pending = @(Get-ChildItem -LiteralPath $updatePath -File -Filter '*.xlsx' | Where-Object { -not $_.Name.StartsWith('~$') })
        $closedMonths = @{}
        foreach ($file in $historyFiles) {
            if ($file.Name -match $filePattern) {
                $first = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
                $last = [datetime]::ParseExact($Matches[3], 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
                if ($first.Day -eq 1 -and $Matches[2] -eq '0000' -and $Matches[4] -eq '0000' -and $last -eq $first.AddMonths(1)) { $closedMonths[$first.ToString('yyyy-MM')] = $true }
            }
        }
        foreach ($file in $pending) {
            if ($file.Name -notmatch $filePattern) { throw "Invalid download filename in Update: $($file.Name)" }
            if ($closedMonths.ContainsKey($Matches[1].Substring(0,7))) { throw "The month is already consolidated in History. Review this correction first: $($file.Name)" }
            if ($historyNames.ContainsKey($file.Name) -or (Test-Path -LiteralPath (Get-HistoryTarget -HistoryRoot $historyPath -FileName $file.Name))) { throw "History already contains this filename: $($file.Name). Use a higher revision for a correction." }
        }
    }
    foreach ($pair in @(
        @('Data Quality', 'tblCoverage'),
        @('Daily Data', 'tblDaily'),
        @('Command Center', 'tblAgentRanking'),
        @('Command Center', 'tblSupervisorRanking'),
        @('Data Quality', 'tblQuality')
    )) {
        $name = $pair[1]
        $table = $wb.Worksheets.Item($pair[0]).ListObjects.Item($name)
        if (-not $table.QueryTable.Refresh($false)) { throw "Refresh failed: $name" }
    }
    $history = $null
    try { $history = $wb.Worksheets.Item('Daily History').ListObjects.Item('tblHistory') } catch {}
    if ($history -ne $null) {
        $history.QueryTable.RefreshStyle = 0
        if (-not $history.QueryTable.Refresh($false)) { throw 'Refresh failed: tblHistory' }
        $historySheet = $wb.Worksheets.Item('Daily History')
        $historySheet.Range('A2:Z5').ClearContents()
        $historySheet.Range('A2').Value2 = 'AHT history'
        $historySheet.Range('A3').Value2 = 'Daily site totals from accepted calls. Filter the table to find any loaded date.'
        $historySheet.Range('A5').Value2 = 'Daily trend and history'
        $historySheet.Range('A2').Font.Size = 16
        $historySheet.Range('A2').Font.Bold = $true
        $historySheet.Range('A5:N5').Interior.Color = [System.Drawing.ColorTranslator]::ToOle([System.Drawing.ColorTranslator]::FromHtml('#17283F'))
        $historySheet.Range('A5:N5').Font.Color = [System.Drawing.ColorTranslator]::ToOle([System.Drawing.ColorTranslator]::FromHtml('#FFFFFF'))
        $historySheet.Range('A5:N5').Font.Bold = $true
        $historySheet.Range('I7:Z7').ClearContents()
        $historySheet.Range('I7').Value2 = 'Loaded days only. Older source files remain in SharePoint.'
        $historySheet.Range('A8:A1000').NumberFormat = 'mmm d, yyyy'
        $historySheet.Range('B8:F1000').NumberFormat = '#,##0'
        $historySheet.Range('G8:H1000').NumberFormat = '#,##0.0'
    }
    $pivot = $wb.Worksheets.Item('Explorer').PivotTables('AHTExplorer')
    if (-not $pivot.RefreshTable()) { throw 'Pivot refresh failed' }
    $overview = $wb.Worksheets.Item('Overview')
    $agentColumns = @{ A='AgentName'; B='AgentId'; C='Supervisor'; D='TodayCalls'; E='AHT Today'; F='Selected Gap'; G='Low Sample' }
    $supervisorColumns = @{ I='Supervisor'; J='TodayCalls'; K='AHT Today'; L='Selected Gap'; M='AHT MTD'; N='MTDCalls' }
    foreach ($row in 17..24) {
        $agentRank = 'ROWS($A$17:A{0})' -f $row
        $supervisorRank = 'ROWS($I$17:I{0})' -f $row
        foreach ($column in $agentColumns.Keys) {
            $source = 'tblAgentRanking[{0}]' -f $agentColumns[$column]
            $overview.Range("$column$row").Formula = '=IFERROR(INDEX({0},{1}),"")' -f $source,$agentRank
        }
        foreach ($column in $supervisorColumns.Keys) {
            $source = 'tblSupervisorRanking[{0}]' -f $supervisorColumns[$column]
            $overview.Range("$column$row").Formula = '=IFERROR(INDEX({0},{1}),"")' -f $source,$supervisorRank
        }
    }
    $excel.CalculateFull()
    $dq = $wb.Worksheets.Item('Data Quality')
    if ([math]::Abs([double]$dq.Range('B6').Value2) -gt 0.00001) { throw 'Component reconciliation failed' }
    $calls = [double]$dq.Range('B5').Value2
    if ($history -ne $null) {
        $historyCalls = [double]$excel.WorksheetFunction.Sum($history.ListColumns.Item('Calls').DataBodyRange)
        if ([math]::Abs($historyCalls - $calls) -gt 0.00001) { throw 'History call count does not reconcile to Daily Data' }
    }
    $site = $wb.Worksheets.Item('Command Center')
    $periodCalls = [double]$site.Range('B4').Value2 + [double]$site.Range('F4').Value2
    if ($periodCalls -gt $calls) { throw 'Period calls exceed accepted total' }
    foreach ($file in $pending) {
        $target = Get-HistoryTarget -HistoryRoot $historyPath -FileName $file.Name
        $folder = Split-Path -Path $target -Parent
        if (-not (Test-Path -LiteralPath $folder -PathType Container)) { New-Item -ItemType Directory -Path $folder -Force | Out-Null }
        Move-Item -LiteralPath $file.FullName -Destination $target
    }
    $wb.Save()
    $timer.Stop()
    Write-Output ('REFRESH_OK path={0} calls={1} moved={2} seconds={3}' -f $path,$calls,$pending.Count,[math]::Round($timer.Elapsed.TotalSeconds,1))
} catch {
    Write-Error ('REFRESH_FAILED: ' + $_.Exception.Message)
    throw
} finally {
    if ($wb -ne $null) { try { $wb.Close($false) } catch {} }
    if ($excel -ne $null) { try { $excel.Quit() } catch {} }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
