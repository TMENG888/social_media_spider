param([string]$Config=(Join-Path $PSScriptRoot 'config.json'))
$ErrorActionPreference='Stop'
$taskConfig=(Resolve-Path -LiteralPath $Config).Path
$cfg=Get-Content -LiteralPath $taskConfig -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $cfg.output_dir | Out-Null
Start-Process -FilePath "$env:windir\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $PSScriptRoot 'launch.ps1')+'"'),'-Config',('"'+$taskConfig+'"')) -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $cfg.output_dir 'service.log') -RedirectStandardError (Join-Path $cfg.output_dir 'service-error.log') | Out-Null
Write-Host ("Dashboard starting on http://"+$cfg.lan_address+':'+$cfg.port)
