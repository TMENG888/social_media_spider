param([Parameter(Mandatory=$true)][string]$InputFile, [Parameter(Mandatory=$true)][string]$OutputDir, [switch]$SmokeOnly)
$ErrorActionPreference='Stop'
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if([string]::IsNullOrWhiteSpace($env:YS_LLM_API_KEY)){throw 'Configure YS_LLM_API_KEY securely. Never paste or print the key.'}
$taskSource=(Resolve-Path -LiteralPath $InputFile).Path
$taskDestination=[IO.Path]::GetFullPath($OutputDir)
if((Split-Path -Parent $taskSource) -eq $taskDestination){throw 'Use a separate version directory; never overwrite the prior delivery.'}
Push-Location -LiteralPath $PSScriptRoot
try{
 & $taskPython -m unittest test_project_context_v90 test_completeness_v89
 if($LASTEXITCODE -ne 0){throw 'Project regression failed.'}
 $taskArgs=@('project_context_v90.py','--input',$taskSource,'--output-dir',$taskDestination)
 if($SmokeOnly){$taskArgs+='--smoke-only'}
 & $taskPython @taskArgs
 if($LASTEXITCODE -ne 0){throw 'Context repair failed; checkpoints retained, prior files unchanged.'}
 Write-Output ('Results: '+$taskDestination)
}finally{Pop-Location}
