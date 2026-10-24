param(
 [ValidatePattern('^worker-0[1-5]$')][string]$Worker='worker-01',
 [switch]$Check,[switch]$Login,[switch]$Smoke,[switch]$ExportOnly,[switch]$Stop,
 [string]$RuntimeRoot='E:\Codex\runtime\zhihu-rpa',
 [string]$Keyword='北京臻澐'
)
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$env:PLAYWRIGHT_BROWSERS_PATH=$cfg.browserRoot
$node=Join-Path $RuntimeRoot 'node\node.exe'
if(!(Test-Path -LiteralPath $node)){$cmd=Get-Command node -ErrorAction SilentlyContinue;if($cmd){$node=$cmd.Source}else{throw '请先运行 安装运行环境.bat'}}
$nodeArgs=@((Join-Path $PSScriptRoot 'src\worker.mjs'),'--worker',$Worker)
if($Check){$nodeArgs+='--check'}
elseif($Stop){$nodeArgs+='--stop'}
elseif($Login){$nodeArgs+='--login'}
elseif($Smoke){$nodeArgs+=@('--smoke','--keyword',$Keyword,'--limit','2')}
elseif($ExportOnly){$nodeArgs+='--supervise'}
else{$nodeArgs+=@('--mysql','--supervise')}
if($Smoke -and $Login){$nodeArgs+='--smoke'}
$redisSecret=$null;$mysqlSecret=$null
$logDir=Join-Path $cfg.outputRoot ($Worker+'\logs')
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$transcribing=$false
try {
 Start-Transcript -Path (Join-Path $logDir ((Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')) -Append | Out-Null
 $transcribing=$true
 if(!$Check -and !$Login -and !$Smoke -and !$Stop){
  if(!$env:REDIS_PASSWORD){$redisSecret=Read-Host 'Redis密码（隐藏输入，仅本进程保留）' -AsSecureString;$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($redisSecret);try{$env:REDIS_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}}
  if(!$ExportOnly -and !$env:MYSQL_PASSWORD){$mysqlSecret=Read-Host 'MySQL密码（隐藏输入，仅本进程保留）' -AsSecureString;$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($mysqlSecret);try{$env:MYSQL_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}}
 }
 & $node @nodeArgs
 if($LASTEXITCODE -ne 0){throw "节点退出码 $LASTEXITCODE，请查看终端及结果目录 task_status.json"}
} finally {
 if($redisSecret){Remove-Item Env:REDIS_PASSWORD -ErrorAction SilentlyContinue;$redisSecret.Dispose()}
 if($mysqlSecret){Remove-Item Env:MYSQL_PASSWORD -ErrorAction SilentlyContinue;$mysqlSecret.Dispose()}
 if($transcribing){Stop-Transcript | Out-Null}
}
