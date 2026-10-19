param([ValidateSet('run','check')][string]$Mode='run')
$ErrorActionPreference = 'Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$resetPolicyFile = Join-Path $Common 'acceptance-policy.json'
if ($Mode -eq 'run' -and (Test-Path -LiteralPath $resetPolicyFile)) {
  $resetPolicy = Get-Content -LiteralPath $resetPolicyFile -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($resetPolicy.enabled -eq $true -and -not $env:WECHAT_RECOLLECT_ONCE) {
    throw 'VIDEO_BACKFILL_REQUIRES_ORIGINAL_RESET: video recovery now uses one reset of the existing keyword task; standalone ASR replay is disabled under the active acceptance policy.'
  }
}
$Root = (Resolve-Path (Join-Path $Common '..')).Path
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) { (Resolve-Path $env:WECHAT_WORKER_ROOT).Path.TrimEnd('\') } else { $Root.TrimEnd('\') }
function Write-JsonAtomic([object]$Value, [string]$Path, [int]$Depth = 8) {
  $directory = Split-Path -Parent $Path
  if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
  $temporary = "$Path.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
  $backup = "$Path.bak.$PID.$([Guid]::NewGuid().ToString('N'))"
  $encoding = New-Object System.Text.UTF8Encoding($false)
  try {
    [System.IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth $Depth), $encoding)
    if (Test-Path -LiteralPath $Path) { [System.IO.File]::Replace($temporary, $Path, $backup, $true) }
    else { [System.IO.File]::Move($temporary, $Path) }
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
  }
}

$node = if ($env:WECHAT_NODE) { $env:WECHAT_NODE } else { (Get-Command node -ErrorAction Stop).Source }
$python = if ($env:WECHAT_PYTHON) { $env:WECHAT_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
$queueFile = if ($env:WECHAT_QUEUE_FILE) {
  (Resolve-Path $env:WECHAT_QUEUE_FILE -ErrorAction Stop).Path
} else {
  Join-Path $WorkerRoot 'task-queue.json'
}
if (-not (Test-Path $queueFile)) { throw "Task queue not found: $queueFile" }
Write-Host "ASR task queue: $queueFile"
$queue = Get-Content $queueFile -Raw -Encoding UTF8 | ConvertFrom-Json
$config = Join-Path $Common 'collector_config.json'
$collector = Join-Path $Common 'src\channels_pc_collector.py'
$enricher = Join-Path $Common 'src\channels_browser_enricher.mjs'
$postprocess = Join-Path $Common 'src\channels_ods_postprocess.mjs'
$importer = Join-Path $Common 'src\mysql-import-retry.mjs'
$dbEnabled = $env:MYSQL_ENABLED -ne '0'
$redisStateScope = if ($env:WECHAT_REDIS_STATE_SCOPE) { ([string]$env:WECHAT_REDIS_STATE_SCOPE -replace '[^A-Za-z0-9_-]+','_').Trim('_') } else { '' }
$stateRoot = if ($redisStateScope) { Join-Path $WorkerRoot ('.state\redis-runs\' + $redisStateScope) } else { Join-Path $WorkerRoot '.state' }
$runsRoot = if ($redisStateScope) { Join-Path $WorkerRoot ('runs\redis-runs\' + $redisStateScope) } else { Join-Path $WorkerRoot 'runs' }
New-Item -ItemType Directory -Force -Path $stateRoot,$runsRoot | Out-Null
if ($redisStateScope) { Write-Host "Redis ASR state scope: $redisStateScope" }

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
}

$status = [ordered]@{workerId=(Split-Path $WorkerRoot -Leaf);phase='asr-backfill';retryRunId=$env:WECHAT_RETRY_OBSERVATION_RUN_ID;startedAt=(Get-Date).ToString('o');keywords=@()}
$failedKeywords = 0
$stopFile = Join-Path $WorkerRoot '.state\stop.requested'
$exactFingerprint = [string]$env:WECHAT_REDIS_VIDEO_FINGERPRINT
$exactArticleKey = [string]$env:WECHAT_REDIS_VIDEO_ARTICLE_KEY
foreach ($task in @($queue.tasks)) {
  if (Test-Path -LiteralPath $stopFile) { break }
  $stateDb = Join-Path $stateRoot ($task.id + '.sqlite')
  # A Redis video-retry may be claimed by a different machine from the one
  # that performed the metadata scan.  In that case the local SQLite file is
  # legitimately absent; collect-live creates it and hydrates the exact video
  # checkpoint from Redis.  The old unconditional continue falsely reported
  # "ASR phase completed" without ever opening WeChat or running ASR.
  if ((-not (Test-Path $stateDb)) -and (-not $env:WECHAT_REDIS_VIDEO_FINGERPRINT)) { continue }
  if ((-not (Test-Path $stateDb)) -and $env:WECHAT_REDIS_VIDEO_FINGERPRINT) {
    Write-Host "[$($task.id)] No local SQLite state; creating it and hydrating the exact Redis video checkpoint." -ForegroundColor Yellow
  }
  $taskFile = Join-Path $Root $task.keywordsFile
  foreach ($keyword in @($task.keywordAllowList)) {
    if (Test-Path -LiteralPath $stopFile) { break }
    $safe = ($keyword -replace '[^\p{L}\p{N}_-]+','_').Trim('_')
    $outDir = Join-Path $runsRoot ($task.id + '\' + $safe)
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    Write-Host "[$($task.id)] ASR phase starting: $keyword"
    $keywordState = [ordered]@{topic=$task.id;keyword=$keyword;exactFingerprint=$exactFingerprint;databaseImported=$false;status='running';startedAt=(Get-Date).ToString('o')}
    try {
      $raw = Join-Path $outDir 'ods_social_media_post_channels.jsonl'
      $directEnrichment = Join-Path $outDir 'browser_enrichment_direct_asr.jsonl'
      $directIngestStatus = Join-Path $outDir 'direct_asr_ingest_status.json'
      if ($exactFingerprint) {
        Write-Host "[$($task.id)] Hydrating only Redis video fingerprint $exactFingerprint"
        & $python $collector hydrate-redis-retry --state-db $stateDb --keyword $keyword --fingerprint $exactFingerprint
        if ($LASTEXITCODE -ne 0) { throw "Exact Redis retry hydration failed: $keyword" }
      }
      # Prefer platform subtitle tracks, visible captions and direct media ASR.
      # A failed public-page probe does not block the logged-in client fallback.
      $exportArgs = @('export-ods','--output-dir',$outDir,'--state-db',$stateDb,'--keyword',$keyword)
      if ($exactArticleKey) { $exportArgs += @('--article-key',$exactArticleKey) }
      & $python $collector @exportArgs
      if ($LASTEXITCODE -ne 0) { throw "Direct ASR pre-export failed: $keyword" }
      $hasLocalRows = (Test-Path -LiteralPath $raw) -and (Get-Item -LiteralPath $raw).Length -gt 0
      if ((-not $hasLocalRows) -and (-not $env:WECHAT_REDIS_VIDEO_FINGERPRINT)) {
        $keywordState.status='skipped_no_local_rows'
        $keywordState.finishedAt=(Get-Date).ToString('o')
        $status.keywords += [pscustomobject]$keywordState
        Write-JsonAtomic $status (Join-Path $WorkerRoot '.state\asr_backfill_status.json') 8
        Write-Host "[$($task.id)] ASR phase skipped: no locally captured rows for $keyword" -ForegroundColor Yellow
        continue
      }
      $directResolved = $false
      if ($hasLocalRows) {
        & $node $enricher $raw $directEnrichment --asr
        if ($LASTEXITCODE -eq 0) {
          Remove-Item -LiteralPath $directIngestStatus -Force -ErrorAction SilentlyContinue
          & $python $collector ingest-asr-enrichment --input $directEnrichment --state-db $stateDb --config $config --status-file $directIngestStatus
          if ($LASTEXITCODE -ne 0) {
            Write-Host "[$($task.id)] Direct ASR ingest failed; continuing with client fallback: $keyword" -ForegroundColor Yellow
          } else {
            try {
              if (-not (Test-Path -LiteralPath $directIngestStatus)) {
                throw "Direct ASR status file was not created"
              }
              $directIngest = Get-Content -LiteralPath $directIngestStatus -Raw -Encoding UTF8 | ConvertFrom-Json
              $directResolved = [int]$directIngest.completed -gt 0
            } catch {
              Write-Host "[$($task.id)] Direct ASR status file was invalid; continuing with client fallback: $keyword - $($_.Exception.Message)" -ForegroundColor Yellow
            }
          }
        } else {
          Write-Host "[$($task.id)] Direct subtitle/media resolution failed; continuing with client fallback: $keyword" -ForegroundColor Yellow
        }
      } else {
        Write-Host "[$($task.id)] No local row on this worker; hydrating the exact video checkpoint from Redis before ASR." -ForegroundColor Yellow
      }

      $collectorExit = 0
      if ($directResolved) {
        Write-Host "[$($task.id)] Direct subtitle/media ASR completed the exact video; client playback skipped." -ForegroundColor Green
      } else {
        $collectArgs = @('collect-live','--input',$taskFile,'--config',$config,'--cutoff',$queue.cutoff,'--max-results','0','--state-db',$stateDb,'--screenshots',(Join-Path $WorkerRoot ('.state\screenshots\' + $task.id)),'--keyword',$keyword,'--asr-backfill','--stop-file',$stopFile)
        if ($exactFingerprint) { $collectArgs += @('--retry-fingerprint',$exactFingerprint) }
        & $python $collector @collectArgs
        $collectorExit = $LASTEXITCODE
      }

      # Always salvage subtitles already committed to SQLite, even if one card
      # or the search surface failed. Then continue to the next keyword.
      $enrichment = Join-Path $outDir 'browser_enrichment.jsonl'
      $final = Join-Path $outDir 'ods_social_media_post_channels_final.jsonl'
      & $python $collector @exportArgs
      if ($LASTEXITCODE -ne 0) { throw "ASR export failed: $keyword" }
      $enrichArgs = @($enricher,$raw,$enrichment)
      if ($task.collectComments) { $enrichArgs += '--comments' }
      & $node @enrichArgs
      if ($LASTEXITCODE -ne 0) { throw "ASR enrichment failed: $keyword" }
      $postArgs = @($postprocess,$raw,$enrichment,$final)
      if ($task.collectComments) { $postArgs += '--comments' }
      & $node @postArgs
      if ($LASTEXITCODE -ne 0) { throw "ASR postprocess failed: $keyword" }
      if ($dbEnabled) {
        $importArgs = @($importer,'--posts',$final,'--status',(Join-Path $outDir 'mysql_asr_import_status.json'))
        $commentFile = Join-Path $outDir 'ods_social_media_comment_channels_final.jsonl'
        if ($task.collectComments -and (Test-Path $commentFile)) { $importArgs += @('--comments',$commentFile) }
        & $node @importArgs
        if ($LASTEXITCODE -ne 0) { throw "ASR MySQL import failed: $keyword" }
        $keywordState.databaseImported=$true
      }
      if ($collectorExit -eq 0) {
        $keywordState.status='completed'
      } else {
        $keywordState.status='partial'
        $keywordState.exitCode=$collectorExit
        $keywordState.error="Client ASR fallback exit $collectorExit; committed subtitles were preserved"
        $failedKeywords++
      }
    } catch {
      $keywordState.status='failed'
      $keywordState.error=$_.Exception.Message
      $failedKeywords++
      Write-Host "[$($task.id)] ASR keyword failed but later keywords will continue: $keyword - $($keywordState.error)" -ForegroundColor Red
    }
    $keywordState.finishedAt=(Get-Date).ToString('o')
    $status.keywords += [pscustomobject]$keywordState
    Write-JsonAtomic $status (Join-Path $WorkerRoot '.state\asr_backfill_status.json') 8
  }
}
$status.finishedAt = (Get-Date).ToString('o')
Write-JsonAtomic $status (Join-Path $WorkerRoot '.state\asr_backfill_status.json') 8
if ($failedKeywords -gt 0) {
  Write-Host "ASR phase finished with $failedKeywords partial/failed keyword(s); other keywords were still processed." -ForegroundColor Yellow
  exit 4
}
Write-Host 'ASR phase completed.' -ForegroundColor Green
