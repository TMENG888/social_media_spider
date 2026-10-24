param(
 [Parameter(Mandatory=$true)][string]$InputResult,
 [Parameter(Mandatory=$true)][string]$OutputDir,
 [string]$Taxonomy='C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09\置地VOC标签体系_两专题打标版.xlsx',
 [switch]$ExportOnly
)
$ErrorActionPreference='Stop'
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$taskNode='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$env:PYTHONIOENCODING='utf-8'
$taskInputPath=[IO.Path]::GetFullPath($InputResult)
$taskOutputPath=[IO.Path]::GetFullPath($OutputDir)
if([IO.Path]::GetDirectoryName($taskInputPath) -eq $taskOutputPath){throw 'Output must be an independent version directory.'}
Push-Location -LiteralPath $PSScriptRoot
try{
 & $taskPython -m unittest -q test_full_dictionary_supplement_v92
 if($LASTEXITCODE -ne 0){throw 'Offline regression failed; no API calls started.'}
 if(-not $ExportOnly){
  if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
  if([string]::IsNullOrWhiteSpace($env:YS_LLM_API_KEY)){throw 'Configure YS_LLM_API_KEY securely. Never print or pass it as an argument.'}
  & $taskPython full_dictionary_supplement_v92.py --input $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
  if($LASTEXITCODE -ne 0){throw 'Supplement failed; retain source and cached checkpoints.'}
  $taskGatePath=Join-Path $taskOutputPath 'supplement_smoke_gate.json'
  if(-not (Test-Path -LiteralPath $taskGatePath)){throw 'No smoke gate result.'}
  $taskGate=Get-Content -LiteralPath $taskGatePath -Raw | ConvertFrom-Json
  if(-not $taskGate.passed){throw 'Smoke gate failed; full-batch export is not authorized by this launcher.'}
  & $taskPython retry_supplement_protocol_v92.py --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
  if($LASTEXITCODE -ne 0){throw 'Bounded API/contract recovery failed; do not conceal incomplete sources.'}
 }
 $taskResult=Join-Path $taskOutputPath 'delivery_results.json'
 if(-not (Test-Path -LiteralPath $taskResult)){throw 'No completed batch result to export.'}
 & $taskPython final_definition_guard_v92.py --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Final evidence-risk routing failed.'}
 & $taskPython package_two_workbooks_v87.py --input $taskResult --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Two-workbook packaging contract failed.'}
 & $taskPython evaluate_supplement_v92.py --prior $taskInputPath --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Same-batch regression failed; no workbook export.'}
 $taskMarker='C:\Users\YS-Insight\.codex\plugins\cache\openai-primary-runtime\spreadsheets\26.905.11957\skills\spreadsheets\container_tools\mark_artifact_operation_started.mjs'
 & $taskNode $taskMarker --operation-kind edit --expected-output-count 2 --output-format xlsx
 if($LASTEXITCODE -ne 0){throw 'Spreadsheet operation registration failed.'}
 foreach($taskKind in @('产品信息单元','观点信息单元')){
  $taskStarted=Get-Date
  & $taskNode export_two_workbooks_v87.mjs (Join-Path $taskOutputPath ($taskKind+'_workbook_payload.json')) $taskOutputPath
  if($LASTEXITCODE -ne 0){
   $taskVerificationPath=Join-Path (Join-Path $taskOutputPath ($taskKind+'_核验')) 'export_verification.json'
   if(-not (Test-Path -LiteralPath $taskVerificationPath)){throw 'No saved export verification.'}
   if((Get-Item -LiteralPath $taskVerificationPath).LastWriteTime -lt $taskStarted){throw 'Export verification is stale.'}
   $taskVerification=Get-Content -LiteralPath $taskVerificationPath -Raw | ConvertFrom-Json
   if(-not (Test-Path -LiteralPath $taskVerification.output)){throw 'Verified workbook is missing.'}
   Write-Warning 'Native cleanup returned nonzero after export; require independent verification below.'
  }
 }
 & $taskPython verify_supplement_delivery_v92.py --prior $taskInputPath --output-dir $taskOutputPath --taxonomy $Taxonomy
 if($LASTEXITCODE -ne 0){throw 'Independent saved-XLSX verification failed.'}
 Write-Output 'Product and opinion workbooks exported. Semantic uncertainty remains in the review sheets; no zero-miss guarantee.'
}finally{Pop-Location}
