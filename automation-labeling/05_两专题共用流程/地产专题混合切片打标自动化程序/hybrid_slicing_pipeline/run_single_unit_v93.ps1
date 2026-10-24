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
 & $taskPython -m unittest -q test_full_dictionary_supplement_v92 test_delivery_label_reference_v91 test_single_unit_v93 test_final_definition_guard_v93 test_joint_keyword_supplement_v95
 if($LASTEXITCODE -ne 0){throw 'Offline request isolation regression failed.'}
 if(-not $ExportOnly){
  if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
  if([string]::IsNullOrWhiteSpace($env:YS_LLM_API_KEY)){throw 'Configure YS_LLM_API_KEY securely; do not print it.'}
  & $taskPython full_dictionary_supplement_v93.py --input $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
  if($LASTEXITCODE -ne 0){throw 'Single-unit rerun interrupted; preserve caches and checkpoints.'}
  # Retry technical failures once; semantic disagreements remain pending.
  # Move only exact generated checkpoints, keeping them recoverable.
  $taskCheckpointDir=Join-Path $taskOutputPath 'checkpoints'
  $taskFailedCheckpoints=@(Get-ChildItem -LiteralPath $taskCheckpointDir -Filter '*.json' | Where-Object {
   $taskCheckpoint=Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
   $taskCheckpoint.label_supplement_coverage.errors.Count -gt 0
  })
  if($taskFailedCheckpoints.Count -gt 0){
   $taskRetryStamp=[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_fffffff')
   $taskRetryDir=[IO.Path]::GetFullPath((Join-Path (Join-Path $taskOutputPath 'checkpoint_retry_history') $taskRetryStamp))
   if(-not $taskRetryDir.StartsWith($taskOutputPath+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Retry history escaped output directory.'}
   New-Item -ItemType Directory -Path $taskRetryDir -Force | Out-Null
   foreach($taskCheckpointFile in $taskFailedCheckpoints){
    if([IO.Path]::GetDirectoryName($taskCheckpointFile.FullName) -ne $taskCheckpointDir){throw 'Unexpected checkpoint target.'}
    $taskRetrySource=Get-Content -LiteralPath $taskCheckpointFile.FullName -Raw | ConvertFrom-Json
    # A valid JSON response can still violate the exact traversal contract.
    # Archive that billed response too, so it is not reused as a successful cache.
    foreach($taskFailedScan in @($taskRetrySource.label_supplement_scans | Where-Object {$_.errors.Count -gt 0})){
     $taskFailedPhase='紧凑单片全字典查漏-v93-'+$taskFailedScan.branch_number
     foreach($taskBadCall in @($taskRetrySource.calls | Where-Object {$_.phase -eq $taskFailedPhase -and $_.target_unit_id -in $taskFailedScan.unit_ids})){
      if($taskBadCall.request_key -notmatch '^[a-f0-9]{64}$'){throw 'Invalid generated request key.'}
      $taskBadCallPath=Join-Path (Join-Path $taskOutputPath 'calls') ($taskBadCall.request_key+'.json')
      if(Test-Path -LiteralPath $taskBadCallPath){
       $taskSavedCall=Get-Content -LiteralPath $taskBadCallPath -Raw | ConvertFrom-Json
       if($taskSavedCall.metrics.record_id -ne $taskRetrySource.document.record_id){throw 'Cache belongs to another source.'}
       $taskAttemptDir=Join-Path $taskOutputPath 'call_attempt_history'
       New-Item -ItemType Directory -Path $taskAttemptDir -Force | Out-Null
       Move-Item -LiteralPath $taskBadCallPath -Destination (Join-Path $taskAttemptDir ($taskBadCall.request_key+'_contract_'+$taskRetryStamp+'.json'))
      }
     }
    }
    Move-Item -LiteralPath $taskCheckpointFile.FullName -Destination (Join-Path $taskRetryDir $taskCheckpointFile.Name)
   }
   Write-Output ('Retrying technical failures for '+$taskFailedCheckpoints.Count+' sources; successful requests stay cached.')
   & $taskPython full_dictionary_supplement_v93.py --input $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
   if($LASTEXITCODE -ne 0){throw 'Technical retry failed; caches, billed attempts and old checkpoints retained.'}
  }
 }
 $taskResult=Join-Path $taskOutputPath 'delivery_results.json'
 if(-not (Test-Path -LiteralPath $taskResult)){throw 'No full-batch result; inspect smoke gate before export.'}
 & $taskPython final_definition_guard_v92.py --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Final new-label evidence guard failed.'}
 # Additive keyword fallback is the final supplementation step. It does not
 # re-slice, remove existing labels, override semantic disputes or call APIs.
 & $taskPython joint_keyword_supplement_v95.py --input $taskResult --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Dictionary-derived keyword fallback failed.'}
 & $taskPython token_cost_report_v93.py --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Current-run token cost calculation failed.'}
 & $taskPython package_two_workbooks_v87.py --input $taskResult --prior $taskInputPath --taxonomy $Taxonomy --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Workbook packaging failed.'}
 & $taskPython evaluate_supplement_v92.py --prior $taskInputPath --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Same-batch regression failed.'}
 & $taskPython verify_single_unit_requests_v93.py --output-dir $taskOutputPath
 if($LASTEXITCODE -ne 0){throw 'Request-scope/full-dictionary coverage check failed.'}
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
   Write-Warning 'Native cleanup returned nonzero after saved export; require independent verification.'
  }
 }
 & $taskPython verify_supplement_delivery_v92.py --prior $taskInputPath --output-dir $taskOutputPath --taxonomy $Taxonomy
 if($LASTEXITCODE -ne 0){throw 'Independent saved-XLSX check failed.'}
 Write-Output 'Two single-unit test workbooks exported. Semantic uncertainties remain explicitly pending.'
}finally{Pop-Location}
