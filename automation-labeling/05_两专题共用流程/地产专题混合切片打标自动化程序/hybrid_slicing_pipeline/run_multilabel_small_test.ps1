param(
    [string]$InputCsv = 'C:\Users\YS-Insight\Desktop\ods_social_media_post.csv',
    [string]$PythonExecutable = 'python',
    [string]$ApiBaseUrl = 'http://127.0.0.1:3000',
    [string]$Model = 'qwen3.7-flash'
)
$ErrorActionPreference = 'Stop'
if (-not $env:YS_LLM_API_KEY) { $env:YS_LLM_API_KEY = [Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User') }
if (-not $env:YS_LLM_API_KEY) { throw 'Configure YS_LLM_API_KEY securely before running. Do not paste keys into source files.' }
$env:PYTHONIOENCODING = 'utf-8'
$taskOutput = Join-Path $PSScriptRoot ('test_results_multilabel_api_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
& $PythonExecutable (Join-Path $PSScriptRoot 'multilabel_v2.py') --input $InputCsv --config (Join-Path $PSScriptRoot 'sample_config_multilabel_small.json') --output-dir $taskOutput --api-base-url $ApiBaseUrl --model $Model --concurrency 2
if ($LASTEXITCODE -ne 0) { throw 'Small API test failed; inspect output before rerunning.' }
Write-Output "Results: $taskOutput"
