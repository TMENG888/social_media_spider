param(
 [string]$PostsCsv='C:\Users\YS-Insight\Desktop\ods_social_media_post.csv',
 [string]$CommentsCsv='C:\Users\YS-Insight\Desktop\ods_social_media_comment.csv',
 [int]$Concurrency=10,
 [string]$OutputDir='',
 [string]$ExcelPath='',
 [string]$PythonExecutable='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
 [string]$NodeExecutable='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe',
 [string]$ApiBaseUrl='http://127.0.0.1:3000',
 [string]$Model='qwen3.7-flash',
 [switch]$Offline,
 [switch]$SmokeOnly,
 [switch]$SkipExcel
)
$ErrorActionPreference='Stop'
if ($Concurrency -lt 1 -or $Concurrency -gt 10) { throw 'Global concurrency must be 1 to 10.' }
if (-not $OutputDir) { $OutputDir=Join-Path $PSScriptRoot ('test_results_v4_'+(Get-Date -Format 'yyyyMMdd_HHmmss')) }
if (-not $ExcelPath) { $ExcelPath=Join-Path $OutputDir '两专题_切片打标验收_v4.xlsx' }
$taskMode=if($Offline){'offline'}else{'api'}
$taskLoadedKey=$false
$taskKeyPtr=[IntPtr]::Zero
try {
 if (-not $Offline -and -not $env:YS_LLM_API_KEY) {
  $env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')
  $taskLoadedKey=$true
  if (-not $env:YS_LLM_API_KEY) {
   $taskSecret=Read-Host 'API key (hidden, process only)' -AsSecureString
   $taskKeyPtr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskSecret)
   $env:YS_LLM_API_KEY=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskKeyPtr)
  }
 }
 $env:PYTHONIOENCODING='utf-8'
 $taskArgs=@('--posts',$PostsCsv,'--comments',$CommentsCsv,'--output-dir',$OutputDir,'--concurrency',$Concurrency,'--api-base-url',$ApiBaseUrl,'--model',$Model,'--mode',$taskMode)
 if($SmokeOnly){$taskArgs+='--smoke-only'}
 & $PythonExecutable (Join-Path $PSScriptRoot 'delivery_v4.py') @taskArgs
 if($LASTEXITCODE -ne 0){throw 'API/smoke run not complete. Check saved diagnostics before resuming with the same OutputDir.'}
 if(-not $SkipExcel){
  $taskExportStarted=Get-Date
  & $NodeExecutable (Join-Path $PSScriptRoot 'export_delivery_v4.mjs') (Join-Path $OutputDir 'delivery_results.json') $ExcelPath
  if($LASTEXITCODE -ne 0){
   # Some desktop native runtimes exit nonzero AFTER export and exact re-import.
   # A stale file/report cannot satisfy this gate.
   $taskVerifiedExport=$false
   $taskReportPath=Join-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ExcelPath))) 'export_v4_verification.json'
   if((Test-Path -LiteralPath $taskReportPath) -and (Test-Path -LiteralPath $ExcelPath)){
    try{
     $taskReport=Get-Content -LiteralPath $taskReportPath -Raw | ConvertFrom-Json
     $taskVerifiedExport=$taskReport.verifiedTables -eq 9 -and
      [IO.Path]::GetFullPath($taskReport.output) -eq [IO.Path]::GetFullPath($ExcelPath) -and
      (Get-Item -LiteralPath $taskReportPath).LastWriteTime -ge $taskExportStarted -and
      (Get-Item -LiteralPath $ExcelPath).Length -gt 0
    }catch{$taskVerifiedExport=$false}
   }
   if(-not $taskVerifiedExport){throw 'Excel export failed; CSV/JSON are retained.'}
   Write-Warning 'Excel export and exact re-import checks passed; the desktop native runtime returned a cleanup exit code.'
  }
 }
 Write-Output ('Results: '+$OutputDir)
} finally {
 if($taskKeyPtr -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskKeyPtr)}
 if($taskLoadedKey){$env:YS_LLM_API_KEY=$null}
}
