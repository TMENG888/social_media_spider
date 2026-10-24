param(
 [Parameter(Mandatory=$true)][string]$BaselineJson,
 [Parameter(Mandatory=$true)][string]$DJson,
 [Parameter(Mandatory=$true)][string]$OutputDir
)
$ErrorActionPreference='Stop'
$taskPython='C:/Users/YS-Insight/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$baselinePath=(Resolve-Path -LiteralPath $BaselineJson).Path
$dPath=(Resolve-Path -LiteralPath $DJson).Path
$outputPath=[IO.Path]::GetFullPath($OutputDir)
if(Test-Path -LiteralPath $outputPath){throw '请指定全新的实验输出目录；保留D和所有历史结果。'}
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if(-not $env:YS_LLM_API_KEY){throw '未配置YS_LLM_API_KEY。请在本机安全配置，不要把密钥写进脚本。'}
$env:PYTHONIOENCODING='utf-8'
& $taskPython (Join-Path $PSScriptRoot 'explore_d_guards_v81.py') --baseline $baselinePath --d $dPath --output-dir $outputPath
if($LASTEXITCODE -ne 0){throw '实验失败，请查看检查点。正式默认入口和D均未修改。'}
