param([ValidateSet('run','retry','check')][string]$Mode='run')
$ErrorActionPreference = 'Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Common 'worker-recovery.ps1')
$Root = Resolve-Path (Join-Path $Common '..')
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) { Resolve-Path $env:WECHAT_WORKER_ROOT } else { $Root }
# A primary visit captures metadata/comments and the complete audio in the same
# detail-page session.  Whisper runs in the background through the scheduler's
# persistent model service; only failed/incomplete videos enter video-retry.
$env:WECHAT_CLIENT_ASR = '1'
function Write-JsonAtomic([object]$Value, [string]$Path, [int]$Depth = 10) {
  $directory = Split-Path -Parent $Path
  if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
  $temporary = "$Path.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
  $backup = "$Path.bak.$PID.$([Guid]::NewGuid().ToString('N'))"
  $encoding = New-Object System.Text.UTF8Encoding($false)
  try {
    [System.IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth $Depth), $encoding)
    if (Test-Path -LiteralPath $Path) {
      [System.IO.File]::Replace($temporary, $Path, $backup, $true)
    } else {
      [System.IO.File]::Move($temporary, $Path)
    }
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
  }
}
function Read-JsonSafe([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
  catch {
    Write-Host "Ignoring interrupted/corrupt status JSON; SQLite remains authoritative: $Path" -ForegroundColor Yellow
    return $null
  }
}
function Get-StatusEvidenceHash([string]$Path) {
  # Do not depend on optional PowerShell modules in the portable runtime.
  $evidenceStream = [System.IO.File]::OpenRead($Path)
  $evidenceAlgorithm = [System.Security.Cryptography.SHA256]::Create()
  try { return [System.BitConverter]::ToString($evidenceAlgorithm.ComputeHash($evidenceStream)).Replace('-', '') }
  finally { $evidenceAlgorithm.Dispose(); $evidenceStream.Dispose() }
}
if ($Mode -eq 'check') { & (Join-Path $Common 'check-env.ps1'); exit $LASTEXITCODE }
$dbEnabled = $env:MYSQL_ENABLED -ne '0'
if ($dbEnabled) {
  $mysqlDefaults = Get-Content -LiteralPath (Join-Path $Common 'src\mysql-defaults.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $env:MYSQL_HOST) { $env:MYSQL_HOST = [string]$mysqlDefaults.host }
  if (-not $env:MYSQL_PORT) { $env:MYSQL_PORT = [string]$mysqlDefaults.port }
  if (-not $env:MYSQL_DATABASE) { $env:MYSQL_DATABASE = [string]$mysqlDefaults.database }
  if (-not $env:MYSQL_USER) { $env:MYSQL_USER = Read-Host 'MySQL username' }
  if (-not $env:MYSQL_PASSWORD) {
    $securePassword = Read-Host 'MySQL password' -AsSecureString
    $passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try { $env:MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr) }
  }
  if (-not $env:MYSQL_USER -or -not $env:MYSQL_PASSWORD) { throw 'MySQL username and password are required.' }
}
# Do not rely on the caller's stale $LASTEXITCODE after a PowerShell script.
# Parse the check result explicitly so double-click launches cannot exit silently.
$checkJson = (& (Join-Path $Common 'check-env.ps1') | Out-String)
try { $checkResult = $checkJson | ConvertFrom-Json } catch { throw "Environment check did not return JSON: $checkJson" }
if (-not $checkResult.ok) {
  Write-Host 'Environment check failed:' -ForegroundColor Red
  foreach ($failedCheck in @($checkResult.checks | Where-Object {-not $_.ok})) {
    Write-Host "  - $($failedCheck.name): $($failedCheck.detail)" -ForegroundColor Red
  }
  throw "Environment check failed. See $WorkerRoot\.state\environment_check.json"
}
$node = if ($env:WECHAT_NODE) { $env:WECHAT_NODE } else { (Get-Command node -ErrorAction Stop).Source }
$python = if ($env:WECHAT_PYTHON) { $env:WECHAT_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
Write-Host 'Environment check passed.'
if ($dbEnabled) {
  Write-Host 'Testing MySQL connection, credentials, database, and target tables...'
  $mysqlCheck = Join-Path $Root 'common\src\mysql-check.mjs'
  $mysqlCheckStatus = Join-Path $WorkerRoot '.state\mysql_connection_check.json'
  & $node $mysqlCheck --status $mysqlCheckStatus
  if ($LASTEXITCODE -ne 0) { throw "MySQL preflight failed. See $mysqlCheckStatus" }
  Write-Host 'MySQL preflight passed.' -ForegroundColor Green
}
Write-Host "Starting $Mode for $(Split-Path $WorkerRoot -Leaf)..."
$queueFile = if ($env:WECHAT_QUEUE_FILE) {
  (Resolve-Path $env:WECHAT_QUEUE_FILE -ErrorAction Stop).Path
} else {
  Join-Path $WorkerRoot 'task-queue.json'
}
if (-not (Test-Path $queueFile)) { $queueFile = Join-Path $Root 'common\task-queue.json' }
Write-Host "Task queue: $queueFile"
$queue = Get-Content $queueFile -Raw -Encoding UTF8 | ConvertFrom-Json
$configuredMaxResults = if ($queue.PSObject.Properties.Name -contains 'maxResultsPerKeyword') { [int]$queue.maxResultsPerKeyword } else { 0 }
# Production collection must cover the complete date window. Legacy worker
# packages used 100 here as a per-keyword cap, which produced partial_limit at
# article 100 even when the list was still months above the cutoff. Keep the
# setting readable for diagnostics, but never apply a positive hard cap.
$effectiveMaxResults = 0
if ($configuredMaxResults -gt 0) {
  Write-Host "Legacy maxResultsPerKeyword=$configuredMaxResults ignored; collection will continue until cutoff/exhaustion/stop." -ForegroundColor Yellow
}
$config = Join-Path $Root 'common\collector_config.json'
$collectorSettings = Get-Content $config -Raw -Encoding UTF8 | ConvertFrom-Json
$keywordRetryAttempts = if ($collectorSettings.PSObject.Properties.Name -contains 'keyword_retry_attempts') { [Math]::Max(1, [int]$collectorSettings.keyword_retry_attempts) } else { 1 }
$keywordRetryBackoffSeconds = if ($collectorSettings.PSObject.Properties.Name -contains 'keyword_retry_backoff_seconds') { [Math]::Max(1, [int]$collectorSettings.keyword_retry_backoff_seconds) } else { 10 }
$keywordTransitionRange = if ($collectorSettings.PSObject.Properties.Name -contains 'jitter_keyword_transition_seconds') { @($collectorSettings.jitter_keyword_transition_seconds) } else { @(20,50) }
$keywordTransitionMinSeconds = [Math]::Max(0, [int]$keywordTransitionRange[0])
$keywordTransitionMaxSeconds = [Math]::Max($keywordTransitionMinSeconds, [int]$keywordTransitionRange[1])
$collector = Join-Path $Root 'common\src\channels_pc_collector.py'
$enricher = Join-Path $Root 'common\src\channels_browser_enricher.mjs'
$post = Join-Path $Root 'common\src\channels_ods_postprocess.mjs'
$importer = Join-Path $Root 'common\src\mysql-import-retry.mjs'
$workerStatus = [ordered]@{workerId=(Split-Path $WorkerRoot -Leaf); mode=$Mode; startedAt=(Get-Date).ToString('o'); tasks=@()}
$stopFile = Join-Path $WorkerRoot '.state\stop.requested'
$infrastructureBlocked = $false
$redisStateScope = if ($env:WECHAT_REDIS_STATE_SCOPE) { ([string]$env:WECHAT_REDIS_STATE_SCOPE -replace '[^A-Za-z0-9_-]+','_').Trim('_') } else { '' }
$stateRoot = if ($redisStateScope) { Join-Path $WorkerRoot ('.state\redis-runs\' + $redisStateScope) } else { Join-Path $WorkerRoot '.state' }
$runsRoot = if ($redisStateScope) { Join-Path $WorkerRoot ('runs\redis-runs\' + $redisStateScope) } else { Join-Path $WorkerRoot 'runs' }
New-Item -ItemType Directory -Force -Path $stateRoot,$runsRoot | Out-Null
if ($redisStateScope) { Write-Host "Redis state scope: $redisStateScope (fresh reset generations do not reuse older local checkpoints)." }
$CompletionSchemaVersion = 'channels-pagination-v8-bound-search-end'
# The outer Redis scheduler owns the safe-stop marker for dynamic workers.
# Clearing it in every per-keyword child creates a race where the scheduler
# can claim several new keywords after the operator requested a stop.  Static
# launches still clear an old consumed marker at startup as before.
if (-not $redisStateScope) {
  Remove-Item $stopFile -Force -ErrorAction SilentlyContinue
}
foreach ($task in $queue.tasks) {
  if (($task.PSObject.Properties.Name -contains 'keywordAllowList') -and @($task.keywordAllowList).Count -eq 0) { $workerStatus.tasks += [pscustomobject]@{taskId=$task.id;status='skipped_unassigned'}; continue }
  # Redis test/operations queues may intentionally point at a keyword file
  # outside the portable package.  Join-Path on Windows does not discard the
  # first drive-qualified operand here; it can produce
  # "<package>\C:\..." and make every claimed task fail before collection.
  $taskFile = if ([System.IO.Path]::IsPathRooted([string]$task.keywordsFile)) {
    [System.IO.Path]::GetFullPath([string]$task.keywordsFile)
  } else {
    Join-Path $Root ([string]$task.keywordsFile)
  }
  $taskRoot = Join-Path $runsRoot $task.id
  $stateDb = Join-Path $stateRoot ($task.id + '.sqlite')
  $screens = Join-Path $stateRoot ("screenshots\" + $task.id)
  New-Item -ItemType Directory -Force -Path $taskRoot,$screens | Out-Null
  $taskStatusPath = Join-Path $taskRoot 'task_status.json'
  $taskStatus = [ordered]@{taskId=$task.id;name=$task.name;status='running';startedAt=(Get-Date).ToString('o');keywords=@()}
  Write-Host "Task $($task.id): $(@($task.keywordAllowList).Count) keywords queued."
  foreach ($allowedKeyword in @($task.keywordAllowList)) {
    Write-Host "[$($task.id)] Starting keyword: $allowedKeyword"
    $safe = ($allowedKeyword -replace '[^\p{L}\p{N}_-]+','_').Trim('_')
    $outDir = Join-Path $taskRoot $safe
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $keywordStatusPath = Join-Path $outDir 'keyword_status.json'
    $oldKeyword = Read-JsonSafe $keywordStatusPath
    if ($Mode -eq 'run' -and (-not $env:WECHAT_SEARCH_SCAN_RUN_TOKEN) -and $oldKeyword -and $oldKeyword.status -eq 'completed' -and $oldKeyword.mysql.status -ne 'failed' -and $oldKeyword.completionSchemaVersion -eq $CompletionSchemaVersion) { $taskStatus.keywords += $oldKeyword; continue }
    # Only this already-selected keyword is being revisited. Keep its exact
    # legacy report before writing the new policy result; SQLite/video/Redis
    # attempt history is never deleted or reset by the version transition.
    if ((Test-Path -LiteralPath $keywordStatusPath) -and ($env:WECHAT_SEARCH_SCAN_RUN_TOKEN -or !$oldKeyword -or $oldKeyword.completionSchemaVersion -ne $CompletionSchemaVersion)) {
      $legacyStatusDigest = Get-StatusEvidenceHash $keywordStatusPath
      $legacyHistory = Join-Path $outDir 'acceptance-history'
      New-Item -ItemType Directory -Force -Path $legacyHistory | Out-Null
      $legacyStatusBackup = Join-Path $legacyHistory ('keyword_status.' + $legacyStatusDigest.ToLowerInvariant() + '.json')
      if (-not (Test-Path -LiteralPath $legacyStatusBackup)) { Copy-Item -LiteralPath $keywordStatusPath -Destination $legacyStatusBackup }
      if ((Get-StatusEvidenceHash $legacyStatusBackup) -ne $legacyStatusDigest) { throw 'Legacy keyword report evidence mismatch; refusing overwrite' }
    }
    $ks = [ordered]@{keyword=$allowedKeyword;status='running';completionSchemaVersion=$CompletionSchemaVersion;startedAt=(Get-Date).ToString('o');outputDir=$outDir;mysql=[ordered]@{status='pending'}}
    $salvage = $null
    $salvageAttempted = $false
    $salvageParameters = @{Python=$python;Node=$node;Collector=$collector;Enricher=$enricher;Postprocessor=$post;Importer=$importer;OutputDir=$outDir;StateDb=$stateDb;Keyword=$allowedKeyword;CollectComments=[bool]$task.collectComments;DatabaseEnabled=$dbEnabled}
    Write-JsonAtomic $ks $keywordStatusPath 8
    try {
      $raw=Join-Path $outDir 'ods_social_media_post_channels.jsonl'; $enrich=Join-Path $outDir 'browser_enrichment.jsonl'; $final=Join-Path $outDir 'ods_social_media_post_channels_final.jsonl'
      # If the previous process was killed before its finally/salvage path ran,
      # recover committed SQLite rows before resuming live collection.
      $previousGracefulImportSucceeded = $oldKeyword -and $oldKeyword.status -eq 'partial' -and $oldKeyword.mysql -and $oldKeyword.mysql.status -eq 'success'
      if ($previousGracefulImportSucceeded) {
        Write-Host "[$($task.id)] Previous graceful stop was already imported; resuming directly from SQLite checkpoint." -ForegroundColor Green
      } elseif ($oldKeyword -and (Test-Path $stateDb)) {
        Write-Host "[$($task.id)] Recovering committed rows from the previous interrupted run..." -ForegroundColor Yellow
        & $python $collector export-ods --output-dir $outDir --state-db $stateDb --keyword $allowedKeyword; if ($LASTEXITCODE -ne 0) { throw "recovery export exit $LASTEXITCODE" }
        if ((Test-Path $raw) -and (Get-Item $raw).Length -gt 0) {
          $recoverEnrichArgs=@($enricher,$raw,$enrich); if ($task.collectComments) {$recoverEnrichArgs += '--comments'}; & $node @recoverEnrichArgs; if ($LASTEXITCODE -ne 0) {throw "recovery enricher exit $LASTEXITCODE"}
          $recoverPostArgs=@($post,$raw,$enrich,$final); if ($task.collectComments) {$recoverPostArgs += '--comments'}; & $node @recoverPostArgs; if ($LASTEXITCODE -ne 0) {throw "recovery postprocess exit $LASTEXITCODE"}
          if ($dbEnabled) {
            $recoverCommentFile=Join-Path $outDir 'ods_social_media_comment_channels_final.jsonl'; $recoverImportArgs=@($importer,'--posts',$final,'--status',(Join-Path $outDir 'mysql_import_status.json')); if ($task.collectComments -and (Test-Path $recoverCommentFile)) {$recoverImportArgs += @('--comments',$recoverCommentFile)}
            & $node @recoverImportArgs; if ($LASTEXITCODE -ne 0) {throw "recovery mysql import exit $LASTEXITCODE"}
            $ks.mysql=Get-Content (Join-Path $outDir 'mysql_import_status.json') -Raw -Encoding UTF8 | ConvertFrom-Json
          }
          Write-Host "[$($task.id)] Previous committed rows recovered. Resuming collection." -ForegroundColor Green
        }
      }
      $collectArgs=@('collect-live','--input',$taskFile,'--config',$config,'--cutoff',$queue.cutoff,'--max-results',[string]$effectiveMaxResults,'--state-db',$stateDb,'--screenshots',$screens,'--keyword',$allowedKeyword,'--stop-file',$stopFile)
      if ($task.collectComments) { $collectArgs += '--comments' }
      $collectorExit = 0
      $collectorAttempt = 0
      do {
        $collectorAttempt++
        & $python $collector @collectArgs
        $collectorExit = $LASTEXITCODE
        if ($collectorExit -eq 0) { break }
        if ($collectorExit -eq 75) {
          $infrastructureBlocked = $true
          throw 'Redis checkpoint unavailable; content retries paused; local recovery required.'
        }
        if($env:SOCIAL_VOLUME_ENABLED -eq '1' -or $env:REDIS_URL){
          & $python (Join-Path $Common 'src\operational_gate.py') --check
          $OperationalCheck=$LASTEXITCODE
          if($OperationalCheck -eq 76){Write-Host '[Platform hold] Incident recorded; no inner retry until cooldown/operator confirmation.';break}
          if($OperationalCheck -ne 0){$infrastructureBlocked=$true;throw 'Operational incident state unavailable; no inner retry.'}
        }
        if (Test-Path $stopFile) {
          Write-Host "[$($task.id)] Safe stop requested; current keyword will be checkpointed without automatic restart." -ForegroundColor Yellow
          break
        }
        if ($collectorAttempt -ge $keywordRetryAttempts) { break }
        $retryDelay = [Math]::Min(120, $keywordRetryBackoffSeconds * [Math]::Pow(2, $collectorAttempt - 1))
        Write-Host "[$($task.id)] Collector exit $collectorExit for '$allowedKeyword'. Automatic retry $($collectorAttempt + 1)/$keywordRetryAttempts in $retryDelay seconds; staying on the same keyword." -ForegroundColor Yellow
        Start-Sleep -Seconds ([int]$retryDelay)
      } while ($true)
      if ($collectorExit -ne 0) { Write-Host "[$($task.id)] Collector stopped with exit $collectorExit; salvaging committed SQLite rows..." -ForegroundColor Yellow }
      # Always export the SQLite checkpoint, even when collection was
      # interrupted or returned a partial status.
      $salvageAttempted = $true
      $salvage = Invoke-KeywordCheckpointSalvage @salvageParameters
      $ks.salvage = $salvage
      $ks.mysql = $salvage.mysql
      if (-not $salvage.success) {throw "Checkpoint recovery failed at $($salvage.stage); existing data retained."}
      if ($collectorExit -ne 0) {
        $ks.status='partial'; $ks.error="collector exit $collectorExit; committed rows were exported/imported; retry resumes from SQLite checkpoint"
      } else {
        $ks.status='completed'
      }
      $ks.completedAt=(Get-Date).ToString('o')
    } catch {
      $ks.status='failed';$ks.error=$_.Exception.Message;$ks.failedAt=(Get-Date).ToString('o')
      $infrastructureBlocked=$true
      Write-Host "[$($task.id)] FAILED: $allowedKeyword - $($ks.error)" -ForegroundColor Red
      # An operational-check exception must not bypass durable data salvage.
      if (-not $salvageAttempted) {
        $salvageAttempted=$true
        $salvageParameters.OfflineOnly=$true
        $salvage=Invoke-KeywordCheckpointSalvage @salvageParameters
        $ks.salvage=$salvage
        $ks.mysql=$salvage.mysql
      }
      $ks.infrastructureBlocked=$true
    }
    Write-JsonAtomic $ks $keywordStatusPath 10; $taskStatus.keywords += [pscustomobject]$ks
    if ($infrastructureBlocked) {
      Write-Host "[$($task.id)] $(Get-KeywordRecoveryMessage $salvage) Infrastructure unavailable; no next keyword will start." -ForegroundColor Yellow
      break
    }
    if (Test-Path $stopFile) {
      Write-Host "[$($task.id)] Safe stop requested; remaining keywords will be collected on the next run." -ForegroundColor Yellow
      break
    }
    if ($ks.status -in @('partial','failed')) {
      Write-Host "[$($task.id)] Keyword '$allowedKeyword' ended as $($ks.status). $(Get-KeywordRecoveryMessage $salvage) This keyword stays queued." -ForegroundColor Yellow
    }
    # A selected/--once child has no next keyword. Do not delay its durable
    # confirmation until a sample deadline; normal multi-task pacing remains.
    if ($env:WECHAT_FINAL_TASK -eq '1' -and @($task.keywordAllowList).Count -eq 1) { continue }
    if ($collectorSettings.jitter_enabled) {
      $transitionDelay = Get-Random -Minimum $keywordTransitionMinSeconds -Maximum ($keywordTransitionMaxSeconds + 1)
      Write-Host "[$($task.id)] Keyword transition jitter: $transitionDelay seconds before the next keyword."
      if ($transitionDelay -gt 0) { Start-Sleep -Seconds $transitionDelay }
    } elseif ([int]$task.transitionDelaySeconds -gt 0) {
      Start-Sleep -Seconds ([int]$task.transitionDelaySeconds)
    }
  }
  $hasFailedKeyword = @($taskStatus.keywords|Where-Object {$_.status -eq 'failed'}).Count -gt 0
  $hasPartialKeyword = @($taskStatus.keywords|Where-Object {$_.status -eq 'partial'}).Count -gt 0
  $taskStatus.status=if ($hasFailedKeyword) {'failed'} elseif ($hasPartialKeyword) {'partial'} else {'completed'}; $taskStatus.finishedAt=(Get-Date).ToString('o'); Write-JsonAtomic $taskStatus $taskStatusPath 10; $workerStatus.tasks += [pscustomobject]$taskStatus
  if ($infrastructureBlocked -or (($hasFailedKeyword -or $hasPartialKeyword) -and (Test-Path $stopFile))) { break }
  if ($hasFailedKeyword -or $hasPartialKeyword) {
    Write-Host "[$($task.id)] Task has failed/partial keywords; continuing with the next task. The worker exit code still flags them for a follow-up run." -ForegroundColor Yellow
  }
}
$workerStatus.runToken=$env:WECHAT_SEARCH_SCAN_RUN_TOKEN
$workerStatus.redisTaskId=$env:WECHAT_REDIS_TASK_ID
$workerStatus.infrastructureBlocked=$infrastructureBlocked
$workerStatus.finishedAt=(Get-Date).ToString('o'); Write-JsonAtomic $workerStatus (Join-Path $WorkerRoot '.state\worker_status.json') 10
if ($infrastructureBlocked) {exit 75}
if (@($workerStatus.tasks|Where-Object {$_.status -eq 'failed'}).Count -gt 0) {exit 3}
if (@($workerStatus.tasks|Where-Object {$_.status -eq 'partial'}).Count -gt 0) {exit 4}
