param([switch]$CollectOnce,[string]$Python='python',[string]$Config=(Join-Path $PSScriptRoot 'config.json'))
$ErrorActionPreference='Stop'
if(-not (Test-Path -LiteralPath $Config)){throw 'Copy config.example.json to config.json and configure the deployment first.'}
$env:CRAWLER_OPS_CONFIG=(Resolve-Path -LiteralPath $Config).Path
$cfg=Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$taskPython=if($cfg.python){$cfg.python}else{$Python}
New-Item -ItemType Directory -Force -Path $cfg.output_dir,$cfg.temp_dir | Out-Null
$taskSavedTemp=$env:TEMP
$taskSavedTmp=$env:TMP
try {
 $env:TEMP=$cfg.temp_dir
 $env:TMP=$cfg.temp_dir
 $taskArgs=@('-B','-X','utf8',(Join-Path $PSScriptRoot 'server.py'))
 if($CollectOnce){$taskArgs+='--collect-once'}
 & $taskPython @taskArgs
 if($LASTEXITCODE){throw "Dashboard exited with code $LASTEXITCODE"}
} finally {$env:TEMP=$taskSavedTemp;$env:TMP=$taskSavedTmp}
