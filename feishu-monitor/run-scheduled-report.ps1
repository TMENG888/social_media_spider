[CmdletBinding()]
param([switch]$Preview)
$ErrorActionPreference = 'Stop'
$monitorRoot = $PSScriptRoot
$startedAt = [DateTimeOffset]::Now
$runId = $startedAt.ToString('yyyyMMdd-HHmmss-fff') + '-' + $PID
$logRoot = Join-Path $monitorRoot 'output\scheduler'
$record = [ordered]@{
    schemaVersion = 1; runId = $runId; startedAt = $startedAt.ToString('o')
    finishedAt = $null; status = 'running'; preview = [bool]$Preview
    exitCode = $null; childExitCode = $null; deliveryConfirmed = $false
    archiveConfirmed = $false; cloudConfirmed = $false; reportId = $null; errorType = $null
}
function Save-SchedulerRecord {
    [IO.Directory]::CreateDirectory($logRoot) | Out-Null
    $json = $record | ConvertTo-Json -Depth 5
    foreach ($name in @(($runId + '.json'), 'latest-run.json')) {
        $target = Join-Path $logRoot $name
        [IO.File]::WriteAllText($target + '.tmp', $json, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath ($target + '.tmp') -Destination $target -Force
    }
}
$exitCode = 1
try {
    Save-SchedulerRecord
    $entry = Join-Path $monitorRoot 'run-once.ps1'
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'Monitor entry missing.' }
    $processInfo = New-Object Diagnostics.ProcessStartInfo
    $processInfo.FileName = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $processInfo.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $entry + '"'
    if (-not $Preview) { $processInfo.Arguments += ' -Send' }
    $processInfo.WorkingDirectory = $monitorRoot
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $processInfo
    try {
        if (-not $process.Start()) { throw 'Monitor process did not start.' }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $null = $stderrTask.GetAwaiter().GetResult()
        $record.childExitCode = $process.ExitCode
    } finally { $process.Dispose() }
    # Do not persist raw process output: an unexpected exception could contain credentials.
    $record.deliveryConfirmed = $stdout -match '(?m)^Feishu delivery confirmed\s*$'
    $archiveMarker = $stdout -match '(?m)^Confirmed report archived locally;'
    if ($Preview) {
        if ($record.childExitCode -ne 0) { throw 'Monitor process failed.' }
        if ($stdout -notmatch 'Preview generated; no message sent') { throw 'Preview was not confirmed.' }
        $record.status = 'preview_verified'
    } else {
        if (-not $record.deliveryConfirmed -or -not $archiveMarker) { throw 'Delivery or archive confirmation missing.' }
        $deliveryState = Get-Content -LiteralPath (Join-Path $monitorRoot 'output\delivery-state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $deliveredAt = [DateTimeOffset]::FromUnixTimeSeconds([long]$deliveryState.deliveredAt)
        if ($deliveredAt.ToUnixTimeSeconds() -lt $startedAt.ToUnixTimeSeconds()) { throw 'Delivery state predates this run.' }
        $dayFolder = $deliveredAt.ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd')
        $historyRoot = Join-Path $monitorRoot ('output\report-history\' + $dayFolder)
        foreach ($file in @(Get-ChildItem -LiteralPath $historyRoot -Filter ($deliveryState.deliveredAt.ToString() + '-*.json') -File)) {
            $entryRecord = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($entryRecord.deliveryConfirmed -eq $true -and $entryRecord.confirmationProvenance -eq 'live_ack' -and
                [DateTimeOffset]::Parse($entryRecord.deliveredAt).ToUnixTimeSeconds() -eq $deliveredAt.ToUnixTimeSeconds() -and
                [DateTimeOffset]::Parse($entryRecord.generatedAt).ToUnixTimeSeconds() -ge $startedAt.ToUnixTimeSeconds()) {
                $record.archiveConfirmed = $true
                $record.reportId = $entryRecord.reportId
                break
            }
        }
        if (-not $record.archiveConfirmed) { throw 'This run has no matching confirmed archive.' }
        $cloudStatePath = Join-Path $monitorRoot 'output\cloud-sync\latest-run.json'
        if (Test-Path -LiteralPath $cloudStatePath) {
            $cloudState = Get-Content -LiteralPath $cloudStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $record.cloudConfirmed = $cloudState.cloudConfirmed -eq $true -and
                [DateTimeOffset]::Parse($cloudState.startedAt) -ge $startedAt -and
                $record.reportId -in @($cloudState.reportIds)
        }
        if ($record.childExitCode -ne 0 -or -not $record.cloudConfirmed) {
            throw 'Group delivery/archive confirmed, but cloud synchronization NOT confirmed.'
        }
        $record.status = 'success'
    }
    $exitCode = 0
} catch {
    $record.status = 'failed'
    $record.errorType = $_.Exception.GetType().Name
} finally {
    $record.exitCode = $exitCode
    $record.finishedAt = [DateTimeOffset]::Now.ToString('o')
    try { Save-SchedulerRecord } catch { $exitCode = 1 }
}
if ($exitCode -eq 0) { Write-Host ('Scheduled report verified: ' + $record.status) }
else { Write-Error 'Scheduled report verification failed; inspect output\scheduler\latest-run.json.' -ErrorAction Continue }
exit $exitCode
