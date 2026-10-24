param(
 [Parameter(Mandatory=$true)][string]$OutputDir,
 [string]$Taxonomy=(Join-Path $PSScriptRoot 'resources/置地VOC标签体系_两专题打标版.xlsx'),
 [switch]$FinalizeOnly,
 [string]$WorkbookDir=''
)
$ErrorActionPreference='Stop'
$taskPython=if($env:LABEL_PYTHON){$env:LABEL_PYTHON}else{'python'}
$taskNode=if($env:LABEL_NODE){$env:LABEL_NODE}else{'node'}
$env:PYTHONIOENCODING='utf-8'
if(-not $env:YS_LLM_API_KEY){$env:YS_LLM_API_KEY=[Environment]::GetEnvironmentVariable('YS_LLM_API_KEY','User')}
if(-not $env:YS_LLM_API_KEY){throw 'Configure YS_LLM_API_KEY securely, do not print it.'}
Push-Location -LiteralPath $PSScriptRoot
try{
 if(-not $FinalizeOnly){
  & $taskPython prepare_bulk_v96.py --output-dir $OutputDir
  if($LASTEXITCODE -ne 0){throw 'Sampling failed'}
  & $taskPython run_bulk_v96.py --sample (Join-Path $OutputDir 'sample.json') --taxonomy $Taxonomy --output-dir $OutputDir
  if($LASTEXITCODE -ne 0){throw 'Generation interrupted. Source/stage and billed request checkpoints retained.'}
  # Identity-only stage has its own signatures. Successful v96 generation,
  # labels and boundaries are preserved, not regenerated for identity repair.
  & $taskPython apply_identity_completion_v97.py --output-dir $OutputDir --taxonomy $Taxonomy
  if($LASTEXITCODE -ne 0){throw 'Identity completion interrupted; original stages and billed requests retained.'}
 }
 # FinalizeOnly never starts new generation or new identity API requests.
 & $taskPython package_bulk_v96.py --output-dir $OutputDir --taxonomy $Taxonomy
 if($LASTEXITCODE -ne 0){throw 'Source/label/comment contract verification failed'}
 # Resolve only the saved workbooks/previews destination. Generation caches
 # and all source/request checkpoints stay in OutputDir.
 if(-not $WorkbookDir){
  $taskExportConfig=Join-Path $OutputDir 'export_target.json'
  if(Test-Path -LiteralPath $taskExportConfig){
   $taskExportSettings=Get-Content -LiteralPath $taskExportConfig -Raw | ConvertFrom-Json
   $WorkbookDir=[string]$taskExportSettings.workbook_dir
   if(-not $WorkbookDir){throw 'export_target.json has no workbook_dir'}
  }else{$WorkbookDir=$OutputDir}
 }
 if(-not [System.IO.Path]::IsPathRooted($WorkbookDir)){throw 'WorkbookDir must be an absolute path'}
 $WorkbookDir=[System.IO.Path]::GetFullPath($WorkbookDir)
 New-Item -ItemType Directory -Path $WorkbookDir -Force | Out-Null
 # Spreadsheet operation registration belongs to the caller; do not register
 # again during the same turn after the taxonomy authoring operation.
 foreach($taskKind in @('产品信息单元','观点信息单元')){
  $taskStarted=Get-Date
  & $taskNode export_two_workbooks_v87.mjs (Join-Path $OutputDir ($taskKind+'_workbook_payload.json')) $WorkbookDir
  if($LASTEXITCODE -ne 0){throw ('Workbook export failed: '+$taskKind)}
  $taskVerification=Join-Path (Join-Path $WorkbookDir ($taskKind+'_核验')) 'export_verification.json'
  if(-not (Test-Path -LiteralPath $taskVerification) -or (Get-Item -LiteralPath $taskVerification).LastWriteTime -lt $taskStarted){throw 'Missing fresh saved-XLSX verification'}
 }
 & $taskPython verify_bulk_v96.py --output-dir $OutputDir --workbook-dir $WorkbookDir --taxonomy $Taxonomy
 if($LASTEXITCODE -ne 0){throw 'Independent saved workbook verification failed'}
}finally{Pop-Location}
