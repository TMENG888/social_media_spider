param([string]$TargetRoot = '')
$ErrorActionPreference = 'Stop'
$SourceRoot = (Resolve-Path $PSScriptRoot).Path.TrimEnd('\')
$Candidates = @(
  'D:\爬虫脚本\视频号',
  'D:\爬虫中心\视频号',
  'D:\视频号'
)

if (-not $TargetRoot) {
  $Matches = @($Candidates | Where-Object {
    (Test-Path -LiteralPath (Join-Path $_ 'common\src\channels_pc_collector.py')) -and
    ((Resolve-Path $_).Path.TrimEnd('\') -ne $SourceRoot)
  })
  if ($Matches.Count -eq 1) {
    $TargetRoot = $Matches[0]
  } else {
    Write-Host 'Detected target candidates:'
    $Matches | ForEach-Object { Write-Host "  $_" }
    $TargetRoot = Read-Host 'Enter the local video crawler root folder'
  }
}

$TargetRoot = (Resolve-Path -LiteralPath $TargetRoot -ErrorAction Stop).Path.TrimEnd('\')
$RelativeFiles = @(
  'common\src\channels_pc_collector.py',
  'common\src\asr-worker.py',
  'common\src\loopback-recorder.py',
  'common\src\process-loopback-recorder.exe',
  'common\src\process-loopback-recorder.NOTICE.txt',
  'common\src\redis_task_queue.py',
  'common\src\channels_resilience.py',
  'common\src\mysql-import.mjs',
  'common\collector_config.json',
  'common\sql\ods_social_media_post.sql',
  'common\sql\ods_social_media_comment.sql',
  'common\sql\upgrade_existing_ods_to_utf8mb4.sql',
  'common\requirements.txt',
  'common\check-env.ps1',
  'common\run-worker.ps1',
  'common\run-asr-backfill.ps1',
  'common\run-two-stage.ps1',
  'common\run-redis-worker.ps1',
  'VERSION',
  'manifest.json',
  'README_分布式部署包.txt',
  '生产部署文件清单.txt',
  '生产运行操作流程.txt'
)
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupRoot = Join-Path $TargetRoot ('.state\code-backup-' + $Stamp)
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

foreach ($Relative in $RelativeFiles) {
  $Source = Join-Path $SourceRoot $Relative
  $Target = Join-Path $TargetRoot $Relative
  if (-not (Test-Path -LiteralPath $Source)) { throw "Source file missing: $Source" }
  $Backup = Join-Path $BackupRoot $Relative
  if (Test-Path -LiteralPath $Target) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
    Copy-Item -LiteralPath $Target -Destination $Backup -Force
  }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Target -Force
  $SourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
  $TargetHash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
  if ($SourceHash -ne $TargetHash) { throw "Hash verification failed: $Relative" }
  Write-Host "Updated and verified: $Relative [$TargetHash]" -ForegroundColor Green
}

$PortablePython = Join-Path $TargetRoot 'common\runtime\python\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonPath = if (Test-Path -LiteralPath $PortablePython) { $PortablePython } elseif ($PythonCommand) { $PythonCommand.Source } else { '' }
if ($PythonPath) {
  & $PythonPath -m py_compile `
    (Join-Path $TargetRoot 'common\src\channels_pc_collector.py') `
    (Join-Path $TargetRoot 'common\src\asr-worker.py') `
    (Join-Path $TargetRoot 'common\src\loopback-recorder.py') `
    (Join-Path $TargetRoot 'common\src\redis_task_queue.py') `
    (Join-Path $TargetRoot 'common\src\channels_resilience.py')
  if ($LASTEXITCODE -ne 0) { throw 'Python syntax validation failed after update.' }
  Write-Host 'Python syntax validation passed.' -ForegroundColor Green
}

Write-Host "Target root: $TargetRoot"
Write-Host "Backup root: $BackupRoot"
Write-Host 'Update completed. Restart the Redis dynamic worker now.' -ForegroundColor Cyan
