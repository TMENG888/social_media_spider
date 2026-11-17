# Telemetry and dedicated safe-stop controls. No task mutations or credentials in arguments.
$script:MonitorSessionId=$null
$script:MonitorHeartbeatProcess=$null
$script:MonitorSupervisorLock=$null
$script:MonitorDiagnosticFile=$null
function Enter-MonitorSupervisorLock {
  if($script:MonitorSupervisorLock){return}
  $directory=Join-Path $Worker '.state'
  [void][IO.Directory]::CreateDirectory($directory)
  try {
    # Keep the handle for the entire supervisor lifetime, including rest.
    # Do not delete the lock file: unlink/recreate would allow two owners.
    $script:MonitorSupervisorLock=[IO.File]::Open((Join-Path $directory 'monitor-supervisor.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read)
  } catch {throw 'SUPERVISOR_LOCK_UNAVAILABLE: another supervisor may own this node. No state or stop flags were changed.'}
}
function Write-MonitorSupervisorDiagnostic([string]$Reason,$Code=$null) {
  $record=@{at=[DateTime]::UtcNow.ToString('o');reason=$Reason;supervisorPid=$PID;sessionId=$script:MonitorSessionId;exitCode=$Code}
  $line=$record|ConvertTo-Json -Compress
  Write-Host ('[Supervisor diagnostic] '+$line)
  try {if($script:MonitorDiagnosticFile){[IO.File]::AppendAllText($script:MonitorDiagnosticFile,$line+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))}}
  catch {Write-Warning '[Monitoring] Diagnostic persistence unavailable.'}
}
function Set-MonitorSupervisorState([string]$Phase,[string]$ResumeAt='') {
  if(-not $script:MonitorSessionId -or -not $script:MonitorSupervisorLock){return}
  $document=@{schemaVersion=1;supervisorPid=$PID;sessionId=$script:MonitorSessionId;state=$Phase;resumeAt=$ResumeAt;updatedAt=[DateTime]::UtcNow.ToString('o')}
  $destination=Join-Path $Worker '.state\monitor-supervisor.json'
  $temporary=$destination+'.tmp-'+$PID
  try {
    [IO.File]::WriteAllText($temporary,($document|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $destination -Force
    # Public display copy is independent of the authoritative supervisor file.
    try {
      $opsDirectory=Join-Path $Worker '.state\ops'
      [void][IO.Directory]::CreateDirectory($opsDirectory)
      $opsFile=Join-Path $opsDirectory 'supervisor.json'
      $opsTemporary=$opsFile+'.tmp-'+$PID
      $opsStops=@(foreach($stopName in 'supervisor.stop','stop.requested'){if(Test-Path -LiteralPath (Join-Path $Worker ('.state\'+$stopName))){$stopName}})
      $opsDocument=@{schemaVersion=1;version='ops-state-split-20261111-v1';kind='supervisor';publishedAt=[DateTime]::UtcNow.ToString('o');data=$document;stops=$opsStops}
      [IO.File]::WriteAllText($opsTemporary,($opsDocument|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
      Move-Item -LiteralPath $opsTemporary -Destination $opsFile -Force
    }catch{Write-Warning '[Monitoring] Public snapshot unavailable; collection state retained.'}

    # Append phase boundaries for hourly keyword timelines. Monitoring failure
    # must never alter collection, protection, login, or task ownership.
    try {
      $timingWord=''
      $timingStatusFile=Join-Path $Worker 'runs\worker_status.json'
      if(Test-Path -LiteralPath $timingStatusFile){
        $timingStatus=Get-Content -LiteralPath $timingStatusFile -Raw -Encoding UTF8|ConvertFrom-Json
        if($timingStatus.currentKeyword){$timingWord=[string]$timingStatus.currentKeyword}
        elseif($timingStatus.tasks.Count){$timingWord=[string]$timingStatus.tasks[-1].keyword}
      }
      $timingRecord=@{at=$document.updatedAt;state=$Phase;resumeAt=$ResumeAt;keyword=$timingWord;sessionId=$script:MonitorSessionId;supervisorPid=$PID;version='keyword-timing-20261106-v1'}
      $timingFile=Join-Path $Worker ('runs\supervisor-state-'+$script:MonitorSessionId+'.jsonl')
      [IO.File]::AppendAllText($timingFile,($timingRecord|ConvertTo-Json -Compress)+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
    }catch{Write-Warning '[Monitoring] Timeline state boundary unavailable.'}

  } catch {Write-Warning '[Monitoring] Supervisor telemetry file unavailable.'}
}
function Start-MonitorSupervisor {
  Enter-MonitorSupervisorLock
  if($script:MonitorHeartbeatProcess){throw 'MONITOR_ALREADY_STARTED'}
  $script:MonitorSessionId=[Guid]::NewGuid().ToString()
  $logDirectory=Join-Path $Worker 'runs'
  [void][IO.Directory]::CreateDirectory($logDirectory)
  $script:MonitorDiagnosticFile=Join-Path $logDirectory ('supervisor-'+$script:MonitorSessionId+'.jsonl')
  $env:MONITOR_WORKER_ROOT=$Worker
  Set-MonitorSupervisorState 'starting'
  $monitorScript=Join-Path $Common 'src\monitor-telemetry.mjs'
  $monitorArguments=@(('"'+$monitorScript+'"'),'--heartbeat',('"'+$Worker+'"'),[string]$PID,$script:MonitorSessionId)
  try {
    $script:MonitorHeartbeatProcess=Start-Process -FilePath $Node -ArgumentList $monitorArguments -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory ('monitor-helper-'+$script:MonitorSessionId+'.stdout.log')) -RedirectStandardError (Join-Path $logDirectory ('monitor-helper-'+$script:MonitorSessionId+'.stderr.log'))
    # Windows PowerShell may otherwise lose ExitCode after a fast child exit.
    $null=$script:MonitorHeartbeatProcess.Handle
    Write-MonitorSupervisorDiagnostic 'helper_started'
  } catch {Write-MonitorSupervisorDiagnostic 'helper_start_failed';throw 'Remote control helper unavailable; collection will not start.'}
  $ReadyFile=Join-Path $Worker '.state\remote-control-ready.json'
  $Ready=$false
  for($Attempt=0;$Attempt -lt 120;$Attempt++){
    Assert-RemoteControlAvailable
    try{
      $Record=Get-Content -LiteralPath $ReadyFile -Raw -Encoding UTF8 | ConvertFrom-Json
      if($Record.sessionId -eq $script:MonitorSessionId -and $Record.supervisorPid -eq $PID){$Ready=$true;break}
    }catch{}
    Start-Sleep -Seconds 1
  }
  if(-not $Ready){Write-MonitorSupervisorDiagnostic 'helper_readiness_timeout';throw 'Remote control readiness not confirmed; collection will not start.'}
}
function Assert-RemoteControlAvailable {
  if($script:MonitorSessionId -and (-not $script:MonitorHeartbeatProcess -or $script:MonitorHeartbeatProcess.HasExited)){
    $helperCode=if($script:MonitorHeartbeatProcess){$script:MonitorHeartbeatProcess.ExitCode}else{$null}
    Write-MonitorSupervisorDiagnostic 'helper_exited' $helperCode
    throw ('Remote control helper exited (code '+$helperCode+'); no further cycle is allowed. Inspect the session diagnostic logs.')
  }
}
function Close-MonitorSupervisor([string]$FinalState='exit_unconfirmed') {
  try {
    Set-MonitorSupervisorState $FinalState
    if($script:MonitorHeartbeatProcess){
      if(-not $script:MonitorHeartbeatProcess.WaitForExit(15000)){
        # A stalled old helper must not outlive the ownership lock.
        Write-MonitorSupervisorDiagnostic 'helper_close_timeout'
        $script:MonitorHeartbeatProcess.Kill()
        [void]$script:MonitorHeartbeatProcess.WaitForExit(5000)
      }
    }
  } catch {Write-Warning '[Monitoring] Final heartbeat unavailable; do not infer safe task completion.'}
  finally {
    if($script:MonitorSupervisorLock){$script:MonitorSupervisorLock.Dispose();$script:MonitorSupervisorLock=$null}
    $script:MonitorHeartbeatProcess=$null
    $script:MonitorSessionId=$null
  }
}


# Called only between workers; no live collector or task lease is reused.
function Wait-ControlFailureRecovery {
  $RecoveryScript=Join-Path $Common 'src\connection-recovery.mjs'
  $RecoveryArgs=@('--root',$Common,'--worker-root',$Worker)
  & $Node $RecoveryScript @RecoveryArgs --action inspect | Out-Host
  $InspectExit=$LASTEXITCODE
  if($InspectExit -ne 10){return $false}
  $Attempt=0
  while($true){
    Assert-RemoteControlAvailable
    Set-MonitorSupervisorState 'reconnecting'
    $OwnerArgs=@()
    if($script:MonitorSessionId){$OwnerArgs=@('--supervisor-pid',[string]$PID,'--session',$script:MonitorSessionId)}
    & $Node $RecoveryScript @RecoveryArgs @OwnerArgs --action recover | Out-Host
    $RecoveryExit=$LASTEXITCODE
    Write-MonitorSupervisorDiagnostic 'connection_recovery_attempt' $RecoveryExit
    if($RecoveryExit -eq 0){Write-Host '[Connection recovery] Ready for original protection gate and a fresh task lease.';return $true}
    if($RecoveryExit -eq 40){
      $Attempt=0
      $Delay=15
      Write-MonitorSupervisorDiagnostic 'network_wait_no_redis_retry' 40
    }elseif($RecoveryExit -eq 30){
      if($Attempt -ge 3){Write-Warning '[Connection recovery] Network is available but Redis verification exhausted three retries; flags retained for review.';return $false}
      $Delay=@(30,60,120)[$Attempt]
      $Attempt++
    }else{Write-Warning '[Connection recovery] Protected stop or local state requires review.';return $false}
    Write-Host "[Connection recovery] Waiting $Delay seconds before fresh verification; no collection while waiting."
    for($Waited=0;$Waited -lt $Delay;$Waited+=5){
      Assert-RemoteControlAvailable
      & $Node $RecoveryScript @RecoveryArgs --action inspect | Out-Host
      if($LASTEXITCODE -ne 10){return $false}
      Start-Sleep -Seconds ([Math]::Min(5,$Delay-$Waited))
    }
  }
}
