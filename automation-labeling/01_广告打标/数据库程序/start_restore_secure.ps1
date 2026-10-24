param([string]$MySqlUser='social_user')
$ErrorActionPreference='Stop'
$TaskRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$Node=if($env:LABEL_NODE){$env:LABEL_NODE}else{'node'}
Write-Host 'Restore cached advertisement labels ONLY for the fixed 247-row manifest.'
Write-Host 'Live identity, input hash and empty label must match; otherwise skip. No AI API calls.'
Write-Host 'Password stays in this process only. Never saved to files or chat.'
$env:MYSQL_USER=$MySqlUser
$Secure=Read-Host 'MySQL password for social_user (hidden)' -AsSecureString
$Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
try {$env:MYSQL_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)} finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer);$Secure.Dispose()}
try {
 & $Node (Join-Path $TaskRoot 'restore_cached.mjs') --run
 if($LASTEXITCODE -ne 0){Write-Warning 'Restore needs review. Do not restart blindly; inspect saved status.'}
}finally{$env:MYSQL_PASSWORD=$null}
Read-Host 'Finished. Press Enter to close'
