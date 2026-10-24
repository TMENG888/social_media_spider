param([Parameter(Mandatory=$true)][string]$RequestFile,[Parameter(Mandatory=$true)][string]$ResultFile)
$ErrorActionPreference='Stop'
$Common=Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Common 'worker-recovery.ps1')
$request=Get-Content -LiteralPath $RequestFile -Raw -Encoding UTF8 | ConvertFrom-Json
$result=[ordered]@{requestId=$request.requestId;taskId=$request.taskId;success=$false;importConfirmed=$false;status='import_unconfirmed';requiresCommitReconciliation=$false}
try {
  if(-not $env:MYSQL_USER -or -not $env:MYSQL_PASSWORD -or $env:MYSQL_ENABLED -eq '0'){throw 'DATABASE_CREDENTIAL_UNAVAILABLE'}
  # A unique recovery output must not bypass an earlier uncertain COMMIT.
  $priorReceipts=@()
  if(Test-Path -LiteralPath $request.originalOutput){
    $priorReceipts=@(Get-ChildItem -LiteralPath $request.originalOutput -File | Where-Object {$_.Name -eq 'mysql_import_status.json' -or $_.Name -like 'mysql_import_status.json.previous.*' -or $_.Name -like 'mysql_salvage_status.*.json'})
  }
  $priorReceipts+=@(Get-ChildItem -LiteralPath (Split-Path $ResultFile -Parent) -Recurse -File -Filter 'mysql*status*.json' -ErrorAction SilentlyContinue)
  foreach($receiptFile in $priorReceipts){
    $prior=Get-Content -LiteralPath $receiptFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    if($prior.status -eq 'failed' -and $prior.commitState -in @('unknown','committed')){
      $result.requiresCommitReconciliation=$true;$result.status='commit_confirmation_required'
      throw 'COMMIT_CONFIRMATION_REQUIRED'
    }
  }
  $node=Join-Path $Common 'runtime\node\node.exe'
  $python=Join-Path $Common 'runtime\python\python.exe'
  New-Item -ItemType Directory -Force -Path $request.outputDir | Out-Null
  $salvage=Invoke-KeywordCheckpointSalvage -Python $python -Node $node `
    -Collector (Join-Path $Common 'src\channels_pc_collector.py') `
    -Enricher (Join-Path $Common 'src\channels_browser_enricher.mjs') `
    -Postprocessor (Join-Path $Common 'src\channels_ods_postprocess.mjs') `
    -Importer (Join-Path $Common 'src\mysql-import-retry.mjs') `
    -OutputDir $request.outputDir -StateDb $request.stateDb -Keyword $request.keyword `
    -CollectComments ([bool]$request.collectComments) -DatabaseEnabled $true -OfflineOnly $true `
    -StopFile ([string]$request.stopFile) -StandbyMinutes 5
  # Maintenance has a 600-second outer deadline; its network wait is capped at
  # five minutes, leaving time for local export and import finalisation.
  $result.mysql=$salvage.mysql
  $result.requiresCommitReconciliation=$salvage.requiresCommitReconciliation
  $result.success=$salvage.success -and $salvage.importConfirmed -and [int]$salvage.mysql.posts -gt 0
  $result.importConfirmed=$result.success
  $result.status=if($result.success){'import_confirmed'}elseif($salvage.requiresCommitReconciliation){'commit_confirmation_required'}elseif($salvage.mysql.status -eq 'success'){'no_local_rows'}else{'import_unconfirmed'}
} catch {
  $result.errorType=$_.Exception.GetType().Name
}
$temporary=$ResultFile+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
[IO.File]::WriteAllText($temporary,($result | ConvertTo-Json -Depth 15),(New-Object Text.UTF8Encoding($false)))
Move-Item -LiteralPath $temporary -Destination $ResultFile -Force
if(-not $result.success){exit 75}
exit 0
