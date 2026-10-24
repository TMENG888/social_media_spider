[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$WorkerRoot,
  [ValidateSet('run','retry','check')][string]$Mode='run',
  [ValidateSet('redis','local')][string]$Dispatch='redis',
  [ValidateSet('auto','posts','authors')][string]$Phase='auto',
  [switch]$ExportOnly,
  [ValidateRange(0,10080)][double]$MaxRuntimeMinutes=0,
  [ValidateRange(1,1440)][int]$CycleRunMinMinutes=45,
  [ValidateRange(1,1440)][int]$CycleRunMaxMinutes=60,
  [ValidateRange(1,1440)][int]$CycleRestMinMinutes=30,
  [ValidateRange(1,1440)][int]$CycleRestMaxMinutes=60,
  [switch]$SingleCycle
)
$ErrorActionPreference='Stop'
$Common=Split-Path -Parent $MyInvocation.MyCommand.Path
$Worker=(Resolve-Path -LiteralPath $WorkerRoot).Path
$Node=Join-Path $Common 'runtime\node\node.exe'
if(-not(Test-Path -LiteralPath $Node)){$Node=(Get-Command node -ErrorAction SilentlyContinue).Source}
if(-not $Node){throw 'Node.js not found'}
if($CycleRunMinMinutes -gt $CycleRunMaxMinutes){throw 'CycleRunMinMinutes cannot exceed CycleRunMaxMinutes'}
if($CycleRestMinMinutes -gt $CycleRestMaxMinutes){throw 'CycleRestMinMinutes cannot exceed CycleRestMaxMinutes'}
$Queue=Join-Path $Worker 'tasks\task-queue.json'
$WorkerState=Join-Path $Worker '.state'
$SupervisorStop=Join-Path $WorkerState 'supervisor.stop'
$OldLocation=Get-Location
$SavedEnv=@{}
foreach($Name in @('XHS_WORKER_ROOT','XHS_DISPATCH','XHS_SKIP_IMPORT','XHS_SUPERVISOR_STOP_FILE','REDIS_URL','REDIS_USERNAME','REDIS_PASSWORD','MYSQL_USER','MYSQL_PASSWORD','MONITOR_WORKER_ROOT')){
  $SavedEnv[$Name]=[Environment]::GetEnvironmentVariable($Name,'Process')
}
. (Join-Path $Common 'monitor-supervisor.ps1')
$RemoteFinalState='exit_unconfirmed'
function Read-HiddenValue([string]$Label){
  $Secure=Read-Host $Label -AsSecureString
  $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer); $Secure.Dispose() }
}
function Read-DpapiPassword([string]$Path){
  $Cipher=(Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
  if(-not $Cipher){throw 'Encrypted Redis credential is empty.'}
  $Secure=ConvertTo-SecureString -String $Cipher
  $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer); $Secure.Dispose() }
}
function Save-DpapiPassword([string]$Path,[string]$Password){
  if(-not $Password){return}
  $Secure=ConvertTo-SecureString -String $Password -AsPlainText -Force
  try {
    $Cipher=ConvertFrom-SecureString -SecureString $Secure
    $Temporary=$Path+'.tmp-'+$PID
    $Cipher|Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $Path -Force
  } finally {$Secure.Dispose()}
}
function Complete-OwnedRuntimeStop([string]$CycleId){
  & $Node (Join-Path $Common 'src\runtime-stop.mjs') --queue $Queue --root $Common --supervisor-stop $SupervisorStop --cycle-id $CycleId | Out-Host
  return $LASTEXITCODE
}
try {
  Set-Location -LiteralPath $Common
  if(-not(Test-Path -LiteralPath $WorkerState)){New-Item -ItemType Directory -Path $WorkerState -Force|Out-Null}
  $env:XHS_WORKER_ROOT=$Common
  $env:XHS_DISPATCH=$Dispatch
  $env:XHS_SKIP_IMPORT=if($ExportOnly){'true'}else{'false'}
  $env:XHS_SUPERVISOR_STOP_FILE=$SupervisorStop
  # Preserve manual/remote/protection stops. The authenticated gate below may
  # archive only an idle node's verified control-channel failure latch.
  & $Node 'src\run-worker.mjs' '--mode' 'check' '--queue' $Queue '--dispatch' $Dispatch '--phase' $Phase
  if($LASTEXITCODE -ne 0){throw 'Environment preflight failed; collection not started.'}
  if($Mode -eq 'check'){exit 0}
  if($Dispatch -eq 'redis'){
    $RedisConfig=Get-Content -LiteralPath (Join-Path $Common 'redis-config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if(-not $env:REDIS_URL){$env:REDIS_URL=$RedisConfig.url}
    if(-not $env:REDIS_URL){$env:REDIS_URL=(Read-Host 'Redis URL (redis://host:port/0; no password in URL)').Trim()}
    if(-not $env:REDIS_URL){throw 'Redis URL is required. No fallback to local shards.'}
    if(-not $env:REDIS_USERNAME){$env:REDIS_USERNAME=$RedisConfig.username}
    if(-not $env:REDIS_USERNAME){$env:REDIS_USERNAME=(Read-Host 'Redis ACL username (Enter for default)').Trim()}
    $RedisCredentialFile=Join-Path $WorkerState 'redis-password.dpapi'
    $RedisCredentialNeedsSave=$false
    if(-not $env:REDIS_PASSWORD -and (Test-Path -LiteralPath $RedisCredentialFile)){
      try {
        $env:REDIS_PASSWORD=Read-DpapiPassword $RedisCredentialFile
        if($env:REDIS_PASSWORD){Write-Host '[Redis credential] Loaded the saved Windows-encrypted password.'}
      } catch {
        Write-Warning '[Redis credential] This Windows user cannot decrypt the saved password. Enter and save it again.'
        $env:REDIS_PASSWORD=$null
      }
    }
    if(-not $env:REDIS_PASSWORD){
      $env:REDIS_PASSWORD=Read-HiddenValue 'Redis password (hidden; saved encrypted for this Windows user)'
      $RedisCredentialNeedsSave=$true
    }
    & $Node 'src\redis-auth-check.mjs'
    $RedisAuthExitCode=$LASTEXITCODE
    if($RedisAuthExitCode -eq 2 -and -not $RedisCredentialNeedsSave){
      Write-Warning '[Redis credential] The saved/provided password was rejected. Enter the current Redis worker password.'
      $env:REDIS_PASSWORD=Read-HiddenValue 'Redis password (hidden)'
      $RedisCredentialNeedsSave=$true
      & $Node 'src\redis-auth-check.mjs'
      $RedisAuthExitCode=$LASTEXITCODE
    }
    if($RedisAuthExitCode -ne 0){throw 'Redis authentication preflight failed. No password was saved and collection was not started.'}
    if($RedisCredentialNeedsSave -and $env:REDIS_PASSWORD){
      Save-DpapiPassword $RedisCredentialFile $env:REDIS_PASSWORD
      Write-Host '[Redis credential] Verified and saved with Windows DPAPI.'
    }
  }
  if(-not $ExportOnly){
    if(-not $env:MYSQL_USER){$env:MYSQL_USER=(Read-Host 'MySQL username').Trim()}
    if(-not $env:MYSQL_PASSWORD){$env:MYSQL_PASSWORD=Read-HiddenValue 'MySQL password (hidden)'}
    if(-not $env:MYSQL_USER -or -not $env:MYSQL_PASSWORD){throw 'MySQL credentials are required.'}
  }
  if($Dispatch -eq 'redis' -and -not $ExportOnly){
    & $Node (Join-Path $Common 'src\remote-stop-control.mjs') --action gate --root $Common --worker-root $Worker --recover-control-failure yes
    if($LASTEXITCODE -ne 0){throw 'Remote stop hold or control unavailable. Collection not started.'}
    Start-MonitorSupervisor
  }
  $CycleEnabled=$Mode -eq 'run' -and $Dispatch -eq 'redis' -and -not $ExportOnly -and -not $SingleCycle -and $MaxRuntimeMinutes -eq 0
  if(Test-Path -LiteralPath $SupervisorStop){$RemoteFinalState='stopped';Write-Host '[Safe stop] Stop requested during startup; collection will not start.';exit 0}
  if(-not $CycleEnabled){
    if($Dispatch -eq 'redis' -and -not $ExportOnly){
      Set-MonitorSupervisorState 'cooldown'
      & $Node 'src\cooldown-control.mjs' '--root' $Common '--worker-root' $Worker '--action' 'wait'
      if($LASTEXITCODE -eq 20){$RemoteFinalState='stopped';exit 0}
      if($LASTEXITCODE -ne 0){throw 'Shared cooldown requires manual action or cannot be verified. Collection not started.'}
    }
    Set-MonitorSupervisorState 'collecting'
    $CycleId=[Guid]::NewGuid().ToString('N')
    & $Node 'src\run-worker.mjs' '--mode' $Mode '--queue' $Queue '--dispatch' $Dispatch '--phase' $Phase '--skip-import' $env:XHS_SKIP_IMPORT '--max-runtime-minutes' $MaxRuntimeMinutes '--cycle-id' $CycleId
    $RunExitCode=$LASTEXITCODE
    if($RunExitCode -eq 0){
      $ResumeCheck=Complete-OwnedRuntimeStop $CycleId
      if($ResumeCheck -eq 20){$RemoteFinalState='stopped'}
      elseif($ResumeCheck -ne 0){$RunExitCode=1}
    }
  } else {
    $RunExitCode=0
    $CycleNumber=0
    while($true){
      Assert-RemoteControlAvailable
      if(Test-Path -LiteralPath $SupervisorStop){Write-Host '[Cycle supervisor] Manual stop requested; no new cycle will start.';break}
      Set-MonitorSupervisorState 'cooldown'
      & $Node 'src\cooldown-control.mjs' '--root' $Common '--worker-root' $Worker '--action' 'wait'
      $CooldownExitCode=$LASTEXITCODE
      if($CooldownExitCode -eq 20){$RunExitCode=0;break}
      if($CooldownExitCode -ne 0){Write-Warning '[Cycle supervisor] Shared cooldown requires manual review or cannot be verified; no restart.';$RunExitCode=1;break}
      $CycleNumber+=1
      $CycleRuntime=Get-Random -Minimum $CycleRunMinMinutes -Maximum ($CycleRunMaxMinutes+1)
      Write-Host "[Cycle supervisor] Cycle ${CycleNumber} started; runtime=${CycleRuntime} minutes. Any unfinished task will be safely released."
      Set-MonitorSupervisorState 'collecting'
      $CycleId=[Guid]::NewGuid().ToString('N')
      & $Node 'src\run-worker.mjs' '--mode' 'run' '--queue' $Queue '--dispatch' $Dispatch '--phase' $Phase '--skip-import' $env:XHS_SKIP_IMPORT '--max-runtime-minutes' $CycleRuntime '--cycle-id' $CycleId
      $RunExitCode=$LASTEXITCODE
      if(Test-Path -LiteralPath $SupervisorStop){Write-Host '[Cycle supervisor] Stop is active; no new cycle will start.';break}
      if($RunExitCode -eq 5){Write-Warning '[Cycle supervisor] Redis lease safety stop: local data is preserved and the unfinished task was not acknowledged. Restore Redis, then start this worker again.';break}
      if($RunExitCode -eq 76){Write-Host '[Cycle supervisor] Rate limit recorded. Entering shared cooldown before any next cycle.';$RunExitCode=0;continue}
      if($RunExitCode -eq 77){Write-Warning '[Cycle supervisor] Login/CAPTCHA recorded; waiting for operator confirmation before another cycle.';$RunExitCode=0;continue}
      if($RunExitCode -ne 0){Write-Warning "[Cycle supervisor] Cycle exited abnormally (code $RunExitCode); automatic restart is disabled to prevent repeated access.";break}

      $WorkerStatusPath=Join-Path $Worker 'runs\worker_status.json'
      $LastTaskStatus=$null
      if(Test-Path -LiteralPath $WorkerStatusPath){
        try{$WorkerStatus=Get-Content -LiteralPath $WorkerStatusPath -Raw -Encoding UTF8|ConvertFrom-Json;$LastTaskStatus=@($WorkerStatus.tasks)[-1].status}catch{}
      }
      if($LastTaskStatus -in @('login_required','risk_controlled','web_unavailable','import_failed','lease_lost','confirmation_failed')){
        Write-Warning "[Cycle supervisor] Current status=$LastTaskStatus; manual action is required, so automatic restart is disabled."
        $RunExitCode=1
        break
      }

      $QueueStatusPath=Join-Path $WorkerState 'redis_queue_status.json'
      if(-not(Test-Path -LiteralPath $QueueStatusPath)){Write-Warning '[Cycle supervisor] Redis progress file is missing; automatic restart is disabled to avoid looping in an unknown state.';$RunExitCode=1;break}
      try{$QueueStatus=Get-Content -LiteralPath $QueueStatusPath -Raw -Encoding UTF8|ConvertFrom-Json}catch{Write-Warning '[Cycle supervisor] Redis progress file cannot be read; automatic restart is disabled.';$RunExitCode=1;break}
      if([int]$QueueStatus.counts.failed -gt 0){Write-Warning "[Cycle supervisor] Redis has $($QueueStatus.counts.failed) exhausted task(s); manual action is required.";$RunExitCode=1;break}
      $ResumeCheck=Complete-OwnedRuntimeStop $CycleId
      if($ResumeCheck -eq 20){$RemoteFinalState='stopped';Write-Host '[Cycle supervisor] Stop request retained; no further cycle will start.';break}
      if($ResumeCheck -ne 0){$RunExitCode=1;break}
      if([int]$QueueStatus.counts.pending -eq 0 -and [int]$QueueStatus.counts.leased -eq 0){Write-Host '[Cycle supervisor] All Redis tasks are complete; worker is stopping.';break}

      $RestMinutes=Get-Random -Minimum $CycleRestMinMinutes -Maximum ($CycleRestMaxMinutes+1)
      $ResumeAt=(Get-Date).AddMinutes($RestMinutes).ToString('yyyy-MM-dd HH:mm:ss')
      Set-MonitorSupervisorState 'resting' (Get-Date).AddMinutes($RestMinutes).ToUniversalTime().ToString('o')
      Write-Host "[Cycle supervisor] Cycle ${CycleNumber} completed; resting ${RestMinutes} minutes, scheduled to resume at ${ResumeAt}. Run the safe-stop BAT file to cancel later cycles."
      $RestSeconds=$RestMinutes*60
      for($Elapsed=0;$Elapsed -lt $RestSeconds;$Elapsed+=5){
        Assert-RemoteControlAvailable
        if(Test-Path -LiteralPath $SupervisorStop){break}
        Start-Sleep -Seconds ([Math]::Min(5,$RestSeconds-$Elapsed))
      }
      if(Test-Path -LiteralPath $SupervisorStop){Write-Host '[Cycle supervisor] Manual stop received during rest; no new cycle will start.';break}
    }
  }
  if($RunExitCode -eq 0){$RemoteFinalState='stopped'}
} finally {
  Close-MonitorSupervisor $RemoteFinalState
  foreach($Name in $SavedEnv.Keys){[Environment]::SetEnvironmentVariable($Name,$SavedEnv[$Name],'Process')}
  Set-Location -LiteralPath $OldLocation.Path
}
exit $RunExitCode
