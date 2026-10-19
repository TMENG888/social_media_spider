[CmdletBinding()]
param(
  [ValidateSet('xhs','douyin')][string]$Platform,
  [ValidateSet('status','stop','release')][string]$Action='status',
  [string]$Computer,[string]$Worker,[string]$ConfirmTarget,[string]$CommandId,
  [switch]$DryRun
)
$ErrorActionPreference='Stop'
if(-not $Platform){throw 'Platform is required: xhs or douyin.'}
$PlatformName=if($Platform -eq 'xhs'){-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66)}else{-join @([char]0x6296,[char]0x97F3)}
$PlatformDirectory=if($Platform -eq 'xhs'){'xiaohongshu'}else{'douyin'}
$MonitorConfig=Join-Path $PSScriptRoot 'config.json'
if(Test-Path -LiteralPath $MonitorConfig){
  $Config=Get-Content -LiteralPath $MonitorConfig -Raw -Encoding UTF8 | ConvertFrom-Json
  if($Config.platform_directories -and $Config.platform_directories.$PlatformName){$PlatformDirectory=$Config.platform_directories.$PlatformName}
}
. (Join-Path $PSScriptRoot 'monitor-paths.ps1')
$PackageRoot=Split-Path -Parent $PSScriptRoot
$PlatformRoot=Get-MonitorPlatformRoot -MonitorRoot $PSScriptRoot -PlatformName $PlatformName -Config $Config
$Common=Join-Path $PlatformRoot 'common'
$Node=Join-Path $Common 'runtime\node\node.exe'
$Control=Join-Path $Common 'src\remote-stop-control.mjs'
if(-not(Test-Path -LiteralPath $Node)){$Node=(Get-Command node -ErrorAction Stop).Source}
if($Action -ne 'status'){
  if(-not $Computer -or -not $Worker){throw 'Exact Computer and Worker required.'}
  $Target=$Computer.Trim().ToUpperInvariant()+'/'+$Worker.Trim().ToLowerInvariant()
  if(-not $DryRun -and $ConfirmTarget -cne $Target){throw 'ConfirmTarget must exactly equal COMPUTER/worker-XX.'}
}
$SavedPassword=$env:REDIS_PASSWORD
try {
  if(-not $env:REDIS_PASSWORD -and -not $DryRun){
    $Credential=Join-Path $PlatformRoot 'worker-01\.state\redis-password.dpapi'
    if(-not(Test-Path -LiteralPath $Credential)){throw 'Encrypted platform Redis credential unavailable.'}
    $Cipher=(Get-Content -LiteralPath $Credential -Raw -Encoding UTF8).Trim()
    $Secure=ConvertTo-SecureString -String $Cipher
    $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try{$env:REDIS_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)}
    finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer);$Secure.Dispose();$Cipher=$null}
  }
  $EffectiveAction=if($DryRun -and $Action -ne 'status'){'preview'}else{$Action}
  $ControlArgs=@($Control,'--root',$Common,'--action',$EffectiveAction)
  if($Computer){$ControlArgs+=@('--computer',$Computer)}
  if($Worker){$ControlArgs+=@('--worker',$Worker)}
  if($ConfirmTarget){$ControlArgs+=@('--confirm-target',$ConfirmTarget)}
  if($CommandId){$ControlArgs+=@('--command-id',$CommandId)}
  & $Node @ControlArgs
  $ControlExitCode=$LASTEXITCODE
} finally {$env:REDIS_PASSWORD=$SavedPassword}
exit $ControlExitCode
