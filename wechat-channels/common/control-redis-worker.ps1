param(
  [ValidateSet('status','stop','resume')][string]$Action='status',
  [string]$Computer,
  [string]$Worker,
  [string]$CommandId,
  [string]$Reason='operator requested safe stop',
  [string]$RedisUrl='redis://127.0.0.1:6379/0',
  [string]$RunId='20260926-prod-01'
)
$ErrorActionPreference='Stop'
$Common = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Common
$Python = Join-Path $Common 'runtime\python\python.exe'
$Script = Join-Path $Common 'src\redis_worker_control.py'
$Credential = Join-Path $Root 'worker-01\.credentials\redis-password.txt'
$CliArgs = @($Script,$Action,'--redis-url',$RedisUrl,'--run-id',$RunId)
if (Test-Path -LiteralPath $Credential) { $CliArgs += @('--password-file',$Credential) }
if ($Action -ne 'status') {
  if (-not $Computer) { $Computer = Read-Host 'Exact target computer name' }
  if (-not $Worker) { $Worker = Read-Host 'Exact worker ID (worker-01/02/03)' }
  if (-not $Computer -or -not $Worker) { throw 'Exact computer and worker are required.' }
  if ($Action -eq 'resume' -and -not $CommandId) { $CommandId = Read-Host 'Stop commandId from status' }
  $Confirmation = Read-Host "Confirm $Action for $Computer / $Worker by typing YES"
  if ($Confirmation -cne 'YES') { Write-Host 'Cancelled.'; exit 10 }
  $CliArgs += @('--computer',$Computer,'--worker',$Worker,'--reason',$Reason)
  if ($Action -eq 'resume') { $CliArgs += @('--command-id',$CommandId) }
}
& $Python @CliArgs
exit $LASTEXITCODE
