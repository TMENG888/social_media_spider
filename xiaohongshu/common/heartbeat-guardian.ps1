param(
 [Parameter(Mandatory=$true)][string]$Common,
 [Parameter(Mandatory=$true)][string]$Worker,
 [Parameter(Mandatory=$true)][string]$Node,
 [Parameter(Mandatory=$true)][int]$SupervisorPid,
 [Parameter(Mandatory=$true)][string]$SessionId,
 [switch]$ObserveStopped,
 [ValidateRange(0,120)][int]$TestLifetimeSeconds=0
)
# Monitoring only: never starts a collector, clears a stop, or changes a lease.
$ErrorActionPreference='Stop'
$guardianStarted=[DateTimeOffset]::UtcNow
$Common=[IO.Path]::GetFullPath($Common);$Worker=[IO.Path]::GetFullPath($Worker)
if((Split-Path $Common -Parent) -ne (Split-Path $Worker -Parent) -or (Split-Path $Worker -Leaf) -notmatch '^worker-\d{2}$' -or $SessionId -notmatch '^[a-f0-9-]{36}$' -or $SupervisorPid -lt 1){throw 'GUARDIAN_TARGET_INVALID'}
$stateDir=Join-Path $Worker '.state';$runs=Join-Path $Worker 'runs'
[void][IO.Directory]::CreateDirectory($runs)
$journal=Join-Path $runs ('heartbeat-guardian-'+$SessionId+'.jsonl')
$statusFile=Join-Path $stateDir 'heartbeat-guardian.json'
$script:ownedChild=$null;$script:attempt=0;$script:locked=$false;$script:reason='starting'
function Write-GuardianEvent([string]$Event,$Details=@{}) {
 $r=[ordered]@{at=[DateTimeOffset]::UtcNow.ToString('o');event=$Event;guardianPid=$PID;supervisorPid=$SupervisorPid;sessionId=$SessionId;attempt=$script:attempt}
 foreach($k in $Details.Keys){$r[$k]=$Details[$k]}
 try{[IO.File]::AppendAllText($journal,($r|ConvertTo-Json -Compress)+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))}catch{}
}
function Read-GuardianState {try{return (Get-Content -LiteralPath (Join-Path $stateDir 'monitor-supervisor.json') -Raw -Encoding UTF8|ConvertFrom-Json)}catch{return $null}}
function Current-GuardianOwner($s){return $s -and $s.sessionId -eq $SessionId -and $s.supervisorPid -eq $SupervisorPid}
function Write-GuardianStatus([string]$Phase){
 $r=@{schemaVersion=1;guardianPid=$PID;supervisorPid=$SupervisorPid;sessionId=$SessionId;phase=$Phase;helperPid=if($script:ownedChild){$script:ownedChild.Id}else{$null};attempt=$script:attempt;updatedAt=[DateTimeOffset]::UtcNow.ToString('o');source='heartbeat_guardian'}
 try{$tmp=$statusFile+'.tmp-'+$PID;[IO.File]::WriteAllText($tmp,($r|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false));Move-Item -LiteralPath $tmp -Destination $statusFile -Force}catch{Write-GuardianEvent 'status_write_failed' @{errorClass=$_.Exception.GetType().Name;hresult=$_.Exception.HResult}}
}
function Stop-OwnedHelper([string]$Why){
 if($script:ownedChild){
  try{if(-not $script:ownedChild.HasExited){Write-GuardianEvent 'owned_helper_termination' @{helperPid=$script:ownedChild.Id;reason=$Why};$script:ownedChild.Kill();[void]$script:ownedChild.WaitForExit(5000)}}catch{Write-GuardianEvent 'owned_helper_termination_failed' @{errorClass=$_.Exception.GetType().Name}}
  $script:ownedChild.Dispose();$script:ownedChild=$null
 }
}
$hash=[Security.Cryptography.SHA256]::Create()
try{$key=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Worker.ToLowerInvariant())))).Replace('-','')}finally{$hash.Dispose()}
$mutex=[Threading.Mutex]::new($false,('Global\CodexHeartbeatGuardian-'+$key))
try {
 try{$script:locked=$mutex.WaitOne(10000)}catch [Threading.AbandonedMutexException]{$script:locked=$true;Write-GuardianEvent 'abandoned_guardian_lock_recovered'}
 if(-not $script:locked){Write-GuardianEvent 'guardian_already_active';exit 0}
 $s=Read-GuardianState
 if(-not(Current-GuardianOwner $s)){Write-GuardianEvent 'owner_mismatch';exit 2}
 Write-GuardianEvent 'guardian_started' @{observeStopped=[bool]$ObserveStopped;restartDelaysSeconds=@(5,15,30);maxRestartsIn15Minutes=3;hangBudgetSeconds=330}
 $failures=[Collections.Generic.List[DateTimeOffset]]::new();$lastHealth=[DateTimeOffset]::MinValue;$pendingSince=$null
 while($true){
  $now=[DateTimeOffset]::UtcNow
  if($TestLifetimeSeconds -gt 0 -and ($now-$guardianStarted).TotalSeconds -ge $TestLifetimeSeconds){$script:reason='test_lifetime_reached';break}
  $s=Read-GuardianState
  if(-not(Current-GuardianOwner $s)){$script:reason='supervisor_identity_changed';break}
  $parent=Get-Process -Id $SupervisorPid -ErrorAction SilentlyContinue
  if(-not $ObserveStopped -and ($s.state -in @('stopped','exit_unconfirmed') -or -not $parent)){$script:reason=if($parent){'supervisor_terminal_state'}else{'supervisor_not_alive'};break}
  if($ObserveStopped -and ($s.state -notin @('stopped','exit_unconfirmed') -or $parent)){$script:reason='stopped_observation_no_longer_valid';break}
  $progress=$null
  try{$progress=Get-Content -LiteralPath (Join-Path $stateDir 'monitor-helper-progress.json') -Raw -Encoding UTF8|ConvertFrom-Json}catch{}
  if($script:ownedChild -and $script:ownedChild.HasExited){
   $null=$script:ownedChild.WaitForExit(1000)
   Write-GuardianEvent 'helper_exited' @{helperPid=$script:ownedChild.Id;exitCode=$script:ownedChild.ExitCode;lastStage=if($progress -and $progress.pid -eq $script:ownedChild.Id){$progress.stage}else{$null};lastProgressAt=if($progress){$progress.at}else{$null}}
   $script:ownedChild.Dispose();$script:ownedChild=$null;$failures.Add($now);$pendingSince=$now
  }
  if($script:ownedChild){
   $matchingProgress=$progress -and $progress.pid -eq $script:ownedChild.Id -and $progress.sessionId -eq $SessionId
   $lastProgress=if($matchingProgress){[DateTimeOffset]::Parse($progress.at)}else{[DateTimeOffset]$script:ownedChild.StartTime.ToUniversalTime()}
   $age=($now-$lastProgress).TotalSeconds
   if($age -gt 330){Write-GuardianEvent 'helper_stalled' @{helperPid=$script:ownedChild.Id;lastStage=$progress.stage;lastProgressAt=$progress.at;staleSeconds=[int]$age};Stop-OwnedHelper 'progress_stalled';$failures.Add($now);$pendingSince=$now}
  }
  while($failures.Count -gt 0 -and ($now-$failures[0]).TotalMinutes -gt 15){$failures.RemoveAt(0)}
  if(-not $script:ownedChild){
   if($failures.Count -ge 4){
    Write-GuardianStatus 'recovery_cooldown'
    if(($now-$lastHealth).TotalSeconds -ge 60){Write-GuardianEvent 'restart_budget_wait' @{failuresIn15Minutes=$failures.Count;retryAfterSeconds=[int][Math]::Max(1,900-($now-$failures[0]).TotalSeconds)};$lastHealth=$now}
    Start-Sleep -Seconds 3;continue
   }
   $delay=if($failures.Count -eq 0){0}elseif($failures.Count -eq 1){5}elseif($failures.Count -eq 2){15}else{30}
   if($pendingSince -and ($now-$pendingSince).TotalSeconds -lt $delay){Write-GuardianStatus 'restart_wait';Start-Sleep -Seconds 1;continue}
   $script:attempt++
   $tag=$script:attempt.ToString()+'-'+[guid]::NewGuid().ToString('N')
   $args=@(('"'+(Join-Path $Common 'src\monitor-telemetry.mjs')+'"'),$(if($ObserveStopped){'--observe-stopped'}else{'--heartbeat'}),('"'+$Worker+'"'),[string]$SupervisorPid,$SessionId,[string]$PID)
   try{
    $script:ownedChild=Start-Process -FilePath $Node -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runs ('heartbeat-child-'+$SessionId+'-'+$tag+'.stdout.log')) -RedirectStandardError (Join-Path $runs ('heartbeat-child-'+$SessionId+'-'+$tag+'.stderr.log'))
    $null=$script:ownedChild.Handle;Write-GuardianEvent 'helper_started' @{helperPid=$script:ownedChild.Id;mode=$(if($ObserveStopped){'stopped_observer'}else{'supervisor_heartbeat'})};$pendingSince=$null
   }catch{Write-GuardianEvent 'helper_start_failed' @{errorClass=$_.Exception.GetType().Name;hresult=$_.Exception.HResult};$script:ownedChild=$null;$failures.Add($now);$pendingSince=$now}
  }
  Write-GuardianStatus 'monitoring'
  if(($now-$lastHealth).TotalSeconds -ge 60){Write-GuardianEvent 'guardian_health' @{helperPid=if($script:ownedChild){$script:ownedChild.Id}else{$null};lastStage=if($progress){$progress.stage}else{$null};lastProgressAt=if($progress){$progress.at}else{$null}};$lastHealth=$now}
  Start-Sleep -Seconds 3
 }
}catch{Write-GuardianEvent 'guardian_failed' @{errorClass=$_.Exception.GetType().Name;hresult=$_.Exception.HResult};$script:reason='guardian_failed';throw}
finally{
 if($script:locked){Stop-OwnedHelper $script:reason;Write-GuardianStatus 'stopped';Write-GuardianEvent 'guardian_exited' @{reason=$script:reason};$mutex.ReleaseMutex()}
 $mutex.Dispose()
}
