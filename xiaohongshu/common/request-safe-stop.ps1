[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WorkerRoot)
$ErrorActionPreference='Stop'
$Worker=(Resolve-Path -LiteralPath $WorkerRoot.Trim().Trim('"')).Path
$State=Join-Path $Worker '.state'
New-Item -ItemType Directory -Path $State -Force|Out-Null
# Write the supervisor flag first: a concurrently starting cycle must not clear
# the collector stop flag after the user has requested a manual stop.
foreach($Name in @('supervisor.stop','stop.requested')){
  $Target=Join-Path $State $Name
  $Temporary=$Target+'.tmp-'+$PID
  [IO.File]::WriteAllText($Temporary,('manual stop '+(Get-Date -Format o)),[Text.Encoding]::ASCII)
  Move-Item -LiteralPath $Temporary -Destination $Target -Force
  if(-not(Test-Path -LiteralPath $Target -PathType Leaf)){throw "Stop flag was not saved: $Target"}
}
Write-Host "[Safe stop] Request saved for $Worker"
Write-Host '[Safe stop] No further notes or cycles will start after the current note finishes.'
Write-Host '[Safe stop] Current ASR/import may finish; remaining ASR jobs stay in the checkpoint.'
Write-Host '[Safe stop] This is a request, not an immediate forced termination. Keep the collector window open.'
