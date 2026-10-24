param([string]$Prior='', [string]$OutputDir='', [switch]$SmokeOnly)
$ErrorActionPreference='Stop'
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if(-not $OutputDir){$OutputDir=Join-Path $PSScriptRoot ('test_results_v89_completeness_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if([string]::IsNullOrWhiteSpace($env:YS_LLM_API_KEY)){throw 'Configure YS_LLM_API_KEY securely. Do not paste or print the key.'}
Push-Location -LiteralPath $PSScriptRoot
try{
 & $taskPython -m unittest test_delivery_v85 test_replacement_v87 test_completeness_v89 test_label_retention_v89 test_project_context_v90
 if($LASTEXITCODE -ne 0){throw 'Offline regression failed.'}
 $taskArgs=@('completeness_v89.py','--output-dir',$OutputDir)
 if($Prior){$taskArgs+=@('--prior',$Prior)}
 if($SmokeOnly){$taskArgs+='--smoke-only'}
 & $taskPython @taskArgs
 if($LASTEXITCODE -ne 0){throw 'Processing failed. Checkpoints retained; do not promote.'}
 if(-not $SmokeOnly){
  $gate=Get-Content -LiteralPath (Join-Path $OutputDir 'smoke_gate.json') -Raw | ConvertFrom-Json
  if(-not $gate.semantic_ok){throw 'Semantic smoke gate failed. Full-batch delivery not promoted.'}
  & $taskPython 'retry_transport_v89.py' --output-dir $OutputDir
  if($LASTEXITCODE -ne 0){throw 'Transport-only resume failed. Checkpoints retained.'}
  $guardDir=Join-Path $OutputDir 'label_retention'
  & $taskPython 'label_retention_v89.py' --input (Join-Path $OutputDir 'delivery_results.json') --output-dir $guardDir
  if($LASTEXITCODE -ne 0){throw 'Lost-label guard failed.'}
  Write-Output ('Post-guard results: '+$guardDir)
 }
 Write-Output ('Results: '+$OutputDir)
 Write-Output 'Review smoke_gate.json and pending_units. A complete main table does not prove full-batch semantic accuracy.'
}finally{Pop-Location}
