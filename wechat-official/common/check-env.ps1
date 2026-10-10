$ErrorActionPreference = 'Continue'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Common '..')
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) { Resolve-Path $env:WECHAT_WORKER_ROOT } else { $Root }
$checks = @()
function Add-Check($name, $ok, $detail) { $script:checks += [pscustomobject]@{name=$name; ok=[bool]$ok; detail=[string]$detail} }
$node = if ($env:WECHAT_NODE) { $env:WECHAT_NODE } else { (Get-Command node -ErrorAction SilentlyContinue).Source }
$python = if ($env:WECHAT_PYTHON) { $env:WECHAT_PYTHON } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
$nodeDetail = if ($node) { $node } else { 'not-found' }
$pythonDetail = if ($python) { $python } else { 'not-found' }
Add-Check 'node' ([bool]$node -and (Test-Path -LiteralPath $node)) $nodeDetail
Add-Check 'python' ([bool]$python -and (Test-Path -LiteralPath $python)) $pythonDetail
if ($python -and (Test-Path -LiteralPath $python)) {
  $moduleProbe = & $python -c "import openpyxl, PIL, pywinauto, win32clipboard" 2>&1
  Add-Check 'python_modules' ($LASTEXITCODE -eq 0) ($(if ($LASTEXITCODE -eq 0) {'openpyxl/PIL/pywinauto/pywin32'} else {[string]$moduleProbe}))
}
Add-Check 'collector' (Test-Path "$Root\common\src\wechat_pc_collector.py") "$Root\common\src\wechat_pc_collector.py"
Add-Check 'browser_enricher' (Test-Path "$Root\common\src\wechat_browser_enricher.mjs") "$Root\common\src\wechat_browser_enricher.mjs"
Add-Check 'postprocess' (Test-Path "$Root\common\src\wechat_ods_postprocess.mjs") "$Root\common\src\wechat_ods_postprocess.mjs"
Add-Check 'dedupe_module' (Test-Path "$Root\common\src\wechat-dedupe.mjs") "$Root\common\src\wechat-dedupe.mjs"
Add-Check 'dedupe_sql' (Test-Path "$Root\common\sql\deduplicate_wechat_posts.sql") "$Root\common\sql\deduplicate_wechat_posts.sql"
Add-Check 'mysql_check' (Test-Path "$Root\common\src\mysql-check.mjs") "$Root\common\src\mysql-check.mjs"
Add-Check 'playwright_module' (Test-Path "$Root\common\node_modules\playwright\package.json") "$Root\common\node_modules\playwright\package.json"
Add-Check 'asr_worker' (Test-Path "$Root\common\src\asr-worker.py") "$Root\common\src\asr-worker.py"
Add-Check 'edge_or_chrome' ((Test-Path "$Root\common\runtime\browsers\chrome-win64\chrome.exe") -or (Test-Path "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe") -or (Test-Path "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") -or (Test-Path "$env:ProgramFiles\Google\Chrome\Application\chrome.exe")) 'bundled Edge/Chrome or system browser'
$wechatProcesses = @(Get-Process Weixin,WeChat -ErrorAction SilentlyContinue | Where-Object {$_.Path} | Select-Object -First 1)
if ($wechatProcesses.Count -eq 1) {
  $wechatVersion = (Get-Item -LiteralPath $wechatProcesses[0].Path).VersionInfo.FileVersion
  $env:WECHAT_CLIENT_VERSION = $wechatVersion
  $env:WECHAT_CLIENT_PATH = $wechatProcesses[0].Path
  # Do not block collection by version number. Account-side rollout and UI
  # structure are detected at runtime as detached/embedded; the version is
  # retained only for diagnostics and coordinate fallback selection.
  Add-Check 'wechat_client' $true "$wechatVersion; detected for diagnostics only (no version restriction)"
} else {
  Add-Check 'wechat_client' $false 'Weixin.exe/WeChat.exe is not running or its path cannot be read'
}
$displayProbeText = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$Root\common\set-display-profile.ps1" -Profile auto -ValidateOnly 2>&1 | Out-String).Trim()
$displayProbeExit = $LASTEXITCODE
try {
  $displayProbe = $displayProbeText | ConvertFrom-Json
  Add-Check 'display_resolution' ($displayProbeExit -eq 0 -and $displayProbe.ok) "$($displayProbe.current); supported: 2560x1440 or 1920x1080"
  Add-Check 'display_scaling' ($displayProbe.scalePercent -in @(100, 150)) "$($displayProbe.scalePercent)% (supported: 100% or 150%)"
} catch {
  Add-Check 'display_resolution' $false $displayProbeText
  Add-Check 'display_scaling' $false 'unable to detect DPI scaling'
}
if ($env:MYSQL_ENABLED -ne '0') {
  Add-Check 'mysql_user' ([bool]$env:MYSQL_USER) 'MYSQL_USER'
  Add-Check 'mysql_password' ([bool]$env:MYSQL_PASSWORD) 'MYSQL_PASSWORD'
}
Add-Check 'task_queue' (Test-Path "$Root\common\task-queue.json") "$Root\common\task-queue.json"
Add-Check 'writable' ((Test-Path $WorkerRoot) -and (Test-Path (New-Item -ItemType File -Force -Path (Join-Path $WorkerRoot '.state\write-test.tmp')))) "$WorkerRoot"
Remove-Item (Join-Path $WorkerRoot '.state\write-test.tmp') -Force -ErrorAction SilentlyContinue
$result = [pscustomobject]@{workerRoot=[string]$WorkerRoot; checks=$checks; ok=(@($checks | Where-Object {-not $_.ok}).Count -eq 0); checkedAt=(Get-Date).ToString('o')}
$result | ConvertTo-Json -Depth 5 | Tee-Object -FilePath (Join-Path $WorkerRoot '.state\environment_check.json')
if (-not $result.ok) { exit 2 }
