[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WorkerRoot)
$ErrorActionPreference='Stop'
$Common=Split-Path -Parent $MyInvocation.MyCommand.Path
$Worker=(Resolve-Path -LiteralPath $WorkerRoot).Path
$Node=Join-Path $Common 'runtime\node\node.exe'
$Credential=Join-Path $Worker '.state\redis-password.dpapi'
if((Read-Host 'Only after manual review and normal access is restored, type RESET to clear the shared cooldown') -cne 'RESET'){
  Write-Host 'Cancelled. No state changed.'
  exit 0
}
$OldPassword=$env:REDIS_PASSWORD
try{
  if(-not $env:REDIS_PASSWORD){
    if(Test-Path -LiteralPath $Credential){
      $Secure=ConvertTo-SecureString -String ((Get-Content -LiteralPath $Credential -Raw -Encoding UTF8).Trim())
    }else{$Secure=Read-Host 'Redis password (hidden)' -AsSecureString}
    $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try{$env:REDIS_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)}
    finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer);$Secure.Dispose()}
  }
  & $Node (Join-Path $Common 'src\cooldown-control.mjs') '--root' $Common '--worker-root' $Worker '--action' 'reset-confirmed'
  $Result=$LASTEXITCODE
}finally{$env:REDIS_PASSWORD=$OldPassword}
exit $Result
