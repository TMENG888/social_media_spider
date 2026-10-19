[CmdletBinding()]
param([string]$WorkerRoot,[switch]$NoPrompt)
$ErrorActionPreference='Stop'
$DbCommon=$PSScriptRoot
if(-not $WorkerRoot){$WorkerRoot=Join-Path (Split-Path -Parent $DbCommon) 'worker-01'}
$DbNode=Join-Path $DbCommon 'runtime\node\node.exe'
if(-not(Test-Path -LiteralPath $DbNode)){$DbNode=(Get-Command node -ErrorAction Stop).Source}
$DbSaved=@{}
foreach($DbName in @('MYSQL_HOST','MYSQL_PORT','MYSQL_DATABASE','MYSQL_USER','MYSQL_PASSWORD')){$DbSaved[$DbName]=[Environment]::GetEnvironmentVariable($DbName,'Process')}
try{
 $DbDefaults=Get-Content -LiteralPath (Join-Path $DbCommon 'src\mysql-defaults.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $DbHostSource=if($env:MYSQL_HOST){'environment'}else{'mysql-defaults.json'}
 if(-not $env:MYSQL_HOST){$env:MYSQL_HOST=[string]$DbDefaults.host}
 if(-not $env:MYSQL_PORT){$env:MYSQL_PORT=[string]$DbDefaults.port}
 if(-not $env:MYSQL_DATABASE){$env:MYSQL_DATABASE=[string]$DbDefaults.database}
 $DbCredentialFile=Join-Path $WorkerRoot '.credentials\mysql-retry-credential.xml'
 if((-not $env:MYSQL_USER -or -not $env:MYSQL_PASSWORD) -and (Test-Path -LiteralPath $DbCredentialFile)){
  $DbCredential=Import-Clixml -LiteralPath $DbCredentialFile
  if(-not $env:MYSQL_USER){$env:MYSQL_USER=$DbCredential.UserName}
  if(-not $env:MYSQL_PASSWORD){$env:MYSQL_PASSWORD=$DbCredential.GetNetworkCredential().Password}
 }
 if(-not $NoPrompt){
  if(-not $env:MYSQL_USER){$env:MYSQL_USER=Read-Host 'MySQL username'}
  if(-not $env:MYSQL_PASSWORD){
   $DbSecure=Read-Host 'MySQL password' -AsSecureString
   try{$env:MYSQL_PASSWORD=([PSCredential]::new('mysql',$DbSecure)).GetNetworkCredential().Password}
   finally{$DbSecure.Dispose()}
  }
 }
 # Never include usernames, passwords, SQL or raw native stderr in console logs.
 $DbSafeHost=if($env:MYSQL_HOST -match '^[A-Za-z0-9_.:\-]{1,160}$'){$env:MYSQL_HOST}else{'unknown'}
 $DbSafeDatabase=if($env:MYSQL_DATABASE -match '^[A-Za-z0-9_\-]{1,160}$'){$env:MYSQL_DATABASE}else{'unknown'}
 $DbSafePort=if($env:MYSQL_PORT -match '^\d{1,5}$'){$env:MYSQL_PORT}else{'unknown'}
 [pscustomobject]@{event='database_readback_target';host=$DbSafeHost;port=$DbSafePort;database=$DbSafeDatabase;hostSource=$DbHostSource;readOnly=$true;collectorStarted=$false}|ConvertTo-Json -Compress
 # Probe performs read-only schema access. No Redis connection or task access.
 $DbPriorErrorPreference=$ErrorActionPreference
 try{
  $ErrorActionPreference='Continue'
  $DbRaw='{"operation":"probe"}'|& $DbNode (Join-Path $DbCommon 'src\volume-db-readback.mjs') 2>&1
  $DbExit=$LASTEXITCODE
 }finally{$ErrorActionPreference=$DbPriorErrorPreference}
 $DbResult=$null
 foreach($DbLine in $DbRaw){
  try{$DbCandidate=([string]$DbLine)|ConvertFrom-Json -ErrorAction Stop;if($null -ne $DbCandidate.ok){$DbResult=$DbCandidate}}catch{}
 }
 if(-not $DbResult){$DbResult=[pscustomobject]@{ok=$false;errorCode='NODE_READBACK_DIAGNOSTIC_UNAVAILABLE';stage='runtime'};$DbExit=1}
 $DbResult|ConvertTo-Json -Compress
}finally{
 foreach($DbName in $DbSaved.Keys){[Environment]::SetEnvironmentVariable($DbName,$DbSaved[$DbName],'Process')}
 $DbCredential=$null;$DbSecure=$null
}
exit $DbExit
