$ErrorActionPreference = 'Continue'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Common '..')
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) { Resolve-Path $env:WECHAT_WORKER_ROOT } else { $Root }
$checks = @()
function Add-Check($name, $ok, $detail) {
  $optionalAudio = $env:SOCIAL_VOLUME_ENABLED -eq '1' -and $name -in @('asr_python_modules','audio_loopback','asr_worker','loopback_recorder','process_loopback_recorder','asr_model')
  $script:checks += [pscustomobject]@{name=$name; ok=[bool]$ok; required=(-not $optionalAudio); detail=[string]$detail}
}
$node = if ($env:WECHAT_NODE) { $env:WECHAT_NODE } else { (Get-Command node -ErrorAction SilentlyContinue).Source }
$python = if ($env:WECHAT_PYTHON) { $env:WECHAT_PYTHON } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
$nodeDetail = if ($node) { $node } else { 'not-found' }
$pythonDetail = if ($python) { $python } else { 'not-found' }
Add-Check 'node' ([bool]$node -and (Test-Path -LiteralPath $node)) $nodeDetail
Add-Check 'python' ([bool]$python -and (Test-Path -LiteralPath $python)) $pythonDetail
if ($python -and (Test-Path -LiteralPath $python)) {
  # soundcard initializes Media Foundation COM and must stay isolated from
  # pywinauto's COM apartment, just like the production loopback subprocess.
  $moduleProbe = & $python -c "import openpyxl, PIL, pywinauto, win32clipboard" 2>&1
  Add-Check 'python_modules' ($LASTEXITCODE -eq 0) ($(if ($LASTEXITCODE -eq 0) {'openpyxl/PIL/pywinauto/pywin32'} else {[string]$moduleProbe}))
  $asrModuleProbe = & $python -c "import faster_whisper" 2>&1
  Add-Check 'asr_python_modules' ($LASTEXITCODE -eq 0) ($(if ($LASTEXITCODE -eq 0) {'faster-whisper'} else {[string]$asrModuleProbe}))
  $audioProbe = & $python -c "import soundcard as sc; s=sc.default_speaker(); assert s is not None; print(s.name)" 2>&1
  Add-Check 'audio_loopback' ($LASTEXITCODE -eq 0) ($(if ($LASTEXITCODE -eq 0) {[string]$audioProbe} else {[string]$audioProbe}))
}
Add-Check 'collector' (Test-Path "$Root\common\src\channels_pc_collector.py") "$Root\common\src\channels_pc_collector.py"
Add-Check 'browser_enricher' (Test-Path "$Root\common\src\channels_browser_enricher.mjs") "$Root\common\src\channels_browser_enricher.mjs"
Add-Check 'postprocess' (Test-Path "$Root\common\src\channels_ods_postprocess.mjs") "$Root\common\src\channels_ods_postprocess.mjs"
Add-Check 'mysql_check' (Test-Path "$Root\common\src\mysql-check.mjs") "$Root\common\src\mysql-check.mjs"
Add-Check 'playwright_module' (Test-Path "$Root\common\node_modules\playwright\package.json") "$Root\common\node_modules\playwright\package.json"
Add-Check 'asr_worker' (Test-Path "$Root\common\src\asr-worker.py") "$Root\common\src\asr-worker.py"
Add-Check 'loopback_recorder' (Test-Path "$Root\common\src\loopback-recorder.py") "$Root\common\src\loopback-recorder.py"
Add-Check 'process_loopback_recorder' (Test-Path "$Root\common\src\process-loopback-recorder.exe") "$Root\common\src\process-loopback-recorder.exe"
Add-Check 'asr_model' ((Test-Path "$Root\common\.state\asr-models") -and @((Get-ChildItem "$Root\common\.state\asr-models" -Recurse -File -ErrorAction SilentlyContinue)).Count -gt 0) "$Root\common\.state\asr-models"
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
  Add-Check 'display_scaling' (@(100, 150) -contains [int]$displayProbe.scalePercent) "$($displayProbe.scalePercent)% (supported: 100% or 150%)"
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
$result = [pscustomobject]@{workerRoot=[string]$WorkerRoot; checks=$checks; ok=(@($checks | Where-Object {$_.required -and -not $_.ok}).Count -eq 0); checkedAt=(Get-Date).ToString('o')}
$json = $result | ConvertTo-Json -Depth 5
$statusPath = Join-Path $WorkerRoot '.state\environment_check.json'
$temporary = "$statusPath.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
$backup = "$statusPath.bak.$PID.$([Guid]::NewGuid().ToString('N'))"
$encoding = New-Object System.Text.UTF8Encoding($false)
try {
  [System.IO.File]::WriteAllText($temporary, $json, $encoding)
  if (Test-Path -LiteralPath $statusPath) { [System.IO.File]::Replace($temporary, $statusPath, $backup, $true) }
  else { [System.IO.File]::Move($temporary, $statusPath) }
} finally {
  if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
}
Write-Output $json
if (-not $result.ok) { exit 2 }
