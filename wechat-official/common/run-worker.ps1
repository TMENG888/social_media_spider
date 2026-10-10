param([ValidateSet('run','retry','check')][string]$Mode='run')
$ErrorActionPreference = 'Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Common '..')
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) { Resolve-Path $env:WECHAT_WORKER_ROOT } else { $Root }
if ($Mode -eq 'check') { & (Join-Path $Common 'check-env.ps1'); exit $LASTEXITCODE }
$dbEnabled = $env:MYSQL_ENABLED -ne '0'
if ($dbEnabled) {
  if (-not $env:MYSQL_HOST) { $env:MYSQL_HOST = 'mysql.example.com' }
  if (-not $env:MYSQL_PORT) { $env:MYSQL_PORT = '3306' }
  if (-not $env:MYSQL_DATABASE) { $env:MYSQL_DATABASE = 'social' }
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
$queueFile = Join-Path $WorkerRoot 'task-queue.json'
if (-not (Test-Path $queueFile)) { $queueFile = Join-Path $Root 'common\task-queue.json' }
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
$keywordRetryAttempts = if ($collectorSettings.PSObject.Properties.Name -contains 'keyword_retry_attempts') { [Math]::Max(1, [int]$collectorSettings.keyword_retry_attempts) } else { 5 }
$keywordRetryBackoffSeconds = if ($collectorSettings.PSObject.Properties.Name -contains 'keyword_retry_backoff_seconds') { [Math]::Max(1, [int]$collectorSettings.keyword_retry_backoff_seconds) } else { 10 }
$collector = Join-Path $Root 'common\src\wechat_pc_collector.py'
$enricher = Join-Path $Root 'common\src\wechat_browser_enricher.mjs'
$post = Join-Path $Root 'common\src\wechat_ods_postprocess.mjs'
$importer = Join-Path $Root 'common\src\mysql-import.mjs'
$workerStatus = [ordered]@{workerId=(Split-Path $WorkerRoot -Leaf); mode=$Mode; startedAt=(Get-Date).ToString('o'); tasks=@()}
$stopFile = Join-Path $WorkerRoot '.state\stop.requested'
$CompletionSchemaVersion = 'wechat-pagination-v2'
Remove-Item $stopFile -Force -ErrorAction SilentlyContinue
foreach ($task in $queue.tasks) {
  if (Test-Path $stopFile) { Write-Host "Safe stop requested; ending the worker session before the next task." -ForegroundColor Yellow; break }
  if (($task.PSObject.Properties.Name -contains 'keywordAllowList') -and @($task.keywordAllowList).Count -eq 0) { $workerStatus.tasks += [pscustomobject]@{taskId=$task.id;status='skipped_unassigned'}; continue }
  $taskFile = Join-Path $Root $task.keywordsFile
  $taskRoot = Join-Path $WorkerRoot ("runs\" + $task.id)
  $stateDb = Join-Path $WorkerRoot (".state\" + $task.id + '.sqlite')
  $screens = Join-Path $WorkerRoot (".state\screenshots\" + $task.id)
  New-Item -ItemType Directory -Force -Path $taskRoot,$screens | Out-Null
  $taskStatusPath = Join-Path $taskRoot 'task_status.json'
  $taskStatus = [ordered]@{taskId=$task.id;name=$task.name;status='running';startedAt=(Get-Date).ToString('o');keywords=@()}
  Write-Host "Task $($task.id): $(@($task.keywordAllowList).Count) keywords queued."
  # Process keywords in multiple passes instead of stopping the whole worker
  # when a single keyword ends partial/failed (e.g. a few permanently deleted
  # articles). Unfinished keywords are re-queued for a bounded retry pass so
  # the remaining keywords are still collected in this session.
  $keywordMaxPasses = if ($collectorSettings.PSObject.Properties.Name -contains 'keyword_retry_passes') { [Math]::Max(1, [int]$collectorSettings.keyword_retry_passes) } else { 2 }
  $pendingKeywords = [System.Collections.Generic.List[string]]::new()
  foreach ($queuedKeyword in @($task.keywordAllowList)) { $pendingKeywords.Add([string]$queuedKeyword) }
  $keywordPass = 0
  $stopTaskForUnfinishedKeyword = $false
  while ($pendingKeywords.Count -gt 0 -and -not $stopTaskForUnfinishedKeyword) {
    if (Test-Path $stopFile) { Write-Host "[$($task.id)] Safe stop requested; ending this task before further keywords." -ForegroundColor Yellow; break }
    $keywordPass++
    if ($keywordPass -gt 1) {
      if (Test-Path $stopFile) { Write-Host "[$($task.id)] Safe stop requested; skipping remaining retry passes." -ForegroundColor Yellow; break }
      Write-Host "[$($task.id)] Retry pass $keywordPass/$keywordMaxPasses for $($pendingKeywords.Count) unfinished keyword(s)." -ForegroundColor Yellow
    }
    $passKeywords = @($pendingKeywords.ToArray())
    $pendingKeywords.Clear()
    foreach ($allowedKeyword in $passKeywords) {
    if (Test-Path $stopFile) { Write-Host "[$($task.id)] Safe stop requested; not starting the next keyword." -ForegroundColor Yellow; break }
    Write-Host "[$($task.id)] Starting keyword: $allowedKeyword"
    $safe = ($allowedKeyword -replace '[^\p{L}\p{N}_-]+','_').Trim('_')
    $outDir = Join-Path $taskRoot $safe
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $keywordStatusPath = Join-Path $outDir 'keyword_status.json'
    $oldKeyword = if (Test-Path $keywordStatusPath) { Get-Content $keywordStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
    if ($Mode -eq 'run' -and $oldKeyword -and $oldKeyword.status -eq 'completed' -and $oldKeyword.mysql.status -ne 'failed' -and $oldKeyword.completionSchemaVersion -eq $CompletionSchemaVersion) { $taskStatus.keywords += $oldKeyword; continue }
    $ks = [ordered]@{keyword=$allowedKeyword;status='running';completionSchemaVersion=$CompletionSchemaVersion;startedAt=(Get-Date).ToString('o');outputDir=$outDir;mysql=[ordered]@{status='pending'}}
    $ks | ConvertTo-Json -Depth 8 | Set-Content $keywordStatusPath -Encoding UTF8
    try {
      $raw=Join-Path $outDir 'ods_social_media_post_wechat.jsonl'; $enrich=Join-Path $outDir 'browser_enrichment.jsonl'; $final=Join-Path $outDir 'ods_social_media_post_wechat_final.jsonl'
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
            $recoverCommentFile=Join-Path $outDir 'ods_social_media_post_wechat_final_comments.jsonl'; $recoverImportArgs=@($importer,'--posts',$final,'--status',(Join-Path $outDir 'mysql_import_status.json')); if ($task.collectComments -and (Test-Path $recoverCommentFile)) {$recoverImportArgs += @('--comments',$recoverCommentFile)}
            & $node @recoverImportArgs; if ($LASTEXITCODE -ne 0) {throw "recovery mysql import exit $LASTEXITCODE"}
            $ks.mysql=Get-Content (Join-Path $outDir 'mysql_import_status.json') -Raw -Encoding UTF8 | ConvertFrom-Json
          }
          Write-Host "[$($task.id)] Previous committed rows recovered. Resuming collection." -ForegroundColor Green
        }
      }
      $collectArgs=@('collect-live','--input',$taskFile,'--config',$config,'--cutoff',$queue.cutoff,'--max-results',[string]$effectiveMaxResults,'--state-db',$stateDb,'--screenshots',$screens,'--keyword',$allowedKeyword,'--stop-file',$stopFile)
      $collectorExit = 0
      $collectorAttempt = 0
      do {
        $collectorAttempt++
        & $python $collector @collectArgs
        $collectorExit = $LASTEXITCODE
        if ($collectorExit -eq 0) { break }
        if (Test-Path $stopFile) {
          Write-Host "[$($task.id)] Safe stop requested; current keyword will be checkpointed without automatic restart." -ForegroundColor Yellow
          break
        }
        if ($collectorAttempt -ge $keywordRetryAttempts) { break }
        # Rows are committed to SQLite article-by-article. Restarting the same
        # keyword is therefore safe, catches newly inserted top results, and
        # uses URL/article-id upserts to avoid duplicates.
        $retryDelay = [Math]::Min(120, $keywordRetryBackoffSeconds * [Math]::Pow(2, $collectorAttempt - 1))
        Write-Host "[$($task.id)] Collector exit $collectorExit for '$allowedKeyword'. Automatic retry $($collectorAttempt + 1)/$keywordRetryAttempts in $retryDelay seconds; staying on the same keyword." -ForegroundColor Yellow
        Start-Sleep -Seconds ([int]$retryDelay)
      } while ($true)
      if ($collectorExit -ne 0) { Write-Host "[$($task.id)] Collector stopped with exit $collectorExit; salvaging committed SQLite rows..." -ForegroundColor Yellow }
      # Always export the SQLite checkpoint, even when collection was
      # interrupted or returned a partial status.
      & $python $collector export-ods --output-dir $outDir --state-db $stateDb --keyword $allowedKeyword; if ($LASTEXITCODE -ne 0) { throw "export exit $LASTEXITCODE" }
      $enrichArgs=@($enricher,$raw,$enrich); if ($task.collectComments) {$enrichArgs += '--comments'}; & $node @enrichArgs; if ($LASTEXITCODE -ne 0) {throw "enricher exit $LASTEXITCODE"}
      $postArgs=@($post,$raw,$enrich,$final); if ($task.collectComments) {$postArgs += '--comments'}; & $node @postArgs; if ($LASTEXITCODE -ne 0) {throw "postprocess exit $LASTEXITCODE"}
      if ($dbEnabled) {
        $commentFile=Join-Path $outDir 'ods_social_media_post_wechat_final_comments.jsonl'; $importArgs=@($importer,'--posts',$final,'--status',(Join-Path $outDir 'mysql_import_status.json')); if ($task.collectComments -and (Test-Path $commentFile)) {$importArgs += @('--comments',$commentFile)}
        & $node @importArgs; if ($LASTEXITCODE -ne 0) {throw "mysql import exit $LASTEXITCODE"}
        $ks.mysql=Get-Content (Join-Path $outDir 'mysql_import_status.json') -Raw -Encoding UTF8 | ConvertFrom-Json
      } else {$ks.mysql=[ordered]@{status='disabled'}}
      if ($collectorExit -ne 0) {
        $ks.status='partial'; $ks.error="collector exit $collectorExit; committed rows were exported/imported; retry resumes from SQLite checkpoint"
      } else {
        $ks.status='completed'
      }
      $ks.completedAt=(Get-Date).ToString('o')
    } catch {
      $ks.status='failed';$ks.error=$_.Exception.Message;$ks.failedAt=(Get-Date).ToString('o')
      Write-Host "[$($task.id)] FAILED: $allowedKeyword - $($ks.error)" -ForegroundColor Red
    }
    $ks | ConvertTo-Json -Depth 10 | Set-Content $keywordStatusPath -Encoding UTF8
    # Replace (not append) the per-keyword entry so retry passes do not
    # duplicate records in task_status.json.
    $existingKeywordIndex = -1
    for ($kIdx = 0; $kIdx -lt @($taskStatus.keywords).Count; $kIdx++) { if (@($taskStatus.keywords)[$kIdx].keyword -eq $allowedKeyword) { $existingKeywordIndex = $kIdx; break } }
    if ($existingKeywordIndex -ge 0) { $taskStatus.keywords[$existingKeywordIndex] = [pscustomobject]$ks } else { $taskStatus.keywords += [pscustomobject]$ks }
    if ($ks.status -in @('partial','failed')) {
      # Strict ordering contract: an unfinished keyword must never be skipped
      # in favour of later keywords.  Five bounded in-place collector retries
      # have already been attempted above.  Stop this worker now; the next
      # launch resumes this exact keyword from its durable checkpoint/top scan.
      Write-Host "[$($task.id)] Keyword '$allowedKeyword' is $($ks.status); stopping before the next keyword so no task is skipped." -ForegroundColor Red
      $stopTaskForUnfinishedKeyword = $true
    }
    if ([int]$task.transitionDelaySeconds -gt 0 -and -not $stopTaskForUnfinishedKeyword -and -not (Test-Path $stopFile)) {Start-Sleep -Seconds ([int]$task.transitionDelaySeconds)}
    }
  }
  $hasFailedKeyword = @($taskStatus.keywords|Where-Object {$_.status -eq 'failed'}).Count -gt 0
  $hasPartialKeyword = @($taskStatus.keywords|Where-Object {$_.status -eq 'partial'}).Count -gt 0
  $taskStatus.status=if ($hasFailedKeyword) {'failed'} elseif ($hasPartialKeyword) {'partial'} else {'completed'}; $taskStatus.finishedAt=(Get-Date).ToString('o'); $taskStatus|ConvertTo-Json -Depth 10|Set-Content $taskStatusPath -Encoding UTF8; $workerStatus.tasks += [pscustomobject]$taskStatus
  if ($hasFailedKeyword -or $hasPartialKeyword) {
    Write-Host "[$($task.id)] Task stopped on its first unfinished keyword; it resumes automatically on the next worker launch." -ForegroundColor Yellow
    break
  }
}
$workerStatus.finishedAt=(Get-Date).ToString('o');$workerStatus|ConvertTo-Json -Depth 10|Set-Content (Join-Path $WorkerRoot '.state\worker_status.json') -Encoding UTF8
if (@($workerStatus.tasks|Where-Object {$_.status -eq 'failed'}).Count -gt 0) {exit 3}
if (@($workerStatus.tasks|Where-Object {$_.status -eq 'partial'}).Count -gt 0) {exit 4}
