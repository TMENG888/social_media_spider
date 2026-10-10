[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WorkerRoot,[ValidateSet('auto','posts','authors')][string]$Phase='auto',[switch]$Check,[switch]$SingleCycle,[switch]$Test,[int]$Limit=10)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Text.UTF8Encoding]::new($false)
$Common=$PSScriptRoot
$Worker=(Resolve-Path -LiteralPath $WorkerRoot).Path
$Node=Join-Path $Common 'runtime\node\node.exe'
$State=Join-Path $Worker '.state'
New-Item -ItemType Directory -Path $State -Force | Out-Null
$Stop=Join-Path $State 'stop.requested'
$SupervisorStop=Join-Path $State 'supervisor.stop'
$SavedEnv=@{}
foreach($Name in @('MYSQL_USER','MYSQL_PASSWORD','REDIS_PASSWORD','REDIS_URL','REDIS_USERNAME','DY_WORKER_ROOT','DY_DISPATCH','DY_LEASE_FILE','DY_LEASE_TASK_ID','DY_LEASE_TOKEN','DY_LEASE_CAMPAIGN')){$SavedEnv[$Name]=[Environment]::GetEnvironmentVariable($Name,'Process')}
function HiddenValue([string]$Label){
  $Secure=Read-Host $Label -AsSecureString
  $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try{return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)}
  finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer);$Secure.Dispose()}
}
try {
  & $Node (Join-Path $Common 'src\run-worker.mjs') --worker-root $Worker --preflight
  if($LASTEXITCODE -ne 0){throw 'Environment preflight failed. Collection not started.'}
  if($Check){exit 0}
  if(-not $Test){
    $Credential=Join-Path $State 'redis-password.dpapi'
    if(-not $env:REDIS_PASSWORD -and (Test-Path -LiteralPath $Credential)){
      $Cipher=(Get-Content -LiteralPath $Credential -Raw -Encoding UTF8).Trim()
      $Secure=ConvertTo-SecureString -String $Cipher
      $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
      try{$env:REDIS_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)}
      finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer);$Secure.Dispose()}
    }
    if(-not $env:REDIS_PASSWORD){$env:REDIS_PASSWORD=HiddenValue 'Redis password (hidden)'}
    & $Node (Join-Path $Common 'src\redis-auth-check.mjs')
    if($LASTEXITCODE -ne 0){throw 'Redis verification failed. Collection not started.'}
  }
  if(-not $env:MYSQL_USER){$env:MYSQL_USER='social_user'}
  if(-not $env:MYSQL_PASSWORD){$env:MYSQL_PASSWORD=HiddenValue 'MySQL password (hidden)'}
  if(-not $env:MYSQL_PASSWORD){throw 'MySQL password cannot be empty.'}
  Remove-Item -LiteralPath $Stop,$SupervisorStop -Force -ErrorAction SilentlyContinue
  $Cycle=0
  while($true){
    if(Test-Path -LiteralPath $SupervisorStop){break}
    $Cycle++
    $Minutes=Get-Random -Minimum 45 -Maximum 61
    Write-Host "[Cycle supervisor] Cycle $Cycle starts; runtime=$Minutes minutes."
    $WorkerArgs=@((Join-Path $Common 'src\run-worker.mjs'),'--worker-root',$Worker,'--phase',$Phase,'--max-runtime-minutes',[string]$Minutes)
    if($Test){$WorkerArgs+=@('--test','--limit',[string]$Limit,'--max-runtime-minutes','90')}
    & $Node @WorkerArgs
    if($LASTEXITCODE -ne 0){throw 'Worker exited abnormally. Automatic restart is disabled.'}
    if($SingleCycle -or $Test -or (Test-Path -LiteralPath $SupervisorStop)){break}
    $Status=Get-Content -LiteralPath (Join-Path $Worker 'runs\worker_status.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if($Status.status -eq 'completed' -and $Status.authors.status -eq 'completed'){Write-Host 'All post and author tasks completed.';break}
    $Rest=Get-Random -Minimum 30 -Maximum 61
    $Resume=(Get-Date).AddMinutes($Rest)
    Write-Host "[Cycle supervisor] Resting $Rest minutes. Resume at $Resume."
    while((Get-Date) -lt $Resume){if(Test-Path -LiteralPath $SupervisorStop){break};Start-Sleep -Milliseconds 500}
    if(Test-Path -LiteralPath $SupervisorStop){break}
    Remove-Item -LiteralPath $Stop -Force -ErrorAction SilentlyContinue
  }
} finally {foreach($Name in $SavedEnv.Keys){[Environment]::SetEnvironmentVariable($Name,$SavedEnv[$Name],'Process')}}
