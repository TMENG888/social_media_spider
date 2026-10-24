param([string]$OutputDir='', [string]$ReplayInput='', [int]$Concurrency=10, [switch]$SmokeOnly)
$ErrorActionPreference='Stop'
if($Concurrency -lt 1 -or $Concurrency -gt 10){throw 'Concurrency must be 1 to 10'}
if(-not $OutputDir){$OutputDir=Join-Path $PSScriptRoot ('test_results_v8_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if(-not $env:YS_LLM_API_KEY){throw 'Configure YS_LLM_API_KEY securely first; no request made.'}
$taskArgs=@('--output-dir',$OutputDir,'--concurrency',$Concurrency)
if($ReplayInput){
 if(-not (Test-Path -LiteralPath $ReplayInput -PathType Leaf)){throw 'Replay input not found'}
 $taskArgs+=@('--replay-input',$ReplayInput)
 if($SmokeOnly){throw 'Use SmokeOnly for a fresh pipeline, not replay mode'}
}elseif($SmokeOnly){$taskArgs+='--smoke-only'}
& $taskPython (Join-Path $PSScriptRoot 'delivery_v8.py') @taskArgs
if($LASTEXITCODE -ne 0){throw 'Run incomplete; checkpoints retained'}
& $taskPython (Join-Path $PSScriptRoot 'evaluate_delivery_v8.py') --result (Join-Path $OutputDir 'delivery_results.json')
if($LASTEXITCODE -ne 0){throw 'Evidence anchors failed; do not accept delivery. Inspect comparison CSV/JSON.'}
& $taskPython (Join-Path $PSScriptRoot 'quality_audit_v8.py') --result (Join-Path $OutputDir 'delivery_results.json')
if($LASTEXITCODE -ne 0){throw 'Quality diagnostics could not run'}
& $taskPython (Join-Path $PSScriptRoot 'verify_dictionary_backfill_v8.py') (Join-Path $OutputDir 'delivery_results.json')
if($LASTEXITCODE -ne 0){throw 'Exact dictionary backfill failed; do not accept delivery'}
if(-not $SmokeOnly){
 & $taskPython (Join-Path $PSScriptRoot 'verify_delivery_v4.py') (Join-Path $OutputDir 'delivery_results.json') --output (Join-Path $OutputDir 'contract_verification.json')
 if($LASTEXITCODE -ne 0){throw 'Independent contract check failed'}
}
Write-Output ('CSV/JSON results: '+$OutputDir)
Write-Output 'Inspect incomplete sources, failed evidence anchors and human-review rows before accepting delivery.'
