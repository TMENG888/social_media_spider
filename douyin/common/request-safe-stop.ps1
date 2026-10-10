param([Parameter(Mandatory=$true)][string]$WorkerRoot)
$ErrorActionPreference='Stop'
$Worker=(Resolve-Path -LiteralPath $WorkerRoot).Path
$State=Join-Path $Worker '.state'
New-Item -ItemType Directory -Path $State -Force | Out-Null
foreach($Name in @('supervisor.stop','stop.requested')){[IO.File]::WriteAllText((Join-Path $State $Name),(Get-Date).ToString('o'),[Text.UTF8Encoding]::new($false))}
Write-Host 'Safe stop requested. The current operation will finish; no new posts, tasks or later cycles will start.'
