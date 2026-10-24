param([switch]$InspectOnly,[string]$MySqlUser='social_user')
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Node=if($env:LABEL_NODE){$env:LABEL_NODE}else{'node'}
function Read-Hidden([string]$Prompt){
 $Secure=Read-Host $Prompt -AsSecureString
 $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
 try {[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)} finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer);$Secure.Dispose()}
}
Write-Host 'Target: social.ods_social_media_post; project: 北京臻澐项目口碑; only blank 是否广告.'
Write-Host 'Credentials stay in this terminal process only; not saved in files or chat.'
$env:MYSQL_USER=$MySqlUser
Write-Host ('MySQL username: '+$MySqlUser)
if(-not $env:MYSQL_PASSWORD){$env:MYSQL_PASSWORD=Read-Hidden 'MySQL password (hidden)'}
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
try {
 & $Node (Join-Path $Root 'label_ads.mjs') --inspect
 if($LASTEXITCODE -ne 0){throw 'Database preflight failed; nothing updated.'}
 if(-not $InspectOnly){
  & $Node (Join-Path $Root 'label_ads.mjs') --run
  if($LASTEXITCODE -ne 0){Write-Warning 'Task stopped safely. Saved predictions can be reused; see error_status.json.'}
 }
}finally{$env:MYSQL_PASSWORD=$null;$env:YS_LLM_API_KEY=$null}
Write-Host 'Finished. Status and checkpoints are in the task output directory.'
Read-Host 'Press Enter to close'
