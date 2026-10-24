param([string]$RuntimeRoot='E:\Codex\runtime\zhihu-rpa',[string]$CacheRoot='E:\Codex\temp\zhihu-rpa\npm')
$ErrorActionPreference='Stop'
foreach($folder in @($RuntimeRoot,$CacheRoot)){
 $drive=[IO.Path]::GetPathRoot($folder)
 if(!(Test-Path -LiteralPath $drive)){throw "目标磁盘不可用：$drive。请为 install.ps1 显式指定其他 RuntimeRoot/CacheRoot；不会自动改存C盘。"}
 New-Item -ItemType Directory -Force -Path $folder | Out-Null
}
$node=Join-Path $RuntimeRoot 'node\node.exe'
if(!(Test-Path -LiteralPath $node)){
 $version='v22.19.0';$archive="node-$version-win-x64.zip";$zip=Join-Path $CacheRoot $archive
 Invoke-WebRequest -Uri "https://nodejs.org/dist/$version/$archive" -OutFile $zip -UseBasicParsing
 $sums=Join-Path $CacheRoot 'SHASUMS256.txt'
 Invoke-WebRequest -Uri "https://nodejs.org/dist/$version/SHASUMS256.txt" -OutFile $sums -UseBasicParsing
 $line=Get-Content -LiteralPath $sums | Where-Object {$_ -match ([regex]::Escape($archive)+'$')}
 if(!$line -or ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower() -ne ($line -split '\s+')[0])){throw 'Node ZIP SHA256 校验失败'}
 Expand-Archive -LiteralPath $zip -DestinationPath $CacheRoot -Force
 $extracted=Join-Path $CacheRoot "node-$version-win-x64"
 Copy-Item -LiteralPath $extracted -Destination (Join-Path $RuntimeRoot 'node') -Recurse
}
$deps=Join-Path $RuntimeRoot 'dependencies'
New-Item -ItemType Directory -Force -Path $deps | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'package.json') -Destination $deps -Force
$lock=Join-Path $PSScriptRoot 'package-lock.json'
if(Test-Path -LiteralPath $lock){Copy-Item -LiteralPath $lock -Destination $deps -Force}
$npm=Join-Path $RuntimeRoot 'node\node_modules\npm\bin\npm-cli.js'
$verb='install';if(Test-Path -LiteralPath $lock){$verb='ci'}
Push-Location -LiteralPath $deps
try { & $node $npm $verb --cache $CacheRoot --no-audit --no-fund; if($LASTEXITCODE -ne 0){throw 'npm安装失败'} }
finally { Pop-Location }
$modules=Join-Path $PSScriptRoot 'node_modules'
if(!(Test-Path -LiteralPath $modules)){New-Item -ItemType Junction -Path $modules -Target (Join-Path $deps 'node_modules') | Out-Null}
$cfg=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if(!(Test-Path -LiteralPath ([IO.Path]::GetPathRoot($cfg.browserRoot)))){throw '浏览器缓存盘不可用，请修改config.json的browserRoot'}
$env:PLAYWRIGHT_BROWSERS_PATH=$cfg.browserRoot
if(!$cfg.browserExecutable -or !(Test-Path -LiteralPath $cfg.browserExecutable)){
 & $node (Join-Path $deps 'node_modules\playwright\cli.js') install chromium
 if($LASTEXITCODE -ne 0){throw 'Chromium安装失败'}
}
Copy-Item -LiteralPath (Join-Path $deps 'package-lock.json') -Destination $PSScriptRoot -Force
Write-Host '安装完成。请运行对应节点的环境预检和登录知乎。'
