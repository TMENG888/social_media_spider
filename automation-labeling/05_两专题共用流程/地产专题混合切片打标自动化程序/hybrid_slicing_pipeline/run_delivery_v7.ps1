param([string]$OutputDir='', [int]$Concurrency=10, [switch]$SmokeOnly, [switch]$PrepareOnly)
$ErrorActionPreference='Stop'
if($Concurrency -lt 1 -or $Concurrency -gt 10){throw 'Concurrency must be 1 to 10'}
if(-not $OutputDir){$OutputDir=Join-Path $PSScriptRoot ('test_results_v7_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
$taskArgs=@('--output-dir',$OutputDir,'--concurrency',$Concurrency)
if(-not $env:YS_LLM_API_KEY -and -not $PrepareOnly){$taskArgs+='--prompt-key'}
if($SmokeOnly){$taskArgs+='--smoke-only'}
if($PrepareOnly){$taskArgs+='--prepare-only'}
& $taskPython (Join-Path $PSScriptRoot 'delivery_v7.py') @taskArgs
if($LASTEXITCODE -ne 0){throw 'Run incomplete; diagnostics and checkpoints retained'}
if(-not $PrepareOnly){
 & $taskPython (Join-Path $PSScriptRoot 'evaluate_delivery_v6.py') --result (Join-Path $OutputDir 'delivery_results.json')
 if($LASTEXITCODE -ne 0){throw 'Evidence anchor evaluation failed'}
 if(-not $SmokeOnly){
  & $taskPython (Join-Path $PSScriptRoot 'verify_delivery_v4.py') (Join-Path $OutputDir 'delivery_results.json') --output (Join-Path $OutputDir 'contract_verification.json')
  if($LASTEXITCODE -ne 0){throw 'Independent full-batch contract verification failed'}
 }
}
Write-Output ('CSV/JSON results: '+$OutputDir)
Write-Output 'Use export_delivery_v4.mjs to build the reviewed Excel delivery from delivery_results.json.'
