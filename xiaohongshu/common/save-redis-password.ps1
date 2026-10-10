[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$WorkerRoot,
  [switch]$Clear,
  [switch]$CheckPath
)
$ErrorActionPreference='Stop'
$Worker=(Resolve-Path -LiteralPath $WorkerRoot).Path
if($CheckPath){
  Write-Host "Worker path verified: $Worker"
  exit 0
}
$State=Join-Path $Worker '.state'
$Credential=Join-Path $State 'redis-password.dpapi'
if($Clear){
  Remove-Item -LiteralPath $Credential -Force -ErrorAction SilentlyContinue
  Write-Host 'Saved Redis credential removed for this worker.'
  exit 0
}
if(-not(Test-Path -LiteralPath $State)){New-Item -ItemType Directory -Path $State -Force|Out-Null}
$Secure=Read-Host 'Redis password (hidden)' -AsSecureString
$Pointer=[IntPtr]::Zero
$Common=Split-Path -Parent $MyInvocation.MyCommand.Path
$Node=Join-Path $Common 'runtime\node\node.exe'
if(-not(Test-Path -LiteralPath $Node)){$Node=(Get-Command node -ErrorAction Stop).Source}
$OldLocation=Get-Location
$SavedEnv=@{}
foreach($Name in @('REDIS_URL','REDIS_USERNAME','REDIS_PASSWORD')){$SavedEnv[$Name]=[Environment]::GetEnvironmentVariable($Name,'Process')}
try {
  if($Secure.Length -eq 0){throw 'Redis password cannot be empty.'}
  $Config=Get-Content -LiteralPath (Join-Path $Common 'redis-config.json') -Raw -Encoding UTF8|ConvertFrom-Json
  if(-not $env:REDIS_URL){$env:REDIS_URL=$Config.url}
  if(-not $env:REDIS_USERNAME){$env:REDIS_USERNAME=$Config.username}
  $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  $env:REDIS_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
  Set-Location -LiteralPath $Common
  & $Node 'src\redis-auth-check.mjs'
  if($LASTEXITCODE -ne 0){throw 'Redis verification failed. The previously saved password remains unchanged.'}
  $Cipher=ConvertFrom-SecureString -SecureString $Secure
  $Temporary=$Credential+'.tmp-'+$PID
  $Cipher|Set-Content -LiteralPath $Temporary -Encoding UTF8
  Move-Item -LiteralPath $Temporary -Destination $Credential -Force
} finally {
  if($Pointer -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)}
  $Secure.Dispose()
  foreach($Name in $SavedEnv.Keys){[Environment]::SetEnvironmentVariable($Name,$SavedEnv[$Name],'Process')}
  Set-Location -LiteralPath $OldLocation.Path
}
Write-Host 'Verified Redis credential saved with Windows DPAPI for this machine, user, and worker.'
