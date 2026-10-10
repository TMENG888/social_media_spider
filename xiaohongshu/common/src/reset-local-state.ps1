[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$DeploymentRoot)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $DeploymentRoot).Path
if ((Split-Path -Leaf $root) -ne '小红书') { throw "拒绝清理非小红书部署包目录：$root" }
$prefix = $root.TrimEnd('\') + '\'
$removedFiles = 0
$removedBytes = [int64]0
$lockedTargets = @()

function Remove-TargetResilient([string]$Target, [string]$AllowedRoot) {
  if (-not $Target.StartsWith(($AllowedRoot.TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase)) { throw "拒绝清理越界目标：$Target" }
  $item = Get-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue
  if (-not $item) { return }
  if ($item.PSIsContainer) {
    foreach ($child in Get-ChildItem -LiteralPath $Target -Force) { Remove-TargetResilient $child.FullName $AllowedRoot }
    try { Remove-Item -LiteralPath $Target -Force }
    catch { if ((Get-ChildItem -LiteralPath $Target -Force -ErrorAction SilentlyContinue).Count -eq 0) { $script:lockedTargets += [pscustomobject]@{ target = $Target; error = $_.Exception.Message } } }
    return
  }
  try {
    $length = [int64]$item.Length
    Remove-Item -LiteralPath $Target -Force
    $script:removedFiles += 1
    $script:removedBytes += $length
  } catch {
    $script:lockedTargets += [pscustomobject]@{ target = $Target; error = $_.Exception.Message }
  }
}

function Remove-ChildrenSafely([string]$Directory, [string[]]$Preserve = @()) {
  if (-not (Test-Path -LiteralPath $Directory)) { return }
  $resolved = (Resolve-Path -LiteralPath $Directory).Path
  if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "拒绝清理部署包外目录：$resolved" }
  foreach ($item in Get-ChildItem -LiteralPath $resolved -Force) {
    if ($Preserve -contains $item.Name) { continue }
    $target = $item.FullName
    Remove-TargetResilient $target $resolved
  }
}

# 仅关闭已无采集子进程、停留在启动BAT中的旧小红书窗口。
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*分布式部署包*小红书*启动工作节点.bat*'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

foreach ($worker in Get-ChildItem -LiteralPath $root -Directory -Filter 'worker-*') {
  Remove-ChildrenSafely (Join-Path $worker.FullName 'runs')
  Remove-ChildrenSafely (Join-Path $worker.FullName '.state') @('browser-profile', 'asr-models')
}
Remove-ChildrenSafely (Join-Path $root 'common\runs')
Remove-ChildrenSafely (Join-Path $root 'common\.state')

[pscustomobject]@{
  root = $root
  removedFiles = $removedFiles
  removedBytes = $removedBytes
  browserProfilesPreserved = @(Get-ChildItem -LiteralPath $root -Directory -Filter 'worker-*' | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName '.state\browser-profile') }).Count
  lockedTargets = $lockedTargets
} | ConvertTo-Json
