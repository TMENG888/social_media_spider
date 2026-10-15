param([ValidateSet('run','retry','check')][string]$Mode='run')

$ErrorActionPreference = 'Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Common '..')
$WorkerRoot = if ($env:WECHAT_WORKER_ROOT) {
  (Resolve-Path $env:WECHAT_WORKER_ROOT).Path.TrimEnd('\')
} else {
  $Root.Path.TrimEnd('\')
}
$WorkerId = Split-Path $WorkerRoot -Leaf

# For live collection, let the operator choose one of the two calibrated
# primary-display profiles. WECHAT_DISPLAY_PROFILE can bypass the prompt for
# an unattended restart while retaining the same validation.
if ($Mode -ne 'check') {
  if (-not $env:WECHAT_DISPLAY_PROFILE) {
    Write-Host 'Select primary display profile before starting WeChat RPA:'
    Write-Host '  1 = 2560x1440'
    Write-Host '  2 = 1920x1080'
    Write-Host '  0 = Cancel'
    $displayChoice = Read-Host 'Display profile (1/2/0)'
    switch ($displayChoice) {
      '1' { $env:WECHAT_DISPLAY_PROFILE = '2560x1440' }
      '2' { $env:WECHAT_DISPLAY_PROFILE = '1920x1080' }
      '0' { Write-Host 'Cancelled by user.'; exit 10 }
      default { Write-Host 'Invalid display profile selection.' -ForegroundColor Red; exit 11 }
    }
  }
  if ($env:WECHAT_DISPLAY_PROFILE -notin @('2560x1440','1920x1080')) {
    throw "Unsupported WECHAT_DISPLAY_PROFILE: $env:WECHAT_DISPLAY_PROFILE"
  }
  $displayScript = Join-Path $Common 'set-display-profile.ps1'
  $displayPowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
  $displayText = (& $displayPowerShell -NoProfile -ExecutionPolicy Bypass -File $displayScript -Profile $env:WECHAT_DISPLAY_PROFILE | Out-String).Trim()
  $displayExit = $LASTEXITCODE
  if ($displayText) { Write-Host $displayText }
  if ($displayExit -ne 0) { throw "Display profile setup failed with exit code $displayExit." }
  $displayResult = $displayText | ConvertFrom-Json
  $env:WECHAT_DISPLAY_WIDTH = [string]$displayResult.current.Split('x')[0]
  $env:WECHAT_DISPLAY_HEIGHT = [string]$displayResult.current.Split('x')[1]
  $env:WECHAT_DISPLAY_SCALE = [string]$displayResult.scalePercent
}

# Obtain credentials before transcription starts. The password is therefore
# never written to the daily diagnostic log, even on older PowerShell hosts.
if ($Mode -ne 'check' -and $env:MYSQL_ENABLED -ne '0') {
  if (-not $env:MYSQL_HOST) { $env:MYSQL_HOST = '127.0.0.1' }
  if (-not $env:MYSQL_PORT) { $env:MYSQL_PORT = '3306' }
  if (-not $env:MYSQL_DATABASE) { $env:MYSQL_DATABASE = 'social' }
  if (-not $env:MYSQL_USER) { $env:MYSQL_USER = Read-Host 'MySQL username' }
  if (-not $env:MYSQL_PASSWORD) {
    $securePassword = Read-Host 'MySQL password' -AsSecureString
    $passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try { $env:MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr) }
  }
  if (-not $env:MYSQL_USER -or -not $env:MYSQL_PASSWORD) {
    throw 'MySQL username and password are required.'
  }
}

$LogDirectory = Join-Path $WorkerRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$LogDate = Get-Date -Format 'yyyy-MM-dd'
$LogPath = Join-Path $LogDirectory ("channels-worker-{0}.log" -f $LogDate)
$RunScript = Join-Path $Common 'run-worker.ps1'
$PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$ExitCode = 1
$TranscriptStarted = $false

try {
  Start-Transcript -LiteralPath $LogPath -Append -Force | Out-Null
  $TranscriptStarted = $true
  Write-Host ('=' * 72)
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] WeChat worker session started"
  Write-Host "Worker: $WorkerId"
  Write-Host "Mode: $Mode"
  Write-Host "Computer: $env:COMPUTERNAME"
  Write-Host "ProcessId: $PID"
  Write-Host "DisplayProfile: $env:WECHAT_DISPLAY_PROFILE"
  Write-Host "DisplayActual: $($env:WECHAT_DISPLAY_WIDTH)x$($env:WECHAT_DISPLAY_HEIGHT) scale=$($env:WECHAT_DISPLAY_SCALE)%"
  Write-Host "PackageRoot: $Root"
  Write-Host "WorkerRoot: $WorkerRoot"
  Write-Host "DailyLog: $LogPath"
  Write-Host ('-' * 72)

  # Run the collector in a child PowerShell host so its explicit exit codes do
  # not bypass this wrapper's finally block. All child stdout/stderr, including
  # Python/Node output and exception stacks, is captured by the transcript.
  & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $RunScript -Mode $Mode
  $ExitCode = $LASTEXITCODE
  Write-Host ('-' * 72)
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] WeChat worker session finished; exitCode=$ExitCode"
} catch {
  $ExitCode = 1
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] Wrapper failure: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host $_.ScriptStackTrace -ForegroundColor Red
} finally {
  if ($TranscriptStarted) {
    try { Stop-Transcript | Out-Null } catch { }
  }
}

Write-Host "Daily diagnostic log: $LogPath"
exit $ExitCode
