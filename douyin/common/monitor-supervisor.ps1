# Telemetry and dedicated safe-stop controls. No task mutations or credentials in arguments.
$script:MonitorSessionId=$null
$script:MonitorHeartbeatProcess=$null
function Set-MonitorSupervisorState([string]$Phase,[string]$ResumeAt='') {
  if(-not $script:MonitorSessionId){return}
  $document=@{schemaVersion=1;supervisorPid=$PID;sessionId=$script:MonitorSessionId;state=$Phase;resumeAt=$ResumeAt;updatedAt=[DateTime]::UtcNow.ToString('o')}
  $destination=Join-Path $Worker '.state\monitor-supervisor.json'
  $temporary=$destination+'.tmp-'+$PID
  try {
    [IO.File]::WriteAllText($temporary,($document|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $destination -Force
  } catch {Write-Warning '[Monitoring] Supervisor telemetry file unavailable.'}
}
function Start-MonitorSupervisor {
  $script:MonitorSessionId=[Guid]::NewGuid().ToString()
  $env:MONITOR_WORKER_ROOT=$Worker
  Set-MonitorSupervisorState 'starting'
  $monitorScript=Join-Path $Common 'src\monitor-telemetry.mjs'
  $monitorArguments=@(('"'+$monitorScript+'"'),'--heartbeat',('"'+$Worker+'"'),[string]$PID,$script:MonitorSessionId)
  try {
    $script:MonitorHeartbeatProcess=Start-Process -FilePath $Node -ArgumentList $monitorArguments -PassThru -WindowStyle Hidden
  } catch {throw 'Remote control helper unavailable; collection will not start.'}
  $ReadyFile=Join-Path $Worker '.state\remote-control-ready.json'
  $Ready=$false
  for($Attempt=0;$Attempt -lt 20;$Attempt++){
    if($script:MonitorHeartbeatProcess.HasExited){throw 'Remote control helper exited; collection will not start.'}
    try{
      $Record=Get-Content -LiteralPath $ReadyFile -Raw -Encoding UTF8 | ConvertFrom-Json
      if($Record.sessionId -eq $script:MonitorSessionId -and $Record.supervisorPid -eq $PID){$Ready=$true;break}
    }catch{}
    Start-Sleep -Seconds 1
  }
  if(-not $Ready){throw 'Remote control readiness not confirmed; collection will not start.'}
}
function Assert-RemoteControlAvailable {
  if($script:MonitorSessionId -and (-not $script:MonitorHeartbeatProcess -or $script:MonitorHeartbeatProcess.HasExited)){
    throw 'Remote control helper exited; no further cycle is allowed. Inspect this node manually.'
  }
}
function Close-MonitorSupervisor([string]$FinalState='exit_unconfirmed') {
  try {
    Set-MonitorSupervisorState $FinalState
    if($script:MonitorHeartbeatProcess){[void]$script:MonitorHeartbeatProcess.WaitForExit(15000)}
  } catch {Write-Warning '[Monitoring] Final heartbeat unavailable; do not infer safe task completion.'}
}
