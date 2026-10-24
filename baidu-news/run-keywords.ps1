param(
  [string]$KeywordsFile = "keywords.txt",
  [string]$OutputDir = "",
  [int]$MaxPages = 20,
  [int]$MaxItems = 200,
  [int]$BatchSize = 10,
  [string]$StartDate = "2026-01-01",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$keywordPath = [System.IO.Path]::GetFullPath((Join-Path $projectDir $KeywordsFile))
if (-not (Test-Path -LiteralPath $keywordPath -PathType Leaf)) {
  throw "关键词文件不存在：$keywordPath"
}
if (-not $OutputDir) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $OutputDir = "batch-data-$stamp"
}
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $projectDir $OutputDir))
$statePath = [System.IO.Path]::GetFullPath((Join-Path $projectDir ".state\$(Split-Path -Leaf $OutputDir)"))

Push-Location $projectDir
try {
  if (-not (Test-Path -LiteralPath (Join-Path $projectDir "node_modules"))) { npm install }
  $arguments = @(
    "run", "batch", "--",
    "--keywords", $keywordPath,
    "--batch-size", $BatchSize,
    "--max-pages", $MaxPages,
    "--max-items", $MaxItems,
    "--start-date", $StartDate,
    "--output-dir", $outputPath,
    "--state-dir", $statePath
  )
  if ($Force) { $arguments += "--force" }
  & npm @arguments
  if ($LASTEXITCODE -ne 0) { throw "批量采集退出码：$LASTEXITCODE" }
  Write-Host "ODS数据：$(Join-Path $outputPath 'combined_ods_social_media_post.jsonl')"
  Write-Host "文章任务表：$(Join-Path $outputPath '爬虫任务表.xlsx')"
} finally {
  Pop-Location
}
