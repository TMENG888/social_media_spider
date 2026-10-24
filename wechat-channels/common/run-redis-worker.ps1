param([switch]$Once)

$ErrorActionPreference = 'Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $Common '..')).Path.TrimEnd('\')
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) { (Resolve-Path $env:WECHAT_WORKER_ROOT).Path.TrimEnd('\') } else { $Root }
$WorkerId = Split-Path $WorkerRoot -Leaf
$Python = if ($env:WECHAT_PYTHON) { $env:WECHAT_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }

# Ask once before the Redis loop. Every claimed task inherits the same display
# calibration and credentials, so long-running workers do not repeatedly stop
# for console input.
if (-not $env:WECHAT_DISPLAY_PROFILE) {
  Write-Host 'Select primary display profile:'
  Write-Host '  1 = 2560x1440'
  Write-Host '  2 = 1920x1080'
  Write-Host '  0 = Cancel'
  $choice = Read-Host 'Display profile (1/2/0)'
  if ($choice -eq '1') { $env:WECHAT_DISPLAY_PROFILE = '2560x1440' }
  elseif ($choice -eq '2') { $env:WECHAT_DISPLAY_PROFILE = '1920x1080' }
  else { exit 10 }
}

if (-not $env:REDIS_URL) { $env:REDIS_URL = Read-Host 'Redis URL (example: redis://127.0.0.1:6379/0)' }
if (-not $env:REDIS_URL) { throw 'REDIS_URL is required.' }
if (-not $env:REDIS_PASSWORD) {
  $redisCredentialFile = Join-Path $WorkerRoot '.credentials\redis-password.txt'
  if (Test-Path -LiteralPath $redisCredentialFile) {
    $redisCredentialValue = (Get-Content -LiteralPath $redisCredentialFile -Raw -Encoding UTF8).Trim()
    if ($redisCredentialValue) {
      $env:REDIS_PASSWORD = $redisCredentialValue
      Write-Host "Redis credential loaded from the worker credential file."
    }
  }
}
if (-not $env:REDIS_PASSWORD) {
  $redisSecure = Read-Host 'Redis password (press Enter when Redis has no password)' -AsSecureString
  $redisPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($redisSecure)
  try { $env:REDIS_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($redisPtr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($redisPtr) }
}
if (-not $env:REDIS_RUN_ID) { $env:REDIS_RUN_ID = '20260926-prod-01' }
if (-not $env:REDIS_WORKER_ROLE) {
  # Every physical node owns an independent WeChat UI.  Let all three nodes
  # claim annual keyword scans as well as exact-video retries; Redis leases keep
  # one keyword on one node. Task priority below gates new keywords until
  # the retry backlog is resolved; primary-burst applies to balanced only.
  $env:REDIS_WORKER_ROLE = 'mixed'
}
if (-not $env:REDIS_PRIMARY_BURST) { $env:REDIS_PRIMARY_BURST = '1' }
if (-not $env:REDIS_TASK_PRIORITY) { $env:REDIS_TASK_PRIORITY = 'retry_first' }

if (-not $env:MYSQL_ENABLED) { $env:MYSQL_ENABLED = '1' }
if ($env:MYSQL_ENABLED -ne '0') {
  $mysqlDefaults = Get-Content -LiteralPath (Join-Path $Common 'src\mysql-defaults.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $env:MYSQL_HOST) { $env:MYSQL_HOST = [string]$mysqlDefaults.host }
  if (-not $env:MYSQL_PORT) { $env:MYSQL_PORT = [string]$mysqlDefaults.port }
  if (-not $env:MYSQL_DATABASE) { $env:MYSQL_DATABASE = [string]$mysqlDefaults.database }
  if (-not $env:MYSQL_USER) { $env:MYSQL_USER = Read-Host 'MySQL username' }
  if (-not $env:MYSQL_PASSWORD) {
    $mysqlSecure = Read-Host 'MySQL password' -AsSecureString
    $mysqlPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($mysqlSecure)
    try { $env:MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($mysqlPtr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($mysqlPtr) }
  }
}

$Queue = if ($env:WECHAT_QUEUE_FILE) {
  (Resolve-Path $env:WECHAT_QUEUE_FILE -ErrorAction Stop).Path
} else {
  Join-Path $Common 'task-queue.json'
}
Write-Host "Redis task queue: $Queue"
$Scheduler = Join-Path $Common 'src\redis_task_queue.py'
$LogDirectory = Join-Path $WorkerRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$LogPath = Join-Path $LogDirectory ("channels-redis-worker-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))
$ExitCode = 1
$TranscriptStarted = $false

try {
  Start-Transcript -LiteralPath $LogPath -Append -Force | Out-Null
  $TranscriptStarted = $true
  Write-Host ('=' * 72)
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] Redis Channels worker started"
  Write-Host "Worker: $WorkerId"
  Write-Host "Computer: $env:COMPUTERNAME"
  Write-Host "RunId: $env:REDIS_RUN_ID"
  Write-Host "WorkerRole: $env:REDIS_WORKER_ROLE (primary burst: $env:REDIS_PRIMARY_BURST)"
  Write-Host "TaskPriority: $env:REDIS_TASK_PRIORITY"
  Write-Host "Redis: $env:REDIS_URL"
  Write-Host "DisplayProfile: $env:WECHAT_DISPLAY_PROFILE"
  Write-Host "DatabaseEnabled: $($env:MYSQL_ENABLED -ne '0')"
  $quantityPolicy=Get-Content -LiteralPath (Join-Path $Common 'acceptance-policy.json') -Raw -Encoding UTF8 -ErrorAction SilentlyContinue | ConvertFrom-Json
  $quantityEnabled=$quantityPolicy.enabled -eq $true -and $quantityPolicy.policy -eq '20261015-keyword-count-p80-v1' -and $quantityPolicy.population -eq 'nonzero_keywords'
  $env:SOCIAL_VOLUME_ENABLED=if($quantityEnabled){'1'}else{'0'}
  if($quantityEnabled){
    Write-Host 'Quantity acceptance: audio is optional; required runtime checks run before claiming any original task.'
  }else{
    Write-Host 'Checking/downloading and loading ASR model before claiming Redis tasks...'
    & $Python (Join-Path $Common 'src\asr_model_preflight.py') (Join-Path $Common 'collector_config.json')
    if ($LASTEXITCODE -ne 0) { throw 'ASR model preflight failed. No Redis task has been claimed; fix model/network and restart.' }
  }
  $arguments = @(
    $Scheduler, 'run', '--queue', $Queue, '--common', $Common,
    '--worker-root', $WorkerRoot, '--redis-url', $env:REDIS_URL,
    '--run-id', $env:REDIS_RUN_ID,
    '--worker-role', $env:REDIS_WORKER_ROLE,
    '--primary-burst', $env:REDIS_PRIMARY_BURST,
    '--task-priority', $env:REDIS_TASK_PRIORITY
  )
  if ($Once) { $arguments += '--once' }
  & $Python @arguments
  $ExitCode = $LASTEXITCODE
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  $ExitCode = 1
} finally {
  # Always record the launcher result inside the transcript. A zero exit only
  # certifies this scheduling pass, not completion of the entire task pool.
  Write-Host ('[Redis worker exit] ' + (@{
    event = 'redis_worker_launcher_exit'
    workerId = $WorkerId
    exitCode = $ExitCode
    allKeywordsComplete = $false
    checkedAt = (Get-Date).ToString('o')
    statusFile = (Join-Path $WorkerRoot '.state\redis_worker_status.json')
  } | ConvertTo-Json -Compress))
  if ($TranscriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
}

Write-Host "Redis worker log: $LogPath"
exit $ExitCode
