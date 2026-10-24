param(
 [string]$Posts='C:\Users\YS-Insight\Desktop\ods_social_media_post.csv',
 [string]$Comments='C:\Users\YS-Insight\Desktop\ods_social_media_comment.csv',
 [string]$OutputDir='',
 [ValidateSet('Hreview','Hscope','Hflex','Hlocal','Hconsensus')][string]$DeliveryRoute='Hreview',
 [string]$ExcelPath=''
)
$ErrorActionPreference='Stop'
$taskPython='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$taskNode='C:\Users\YS-Insight\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
if(-not $OutputDir){$OutputDir=Join-Path $PSScriptRoot ('test_results_v82_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
if(-not $ExcelPath){$ExcelPath=Join-Path $OutputDir ('两专题_H整合_'+$DeliveryRoute+'_测试交付.xlsx')}
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if([string]::IsNullOrWhiteSpace($env:YS_LLM_API_KEY)){throw 'Configure YS_LLM_API_KEY securely. Never print the key.'}
Push-Location -LiteralPath $PSScriptRoot
try{
 & $taskPython (Join-Path $PSScriptRoot 'delivery_v82.py') --posts $Posts --comments $Comments --output-dir $OutputDir
 if($LASTEXITCODE -ne 0){throw 'Generation failed. Cached requests and source checkpoints are retained.'}
 & $taskPython (Join-Path $PSScriptRoot 'final_review_v83.py') --output-dir $OutputDir --route Hscope
 if($LASTEXITCODE -ne 0){throw 'Final semantic review failed; checkpoints retained.'}
 & $taskPython (Join-Path $PSScriptRoot 'compose_review_delivery_v84.py') --output-dir $OutputDir
 if($LASTEXITCODE -ne 0){throw 'Non-destructive review delivery composition failed.'}
 & $taskPython (Join-Path $PSScriptRoot 'test_real_hflex_v82.py') --output-dir $OutputDir
 if($LASTEXITCODE -ne 0){throw 'Boundary challenge execution failed; keep all previous checkpoints.'}
 foreach($taskRoute in @('D','Hflex','Hlocal','Hconsensus','Hscope','Hreview')){
  $taskResult=Join-Path $OutputDir ($taskRoute+'\delivery_results.json')
  & $taskPython (Join-Path $PSScriptRoot 'verify_dictionary_backfill_v8.py') $taskResult
  if($LASTEXITCODE -ne 0){throw ('Dictionary validation failed: '+$taskRoute)}
  & $taskPython (Join-Path $PSScriptRoot 'verify_delivery_v4.py') $taskResult --output (Join-Path $OutputDir ($taskRoute+'\contract_verification.json'))
  if($LASTEXITCODE -ne 0){throw ('Contract validation failed: '+$taskRoute)}
 }
 # Hscope is a separately named corrected-boundary review candidate. Hfull
 # failed the scope regression and is never silently substituted for Hflex.
 $taskExportRoute=$DeliveryRoute
 & $taskPython (Join-Path $PSScriptRoot 'evaluate_integrated_v82.py') --output-dir $OutputDir --delivery-route $taskExportRoute
 if($LASTEXITCODE -ne 0){throw 'Evaluation/package preparation failed.'}
 $taskCompanionDir=Join-Path (Split-Path $ExcelPath) $taskExportRoute
 New-Item -ItemType Directory -Path $taskCompanionDir -Force | Out-Null
 foreach($taskFile in @('delivery_results.json','产品信息单元.csv','观点信息单元.csv','人工审核.csv','来源追溯.csv','排除及异常.csv','渠道覆盖.csv','抽样文章清单.csv','Token费用.csv','contract_verification.json','dictionary_backfill_verification.json')){
  $taskSourceFile=Join-Path (Join-Path $OutputDir $taskExportRoute) $taskFile
  $taskTargetFile=Join-Path $taskCompanionDir $taskFile
  if((Test-Path -LiteralPath $taskSourceFile) -and [IO.Path]::GetFullPath($taskSourceFile) -ne [IO.Path]::GetFullPath($taskTargetFile)){Copy-Item -LiteralPath $taskSourceFile -Destination $taskTargetFile}
 }
 $taskMarker='C:\Users\YS-Insight\.codex\plugins\cache\openai-primary-runtime\spreadsheets\26.905.11957\skills\spreadsheets\container_tools\mark_artifact_operation_started.mjs'
 & $taskNode $taskMarker --operation-kind create --expected-output-count 1 --output-format xlsx
 if($LASTEXITCODE -ne 0){throw 'Spreadsheet operation registration failed.'}
 $taskExportStarted=Get-Date
 & $taskNode (Join-Path $PSScriptRoot 'export_delivery_v4.mjs') (Join-Path $OutputDir 'delivery_package.json') $ExcelPath
 if($LASTEXITCODE -ne 0){
  $taskVerifyFile=Join-Path (Join-Path (Split-Path $ExcelPath) (([IO.Path]::GetFileNameWithoutExtension($ExcelPath))+'_核验')) 'export_v4_verification.json'
  $taskVerified=$false
  if((Test-Path -LiteralPath $taskVerifyFile) -and (Test-Path -LiteralPath $ExcelPath) -and (Get-Item -LiteralPath $taskVerifyFile).LastWriteTime -ge $taskExportStarted){
   $taskVerification=Get-Content -LiteralPath $taskVerifyFile -Raw | ConvertFrom-Json
   $taskPackage=Get-Content -LiteralPath (Join-Path $OutputDir 'delivery_package.json') -Raw | ConvertFrom-Json
   $taskVerified=([IO.Path]::GetFullPath($taskVerification.output) -eq [IO.Path]::GetFullPath($ExcelPath)) -and ($taskVerification.summary.version -eq $taskPackage.summary.version) -and ($taskVerification.verifiedTables -eq (1+$taskPackage.tables.PSObject.Properties.Count))
  }
  if(-not $taskVerified){throw 'Spreadsheet export or exact saved-value verification failed.'}
  Write-Warning 'Native process cleanup returned nonzero after fresh export and exact reimport verification succeeded. Workbook is saved; inspect visual previews before handoff.'
 }
 Write-Output ('Delivery workbook: '+$ExcelPath)
 Write-Output 'Hconsensus is a conservative review route, not proof of the best accuracy. Review evaluation and human queue before formal statistics.'
}finally{Pop-Location}
