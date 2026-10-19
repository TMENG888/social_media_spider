function Set-MonitorSupervisorState([string]$Phase,[string]$ResumeAt='') {}
function Start-MonitorSupervisor {}
function Assert-RemoteControlAvailable {}
function Close-MonitorSupervisor([string]$FinalState='') {}
function Start-Sleep {
  param([int]$Seconds,[int]$Milliseconds)
  if($env:XHS_TEST_SCENARIO -eq 'manual-during-rest'){
    [IO.File]::WriteAllText((Join-Path $Worker '.state\supervisor.stop'),'manual stop during rest')
    [IO.File]::WriteAllText((Join-Path $Worker '.state\stop.requested'),'manual stop during rest')
  }
}
