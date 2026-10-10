[CmdletBinding()]
param([ValidateSet('run','retry','check')][string]$Mode)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Node = Join-Path $Root 'runtime\node\node.exe'
$Browsers = Join-Path $Root 'runtime\browsers'
$BrowserExecutable = Join-Path $Browsers 'chrome-win64\chrome.exe'
$TasksRoot = Join-Path $Root 'tasks'
$QueueFile = Join-Path $TasksRoot 'task-queue.json'

try {
    if (-not (Test-Path -LiteralPath $Node)) { throw "Portable Node is missing: $Node" }
    if (-not (Test-Path -LiteralPath $BrowserExecutable)) { throw "Portable Chromium is missing: $BrowserExecutable" }
    $QueueItems = @()
    if (Test-Path -LiteralPath $QueueFile) {
        $queueConfig = Get-Content -LiteralPath $QueueFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $QueueItems = @($queueConfig.tasks)
        if ($QueueItems.Count -lt 1) { throw 'Task queue contains no tasks.' }
    }
    else {
        $taskFiles = @(Get-ChildItem -LiteralPath $TasksRoot -Filter '*.json' -File)
        if ($taskFiles.Count -ne 1) { throw "Without task-queue.json, the tasks folder must contain exactly one JSON file; found $($taskFiles.Count)." }
        $QueueItems = @([pscustomobject]@{
            name = 'Default task'
            taskFile = $taskFiles[0].FullName
            outputDir = 'runs\current'
            stateDir = '.state\current'
            transitionDelaySeconds = 0
        })
    }

    $ResolvedQueue = @()
    foreach ($item in $QueueItems) {
        $taskPath = if ([IO.Path]::IsPathRooted([string]$item.taskFile)) { [string]$item.taskFile } else { Join-Path $Root ([string]$item.taskFile) }
        $taskPath = [IO.Path]::GetFullPath($taskPath)
        if (-not (Test-Path -LiteralPath $taskPath -PathType Leaf)) { throw "Task file is missing: $taskPath" }
        $outputPath = Join-Path $Root ([string]$item.outputDir)
        $statePath = Join-Path $Root ([string]$item.stateDir)
        $ResolvedQueue += [pscustomobject]@{
            name = [string]$item.name
            taskFile = $taskPath
            outputDir = $outputPath
            stateDir = $statePath
            transitionDelaySeconds = [math]::Max(0, [int]$item.transitionDelaySeconds)
        }
    }

    $env:PLAYWRIGHT_BROWSERS_PATH = $Browsers
    $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = '1'
    $env:BROWSER_EXECUTABLE = $BrowserExecutable
    Set-Location -LiteralPath $Root

    if (-not $Mode) {
        Write-Host ''
        Write-Host 'Baidu News portable worker'
        Write-Host '1. Start or continue this worker, then import into MySQL'
        Write-Host '2. Retry failed/incomplete tasks, then import into MySQL'
        Write-Host '3. Check portable runtime only'
        $choice = Read-Host 'Select 1 / 2 / 3'
        $Mode = switch ($choice) { '1' {'run'} '2' {'retry'} '3' {'check'} default { throw 'Invalid option.' } }
    }

    if ($Mode -eq 'check') {
        & $Node 'src\portable-check.mjs'
        if ($LASTEXITCODE -ne 0) { throw "Runtime check failed with exit code $LASTEXITCODE." }
        Write-Host 'Runtime check passed.'
        exit 0
    }

    $dbUser = Read-Host 'MySQL user'
    if ([string]::IsNullOrWhiteSpace($dbUser)) { throw 'MySQL user cannot be empty.' }
    $securePassword = Read-Host 'MySQL password (hidden and never saved)' -AsSecureString
    $passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $env:MYSQL_USER = $dbUser.Trim()
        $env:MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
        if ([string]::IsNullOrWhiteSpace($env:MYSQL_PASSWORD)) { throw 'MySQL password cannot be empty.' }
    }
    finally {
        if ($passwordPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr) }
    }
    & $Node 'src\check-mysql.mjs'
    if ($LASTEXITCODE -ne 0) { throw "MySQL connection check failed with exit code $LASTEXITCODE." }

    $queueStatusPath = Join-Path $Root 'runs\task_queue_status.json'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $queueStatusPath) | Out-Null
    $queueResults = @()
    $hadFailure = $false
    for ($queueIndex = 0; $queueIndex -lt $ResolvedQueue.Count; $queueIndex++) {
        $item = $ResolvedQueue[$queueIndex]
        Write-Host ''
        Write-Host ("[Queue {0}/{1}] {2}" -f ($queueIndex + 1), $ResolvedQueue.Count, $item.name)
        New-Item -ItemType Directory -Force -Path $item.outputDir, $item.stateDir | Out-Null
        $startedAt = [DateTimeOffset]::Now.ToString('o')
        $crawlArgs = @(
            'src\run-batch.mjs', '--keywords-json', $item.taskFile,
            '--output-dir', $item.outputDir, '--state-dir', $item.stateDir, '--skip-excel', '--import-each-keyword'
        )
        if ($Mode -eq 'retry') { $crawlArgs += '--resume-failed' }
        & $Node @crawlArgs
        $itemExitCode = $LASTEXITCODE
        $queueResults += [pscustomobject]@{
            name = $item.name
            taskFile = $item.taskFile
            outputDir = $item.outputDir
            stateDir = $item.stateDir
            startedAt = $startedAt
            finishedAt = [DateTimeOffset]::Now.ToString('o')
            exitCode = $itemExitCode
            status = if ($itemExitCode -eq 0) { 'completed' } elseif ($itemExitCode -eq 130) { 'interrupted' } else { 'failed_but_preserved' }
        }
        [pscustomobject]@{
            updatedAt = [DateTimeOffset]::Now.ToString('o')
            mode = $Mode
            queueCount = $ResolvedQueue.Count
            completedItems = @($queueResults)
        } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $queueStatusPath -Encoding UTF8

        if ($itemExitCode -eq 130) { throw 'Worker was interrupted; all checkpoints were preserved.' }
        if ($itemExitCode -ne 0) {
            $hadFailure = $true
            Write-Host ("Task set failed with exit code {0}; checkpoints were preserved and the queue will continue." -f $itemExitCode) -ForegroundColor Yellow
        }
        if ($queueIndex -lt $ResolvedQueue.Count - 1 -and $item.transitionDelaySeconds -gt 0) {
            Write-Host ("Task-set transition cooldown: {0} seconds." -f $item.transitionDelaySeconds)
            Start-Sleep -Seconds $item.transitionDelaySeconds
        }
    }

    if ($hadFailure) { throw "Task queue finished, but one or more task sets failed. Review $queueStatusPath and use retry mode." }
    Write-Host "Task queue completed. Status: $queueStatusPath"
}
catch {
    Write-Host ''
    Write-Host ("FAILED: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
finally {
    Remove-Item Env:MYSQL_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:MYSQL_USER -ErrorAction SilentlyContinue
}
