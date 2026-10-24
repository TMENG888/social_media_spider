param(
    [Parameter(Mandatory=$true)][string]$SampleFile,
    [string]$OutputDir='',
    [switch]$SmokeFirst,
    [switch]$EnableSemanticMerge
)
$ErrorActionPreference='Stop'
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if(-not (Test-Path -LiteralPath $SampleFile -PathType Leaf)){throw 'Sample JSON not found'}
if(-not $OutputDir){$OutputDir=Join-Path $PSScriptRoot ('test_results_v11_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if([string]::IsNullOrWhiteSpace($env:YS_LLM_API_KEY)){throw 'Configure YS_LLM_API_KEY securely; do not paste it into logs.'}
$taskArgs=@('--sample',(Resolve-Path -LiteralPath $SampleFile).Path,'--output-dir',$OutputDir)
if($SmokeFirst){$taskArgs+='--smoke-first'}
$taskEntry='delivery_v76.py'
if($EnableSemanticMerge){$taskEntry='delivery_v77.py'; Write-Warning 'Experimental adjacent merge enabled explicitly; v76 remains the default.'}
& $taskPython (Join-Path $PSScriptRoot $taskEntry) @taskArgs
if($LASTEXITCODE -ne 0){throw 'Run failed; checkpoints and request cache retained.'}
$taskResult=Join-Path $OutputDir 'delivery_results.json'
& $taskPython (Join-Path $PSScriptRoot 'verify_dictionary_backfill_v8.py') $taskResult
if($LASTEXITCODE -ne 0){throw 'Dictionary backfill validation failed.'}
& $taskPython (Join-Path $PSScriptRoot 'verify_delivery_v4.py') $taskResult --output (Join-Path $OutputDir 'contract_verification.json')
if($LASTEXITCODE -ne 0){throw 'Delivery contract validation failed.'}
$taskSummary=(Get-Content -LiteralPath $taskResult -Raw -Encoding UTF8 | ConvertFrom-Json).summary
if($taskSummary.incomplete_documents -gt 0 -or $taskSummary.smoke_passed -eq $false){
    Write-Warning 'Some sources or smoke anchors failed. This is not an accepted complete batch.'
}
Write-Output ('CSV/JSON results: '+$OutputDir)
Write-Output 'Global API concurrency is 10. Review semantic issues separately; structural validation is not an accuracy score.'
