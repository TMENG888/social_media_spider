param(
    [string]$InputCsv = 'C:\Users\YS-Insight\Desktop\ods_social_media_post.csv',
    [int]$PerTopic = 30,
    [int]$Concurrency = 10,
    [string]$PythonExecutable = 'C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
    [string]$ApiBaseUrl = 'http://127.0.0.1:3000',
    [string]$Model = 'qwen3.7-flash',
    [switch]$LegacySingleLabel,
    [switch]$Offline,
    [string]$CommentsCsv = 'C:\Users\YS-Insight\Desktop\ods_social_media_comment.csv'
)
$ErrorActionPreference = 'Stop'
if ($Concurrency -lt 1 -or $Concurrency -gt 16) { throw 'Concurrency must be 1 to 16.' }
if (-not $LegacySingleLabel) {
    if($PerTopic -ne 30){throw 'v4 uses the approved fixed 30-per-topic channel plan plus 20 commented-post supplements. Use PerTopic 30.'}
    & (Join-Path $PSScriptRoot 'run_delivery_v4.ps1') -PostsCsv $InputCsv -CommentsCsv $CommentsCsv -Concurrency $Concurrency -PythonExecutable $PythonExecutable -ApiBaseUrl $ApiBaseUrl -Model $Model -Offline:$Offline
    return
}
if (-not $env:YS_LLM_API_KEY) { $env:YS_LLM_API_KEY = [Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User') }
if (-not $Offline -and -not $env:YS_LLM_API_KEY) { throw 'Set YS_LLM_API_KEY in this shell first; do not put the key in source files.' }
if ($Offline -and $LegacySingleLabel) { throw 'Offline mode is supported by v3 only.' }
$env:PYTHONIOENCODING = 'utf-8'
$taskStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$taskOutput = Join-Path $PSScriptRoot "test_results_${taskStamp}"
$taskConfig = Join-Path $taskOutput 'sample_config.json'
$taskRuleOutput = Join-Path $taskOutput 'rule'
$taskApiOutput = Join-Path $taskOutput 'api'
$taskTemplates = 'C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09'
& $PythonExecutable (Join-Path $PSScriptRoot 'select_per_topic_samples.py') --input $InputCsv --base-config (Join-Path $PSScriptRoot 'sample_config_50_voc5.json') --output $taskConfig --per-topic $PerTopic
if ($LASTEXITCODE -ne 0) { throw 'Sample selection failed.' }
if (-not $LegacySingleLabel) {
    $taskMode = if ($Offline) { 'offline' } else { 'api' }
    $taskArgs = @('--input',$InputCsv,'--config',$taskConfig,'--output-dir',$taskApiOutput,'--api-base-url',$ApiBaseUrl,'--model',$Model,'--concurrency',$Concurrency,'--mode',$taskMode)
    if ($CommentsCsv) { $taskArgs += @('--comments',$CommentsCsv) }
    & $PythonExecutable (Join-Path $PSScriptRoot 'multilabel_v3.py') @taskArgs
    if ($LASTEXITCODE -ne 0) { throw 'Multilabel run failed; inspect outputs before retrying.' }
    Write-Output "Multilabel CSV and JSON results: $taskOutput"
    return
}
& $PythonExecutable (Join-Path $PSScriptRoot 'hybrid_slice_and_label.py') --input $InputCsv --topic1-template (Join-Path $taskTemplates '专题一 房地产社媒监测_V6_产品力分析数据模板.xlsx') --topic2-template (Join-Path $taskTemplates '专题二_北京臻澐网络及竞品口碑分析数据模板_V3.xlsx') --voc-taxonomy (Join-Path $PSScriptRoot 'resources\置地VOC标签体系_两专题打标版.xlsx') --config $taskConfig --output-dir $taskRuleOutput
if ($LASTEXITCODE -ne 0) { throw 'Rule candidate generation failed.' }
& $PythonExecutable (Join-Path $PSScriptRoot 'run_api_50_test.py') --input $InputCsv --config $taskConfig --rule-json (Join-Path $taskRuleOutput 'sample_delivery_data.json') --output-dir $taskApiOutput --api-base-url $ApiBaseUrl --model $Model --concurrency $Concurrency --candidate-batch-size 6
if ($LASTEXITCODE -ne 0) { throw 'API test failed; inspect output before rerunning.' }
Write-Output "CSV and JSON results: $taskOutput"
