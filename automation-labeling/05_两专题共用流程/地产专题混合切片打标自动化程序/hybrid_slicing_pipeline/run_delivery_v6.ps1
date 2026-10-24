param([string]$OutputDir='', [int]$Concurrency=10, [switch]$SmokeOnly, [switch]$PrepareOnly, [switch]$SkipExcel)
$ErrorActionPreference='Stop'
if($Concurrency -lt 1 -or $Concurrency -gt 10){throw 'Concurrency must be 1 to 10'}
if(-not $OutputDir){$OutputDir=Join-Path $PSScriptRoot ('test_results_v6_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
$taskArgs=@('--output-dir',$OutputDir,'--concurrency',$Concurrency)
if(-not $env:YS_LLM_API_KEY -and -not $PrepareOnly){$taskArgs+='--prompt-key'}
if($SmokeOnly){$taskArgs+='--smoke-only'}
if($PrepareOnly){$taskArgs+='--prepare-only'}
& $taskPython (Join-Path $PSScriptRoot 'delivery_v6.py') @taskArgs
if($LASTEXITCODE -ne 0){throw 'Run incomplete; diagnostics and checkpoints retained'}
if(-not $PrepareOnly){
 & $taskPython (Join-Path $PSScriptRoot 'evaluate_delivery_v6.py') --result (Join-Path $OutputDir 'delivery_results.json')
 if($LASTEXITCODE -ne 0){throw 'Evidence anchor evaluation failed'}
 if(-not $SmokeOnly){
  & $taskPython (Join-Path $PSScriptRoot 'verify_delivery_v4.py') (Join-Path $OutputDir 'delivery_results.json') --output (Join-Path $OutputDir 'contract_verification.json')
  if($LASTEXITCODE -ne 0){throw 'Independent full-batch contract verification failed'}
 }
}
if(-not $PrepareOnly -and -not $SkipExcel){
 $taskNode='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
 $taskMarker='C:\Users\YS-Insight\.codex\plugins\cache\openai-primary-runtime\spreadsheets\26.905.11957\skills\spreadsheets\container_tools\mark_artifact_operation_started.mjs'
 & $taskNode $taskMarker --operation-kind create --expected-output-count 1 --output-format xlsx
 if($LASTEXITCODE -ne 0){throw 'Workbook operation initialization failed'}
 $taskExcel=Join-Path $OutputDir '两专题_全字典覆盖审核_漏标回归_v6.xlsx'
 $taskExportStarted=Get-Date
 & $taskNode (Join-Path $PSScriptRoot 'export_delivery_v4.mjs') (Join-Path $OutputDir 'delivery_results.json') $taskExcel
 if($LASTEXITCODE -ne 0){
  $taskReport=Join-Path $OutputDir 'export_v4_verification.json'
  $taskVerified=$false
  if((Test-Path -LiteralPath $taskReport) -and (Test-Path -LiteralPath $taskExcel)){
   $taskAudit=Get-Content -LiteralPath $taskReport -Raw | ConvertFrom-Json
   $taskVerified=$taskAudit.verifiedTables -ge 10 -and
    [IO.Path]::GetFullPath($taskAudit.output) -eq [IO.Path]::GetFullPath($taskExcel) -and
    (Get-Item -LiteralPath $taskReport).LastWriteTime -ge $taskExportStarted
  }
  if(-not $taskVerified){throw 'Excel export failed; CSV/JSON retained'}
  Write-Warning 'Excel export and all-cell re-import passed; runtime returned a cleanup exit code.'
 }
}
Write-Output ('CSV/JSON results: '+$OutputDir)
