[CmdletBinding()]
param([switch]$Once,[switch]$SelfTest,[switch]$Check,[switch]$Resolve,[string]$Platform,[string]$Machine,[string]$WorkerId,[string]$IncidentId)
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$IncidentMutex=New-Object System.Threading.Mutex($false,'Local\SocialCollectorIncidentRelayV1')
$IncidentLocked=$false
$IncidentSaved=@{}
foreach($IncidentName in @('FEISHU_WEBHOOK','FEISHU_SIGN_SECRET','MONITOR_XHS_PASSWORD','MONITOR_DY_PASSWORD','PYTHONUTF8','PYTHONIOENCODING')){
 $IncidentSaved[$IncidentName]=[Environment]::GetEnvironmentVariable($IncidentName,'Process')
}
try{
 if(-not $SelfTest -and -not $Resolve -and -not $Check){
  try{$IncidentLocked=$IncidentMutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$IncidentLocked=$true}
  if(-not $IncidentLocked){Write-Host 'Incident relay already running.';exit 0}
 }
 $IncidentConfig=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8|ConvertFrom-Json
 . (Join-Path $PSScriptRoot 'monitor-paths.ps1')
 $IncidentBot=Import-Clixml -LiteralPath (Join-Path $PSScriptRoot '.credentials\feishu-bot.xml')
 $env:FEISHU_WEBHOOK=([PSCredential]::new('webhook',$IncidentBot.Webhook)).GetNetworkCredential().Password
 if($IncidentBot.SignSecret -and $IncidentBot.SignSecret.Length -gt 0){$env:FEISHU_SIGN_SECRET=([PSCredential]::new('sign',$IncidentBot.SignSecret)).GetNetworkCredential().Password}
 foreach($IncidentEntry in @(@('小红书','xiaohongshu','MONITOR_XHS_PASSWORD'),@('抖音','douyin','MONITOR_DY_PASSWORD'))){
  $IncidentDirectory=$IncidentEntry[1]
  if($IncidentConfig.platform_directories -and $IncidentConfig.platform_directories.($IncidentEntry[0])){$IncidentDirectory=$IncidentConfig.platform_directories.($IncidentEntry[0])}
  $IncidentCredential=Join-Path (Get-MonitorPlatformRoot -MonitorRoot $PSScriptRoot -PlatformName $IncidentEntry[0] -Config $IncidentConfig) 'worker-01\.state\redis-password.dpapi'
  $IncidentSecure=ConvertTo-SecureString -String (Get-Content -LiteralPath $IncidentCredential -Raw -Encoding UTF8).Trim()
  try{[Environment]::SetEnvironmentVariable($IncidentEntry[2],([PSCredential]::new('redis',$IncidentSecure)).GetNetworkCredential().Password,'Process')}
  finally{$IncidentSecure.Dispose()}
 }
 $env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'
 $IncidentPython=Join-Path (Get-MonitorPlatformRoot -MonitorRoot $PSScriptRoot -PlatformName '视频号' -Config $IncidentConfig) 'common\runtime\python\python.exe'
 $IncidentArgs=@((Join-Path $PSScriptRoot 'incident-relay.py'))
 if($SelfTest){$IncidentArgs=@((Join-Path $PSScriptRoot 'incident-selftest.py'))}
 if($Resolve){
  if(-not $Platform -or -not $Machine -or -not $WorkerId -or -not $IncidentId){throw 'Resolve requires exact Platform, Machine, WorkerId and IncidentId from the alert.'}
  $IncidentArgs=@((Join-Path $PSScriptRoot 'resolve-incident.py'),'--platform',$Platform,'--machine',$Machine,'--worker',$WorkerId,'--incident-id',$IncidentId)
 }
 if($Once){$IncidentArgs+='--once'}
 if($Check){$IncidentArgs+='--check'}
 & $IncidentPython @IncidentArgs
 $IncidentExit=$LASTEXITCODE
}finally{
 foreach($IncidentName in $IncidentSaved.Keys){[Environment]::SetEnvironmentVariable($IncidentName,$IncidentSaved[$IncidentName],'Process')}
 if($IncidentLocked){$IncidentMutex.ReleaseMutex()};$IncidentMutex.Dispose()
}
exit $IncidentExit
