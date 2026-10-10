param([switch]$Once)

$ErrorActionPreference = 'Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $Common '..')).Path.TrimEnd('\')
$Python = if (Test-Path (Join-Path $Common 'runtime\python\python.exe')) {
  (Join-Path $Common 'runtime\python\python.exe')
} elseif ($env:WECHAT_PYTHON) {
  $env:WECHAT_PYTHON
} else {
  (Get-Command python -ErrorAction Stop).Source
}

if (-not $env:REDIS_URL) { $env:REDIS_URL = 'redis://127.0.0.1:6379/0' }
if (-not $env:REDIS_RUN_ID) { $env:REDIS_RUN_ID = '20260926-prod-01' }
if (-not $env:REDIS_PASSWORD) {
  $secure = Read-Host 'Redis password' -AsSecureString
  $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { $env:REDIS_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
if ($env:CENTRAL_LOG_ONCE -eq '1') { $Once = $true }

$Sink = Join-Path $Common 'src\redis_log_sink.py'
$Output = Join-Path $Root 'central-logs'
$State = Join-Path $Root ('.state\central-log-cursor-{0}.json' -f $env:REDIS_RUN_ID)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $State) | Out-Null
Write-Host "Redis: $env:REDIS_URL"
Write-Host "RunId: $env:REDIS_RUN_ID"
Write-Host "Central logs: $Output"
$arguments = @(
  $Sink, '--redis-url', $env:REDIS_URL, '--run-id', $env:REDIS_RUN_ID,
  '--output-root', $Output, '--state', $State
)
if ($Once) { $arguments += '--once' }
& $Python @arguments
exit $LASTEXITCODE
