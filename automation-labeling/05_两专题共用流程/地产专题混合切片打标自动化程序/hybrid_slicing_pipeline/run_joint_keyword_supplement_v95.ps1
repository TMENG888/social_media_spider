param(
 [Parameter(Mandatory=$true)][string]$InputResult,
 [Parameter(Mandatory=$true)][string]$OutputDir,
 [string]$Taxonomy='C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09\置地VOC标签体系_两专题打标版.xlsx',
 [switch]$ExportOnly,
 [switch]$ArtifactOperationAlreadyRegistered
)
$ErrorActionPreference='Stop'
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$taskNode='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$env:PYTHONIOENCODING='utf-8'
$taskInputPath=[IO.Path]::GetFullPath($InputResult)
$taskOutputPath=[IO.Path]::GetFullPath($OutputDir)
if([IO.Path]::GetDirectoryName($taskInputPath) -eq $taskOutputPath){throw 'Keep the previous delivery in its own directory.'}
Push-Location -LiteralPath $PSScriptRoot
try{
 & $taskPython -m unittest -q test_joint_keyword_supplement_v95 test_full_dictionary_supplement_v92 test_delivery_label_reference_v91 test_single_unit_v93 test_final_definition_guard_v93
 if($LASTEXITCODE -ne 0){throw 'Joint keyword regression failed.'}
 if(-not $ExportOnly){
  & $taskPython joint_keyword_supplement_v95.py --input $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
  if($LASTEXITCODE -ne 0){throw 'Joint keyword fallback failed; old delivery unchanged.'}
 }
 $taskResult=Join-Path $taskOutputPath 'delivery_results.json'
 & $taskPython token_cost_report_v93.py --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Token accounting failed.'}
 & $taskPython verify_joint_keyword_supplement_v95.py --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Joint evidence or additive contract failed.'}
 & $taskPython package_two_workbooks_v87.py --input $taskResult --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Delivery packaging failed.'}
 & $taskPython evaluate_supplement_v92.py --prior $taskInputPath --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Known-fact regression failed.'}
 if(-not $ArtifactOperationAlreadyRegistered){
  $taskMarker='C:\Users\YS-Insight\.codex\plugins\cache\openai-primary-runtime\spreadsheets\26.905.11957\skills\spreadsheets\container_tools\mark_artifact_operation_started.mjs'
  & $taskNode $taskMarker --operation-kind edit --expected-output-count 2 --output-format xlsx
  if($LASTEXITCODE -ne 0){throw 'Spreadsheet operation registration failed.'}
 }
 foreach($taskKind in @('产品信息单元','观点信息单元')){
  $taskStarted=Get-Date
  & $taskNode export_two_workbooks_v87.mjs (Join-Path $taskOutputPath ($taskKind+'_workbook_payload.json')) $taskOutputPath
  if($LASTEXITCODE -ne 0){
   $taskVerificationPath=Join-Path (Join-Path $taskOutputPath ($taskKind+'_核验')) 'export_verification.json'
   if(-not (Test-Path -LiteralPath $taskVerificationPath)){throw 'No saved export verification.'}
   if((Get-Item -LiteralPath $taskVerificationPath).LastWriteTime -lt $taskStarted){throw 'Export verification is stale.'}
   $taskVerification=Get-Content -LiteralPath $taskVerificationPath -Raw | ConvertFrom-Json
   if(-not (Test-Path -LiteralPath $taskVerification.output)){throw 'Verified workbook is missing.'}
   Write-Warning 'Native cleanup returned nonzero after saved export; require independent verification.'
  }
 }
 & $taskPython verify_supplement_delivery_v92.py --prior $taskInputPath --output-dir $taskOutputPath --taxonomy $Taxonomy
 if($LASTEXITCODE -ne 0){throw 'Independent saved-XLSX check failed.'}
 Write-Output 'Two joint keyword workbooks exported; no new API calls. Ambiguities retained for review.'
}finally{Pop-Location}
