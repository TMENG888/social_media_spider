param([Parameter(Mandatory=$true)][int]$GenerationPid,[Parameter(Mandatory=$true)][string]$OutputDir)
$ErrorActionPreference='Stop'
$taskStatusFile=Join-Path $OutputDir 'background_export_status.json'
try{
 @{status='waiting_for_generation';generation_pid=$GenerationPid;updated_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $taskStatusFile -Encoding utf8
 Wait-Process -Id $GenerationPid -ErrorAction SilentlyContinue
 if(-not (Test-Path -LiteralPath (Join-Path $OutputDir 'delivery_results.json'))){throw 'Generation ended without full-batch results; inspect saved requests and checkpoints.'}
 $taskResult=Get-Content -LiteralPath (Join-Path $OutputDir 'delivery_results.json') -Raw | ConvertFrom-Json
 if(-not $taskResult.summary.bulk_source_complete -or $taskResult.results.Count -ne 1956){throw 'Generation is not complete for all planned sources.'}
 @{status='exporting';updated_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $taskStatusFile -Encoding utf8
 & (Join-Path $PSScriptRoot 'run_bulk_v96.ps1') -OutputDir $OutputDir -FinalizeOnly *> (Join-Path $OutputDir 'background_export.log')
 if(-not (Test-Path -LiteralPath (Join-Path $OutputDir 'saved_workbooks_verification.json'))){throw 'Saved-workbook verification not generated.'}
 $taskVerification=Get-Content -LiteralPath (Join-Path $OutputDir 'saved_workbooks_verification.json') -Raw | ConvertFrom-Json
 if(-not $taskVerification.passed){throw 'Saved-workbook verification failed.'}
 @{status='files_complete';updated_at=[DateTime]::UtcNow.ToString('o');workbooks=$taskVerification.workbooks} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $taskStatusFile -Encoding utf8
}catch{
 @{status='needs_attention';updated_at=[DateTime]::UtcNow.ToString('o');error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $taskStatusFile -Encoding utf8
 exit 1
}
