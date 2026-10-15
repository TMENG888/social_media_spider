param(
  [ValidateSet("menu", "single", "batch", "resume", "repair-ids")]
  [string]$Mode = "menu"
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledBrowser = Join-Path $projectDir ".portable-build\browsers\chrome-win64\chrome.exe"

function Resolve-UserPath([string]$Value) {
  $trimmed = $Value.Trim().Trim('"')
  if (-not [System.IO.Path]::IsPathRooted($trimmed)) { $trimmed = Join-Path $projectDir $trimmed }
  return [System.IO.Path]::GetFullPath($trimmed)
}

function Read-Required([string]$Prompt) {
  do { $value = Read-Host $Prompt } while ([string]::IsNullOrWhiteSpace($value))
  return $value.Trim()
}

function Invoke-Node([string[]]$Arguments) {
  & node @Arguments
  if ($LASTEXITCODE -ne 0) { throw "命令执行失败（退出码 $LASTEXITCODE）：node $($Arguments -join ' ')" }
}

function Initialize-DatabaseCredentials {
  $dbUser = Read-Required "MySQL 用户名"
  $securePassword = Read-Host "MySQL 密码（输入时不显示，也不会写入磁盘）" -AsSecureString
  $passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
  try {
    $env:MYSQL_USER = $dbUser
    $env:MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
    if ([string]::IsNullOrWhiteSpace($env:MYSQL_PASSWORD)) { throw "MySQL 密码不能为空" }
  } finally {
    if ($passwordPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr) }
  }
}

function Import-Results([string]$InputFile, [string]$OutputDir) {
  if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) { throw "未找到待入库文件：$InputFile" }
  if ((Get-Item -LiteralPath $InputFile).Length -eq 0) {
    Write-Host "本次没有符合条件的文章，跳过数据库入库。" -ForegroundColor Yellow
    return
  }
  Invoke-Node @("src/import-mysql.mjs", "--input", $InputFile)
  Invoke-Node @("src/build-crawl-tasks.mjs", "--output-dir", $OutputDir, "--output", (Join-Path $OutputDir "爬虫任务表.xlsx"), "--db-imported")
  Write-Host "数据已入库，爬虫任务表已更新为‘已入库’。" -ForegroundColor Green
}

Push-Location $projectDir
try {
  if (Test-Path -LiteralPath $bundledBrowser -PathType Leaf) {
    $env:BROWSER_EXECUTABLE = $bundledBrowser
    Write-Host "使用项目内置 Chromium：$bundledBrowser" -ForegroundColor DarkGray
  }
  if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "未安装 Node.js 20+，请先安装后重试。" }
  if (-not (Test-Path -LiteralPath (Join-Path $projectDir "node_modules"))) {
    $npmCommand = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npmCommand) { throw "未找到 npm.cmd，请重新安装 Node.js 20+。" }
    & $npmCommand install
    if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
  }
  if ($Mode -eq "menu") {
    Write-Host "`n百度资讯任务驱动爬虫" -ForegroundColor Cyan
    Write-Host "1. 单个检索词采集并入库"
    Write-Host "2. 导入检索词任务文件（XLSX / JSON / TXT）批量采集并入库"
    Write-Host "3. 对历史输出目录断点续爬失败任务并入库"
    Write-Host "4. 修复本爬虫已经入库的历史哈希ID"
    $choice = Read-Required "请选择 1 / 2 / 3 / 4"
    $Mode = switch ($choice) { "1" { "single" } "2" { "batch" } "3" { "resume" } "4" { "repair-ids" } default { throw "无效选项：$choice" } }
  }

  Write-Host "请先输入数据库凭据；爬虫将按完成的关键词即时入库。" -ForegroundColor Yellow
  Initialize-DatabaseCredentials
  Write-Host "正在验证MySQL连接……" -ForegroundColor DarkGray
  Invoke-Node @("src/check-mysql.mjs")

  if ($Mode -eq "repair-ids") {
    $inputFile = Resolve-UserPath (Read-Required "请输入原运行目录中 ods_social_media_post.jsonl 或 combined_ods_social_media_post.jsonl 的完整路径")
    if (-not (Test-Path -LiteralPath $inputFile -PathType Leaf)) { throw "历史JSONL不存在：$inputFile" }
    $outputDir = Split-Path -Parent $inputFile
    Import-Results $inputFile $outputDir
  } elseif ($Mode -eq "single") {
    $query = Read-Required "请输入百度资讯检索词"
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $outputDir = Join-Path $projectDir "runs\single-$stamp"
    $stateDir = Join-Path $projectDir ".state\single-$stamp"
    $crawlError = $null
    try {
      Invoke-Node @("src/index.mjs", "--query", $query, "--start-date", "2026-01-01", "--batch-size", "10", "--max-pages", "20", "--max-items", "200", "--output-dir", $outputDir, "--state-dir", $stateDir)
    } catch { $crawlError = $_ }
    $singleInput = Join-Path $outputDir "ods_social_media_post.jsonl"
    if (Test-Path -LiteralPath $singleInput -PathType Leaf) { Import-Results $singleInput $outputDir }
    if ($crawlError) { throw $crawlError }
  } else {
    $taskFile = Resolve-UserPath (Read-Required "请输入检索词任务文件（XLSX / JSON / TXT）的完整路径")
    if (-not (Test-Path -LiteralPath $taskFile -PathType Leaf)) { throw "检索词任务文件不存在：$taskFile" }
    $taskArgument = switch ([System.IO.Path]::GetExtension($taskFile).ToLowerInvariant()) {
      ".xlsx" { @("--keyword-task-xlsx", $taskFile) }
      ".json" { @("--keywords-json", $taskFile) }
      ".txt"  { @("--keywords", $taskFile) }
      default { throw "不支持的任务文件格式，仅支持 .xlsx、.json、.txt" }
    }
    if ($Mode -eq "resume") {
      $outputDir = Resolve-UserPath (Read-Required "请输入上次批量运行的输出目录")
      if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) { throw "历史输出目录不存在：$outputDir" }
      $stateDir = Join-Path $projectDir ".state\resume"
      $crawlArgs = @("src/run-batch.mjs") + $taskArgument + @("--start-date", "2026-01-01", "--output-dir", $outputDir, "--state-dir", $stateDir, "--resume-failed", "--import-each-keyword")
    } else {
      $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
      $outputDir = Join-Path $projectDir "runs\batch-$stamp"
      $stateDir = Join-Path $projectDir ".state\batch-$stamp"
      $crawlArgs = @("src/run-batch.mjs") + $taskArgument + @("--start-date", "2026-01-01", "--output-dir", $outputDir, "--state-dir", $stateDir, "--import-each-keyword")
    }
    Invoke-Node $crawlArgs
  }
  Write-Host "输出目录：$outputDir" -ForegroundColor Cyan
  if (Test-Path -LiteralPath (Join-Path $outputDir '爬虫任务表.xlsx')) { Write-Host "文章任务表：$(Join-Path $outputDir '爬虫任务表.xlsx')" -ForegroundColor Cyan }
} finally {
  Remove-Item Env:MYSQL_PASSWORD -ErrorAction SilentlyContinue
  Remove-Item Env:MYSQL_USER -ErrorAction SilentlyContinue
  Pop-Location
}
