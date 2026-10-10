param([ValidateSet('run','retry')][string]$Mode='run')
$ErrorActionPreference = 'Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $Common '..')).Path
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) { (Resolve-Path $env:WECHAT_WORKER_ROOT).Path.TrimEnd('\') } else { $Root.TrimEnd('\') }

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
$displayText = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Common 'set-display-profile.ps1') -Profile $env:WECHAT_DISPLAY_PROFILE | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Display profile setup failed: $displayText" }
$display = $displayText | ConvertFrom-Json
$env:WECHAT_DISPLAY_WIDTH = [string]$display.current.Split('x')[0]
$env:WECHAT_DISPLAY_HEIGHT = [string]$display.current.Split('x')[1]
$env:WECHAT_DISPLAY_SCALE = [string]$display.scalePercent

$requestedDbEnabled = $env:MYSQL_ENABLED -ne '0'
if ($requestedDbEnabled) {
  if (-not $env:MYSQL_HOST) { $env:MYSQL_HOST = 'mysql.example.com' }
  if (-not $env:MYSQL_PORT) { $env:MYSQL_PORT = '3306' }
  if (-not $env:MYSQL_DATABASE) { $env:MYSQL_DATABASE = 'social' }
  if (-not $env:MYSQL_USER) { $env:MYSQL_USER = Read-Host 'MySQL username' }
  if (-not $env:MYSQL_PASSWORD) {
    $secure = Read-Host 'MySQL password' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $env:MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
  }
}

$logDir = Join-Path $WorkerRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("channels-two-stage-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))
$exitCode = 1
Start-Transcript -LiteralPath $logPath -Append -Force | Out-Null
try {
  Write-Host 'Integrated collection: metadata, topic-2 comments, complete audio and background ASR in one visit...' -ForegroundColor Cyan
  $previousClientAsr = $env:WECHAT_CLIENT_ASR
  $env:MYSQL_ENABLED = if ($requestedDbEnabled) { '1' } else { '0' }
  $env:WECHAT_CLIENT_ASR = '1'
  & (Join-Path $Common 'run-worker.ps1') -Mode $Mode
  $exitCode = $LASTEXITCODE
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  if ($exitCode -eq 0) { $exitCode = 1 }
} finally {
  $env:MYSQL_ENABLED = if ($requestedDbEnabled) { '1' } else { '0' }
  if ($null -eq $previousClientAsr) { Remove-Item Env:WECHAT_CLIENT_ASR -ErrorAction SilentlyContinue }
  else { $env:WECHAT_CLIENT_ASR = $previousClientAsr }
  try { Stop-Transcript | Out-Null } catch {}
}
Write-Host "Two-stage log: $logPath"
exit $exitCode
