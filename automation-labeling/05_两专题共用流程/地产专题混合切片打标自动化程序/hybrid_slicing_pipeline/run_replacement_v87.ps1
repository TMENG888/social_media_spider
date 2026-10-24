param(
 [string]$Prior='',
 [string]$Sample='',
 [string]$OutputDir='',
 [switch]$RunFull
)
$ErrorActionPreference='Stop'
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if(-not $Prior){$Prior=Join-Path $PSScriptRoot 'test_results_v82_integrated_20261010\Hreview\delivery_results.json'}
if(-not $Sample){$Sample=Join-Path $PSScriptRoot 'test_results_v82_integrated_20261010\sample.json'}
if(-not $OutputDir){$OutputDir=Join-Path $PSScriptRoot ('test_results_v87_experimental_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
if(-not(Test-Path -LiteralPath $Prior)){throw 'Prior delivery JSON is missing.'}
if(-not(Test-Path -LiteralPath $Sample)){throw 'Same-batch sample JSON is missing.'}
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if([string]::IsNullOrWhiteSpace($env:YS_LLM_API_KEY)){throw 'Configure YS_LLM_API_KEY safely; never print or put it in arguments.'}
Push-Location -LiteralPath $PSScriptRoot
try{
 & $taskPython -m unittest test_delivery_v85 test_replacement_v87
 if($LASTEXITCODE -ne 0){throw 'Offline regression failed; API testing not launched.'}
 $taskArgs=@('delivery_v87.py','--prior',$Prior,'--sample',$Sample,'--output-dir',$OutputDir)
 if(-not $RunFull){$taskArgs+='--smoke-only'}
 & $taskPython @taskArgs
 if($LASTEXITCODE -ne 0){throw 'API smoke/contract failed. Checkpoints retained; do not promote this experiment or keep retrying a failing service.'}
 Write-Output ('Experimental output: '+$OutputDir)
 Write-Output 'This experiment does not replace the default core. Validate semantic errors and source coverage before producing a new delivery.'
}finally{Pop-Location}
