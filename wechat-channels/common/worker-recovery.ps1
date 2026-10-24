# Shared by normal and exceptional exits. No Redis commands or task mutation.
function Invoke-KeywordCheckpointSalvage {
  param(
    [string]$Python, [string]$Node, [string]$Collector,
    [string]$Enricher, [string]$Postprocessor, [string]$Importer,
    [string]$OutputDir, [string]$StateDb, [string]$Keyword,
    [bool]$CollectComments, [bool]$DatabaseEnabled, [bool]$OfflineOnly=$false,
    [string]$StopFile='', [int]$StandbyMinutes=-1
  )
  $result = [ordered]@{success=$false;stage='export';exportConfirmed=$false;importConfirmed=$false;requiresCommitReconciliation=$false;mysql=@{status='pending'}}
  try {
    if (-not (Test-Path -LiteralPath $StateDb -PathType Leaf)) { throw 'SQLite checkpoint not found' }
    $raw=Join-Path $OutputDir 'ods_social_media_post_channels.jsonl'
    $enrich=Join-Path $OutputDir 'browser_enrichment.jsonl'
    $final=Join-Path $OutputDir 'ods_social_media_post_channels_final.jsonl'
    # Suppress success-stream stdout so this function returns exactly one object.
    & $Python $Collector export-ods --output-dir $OutputDir --state-db $StateDb --keyword $Keyword | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $raw)) { throw 'SQLite export unconfirmed' }
    $result.exportConfirmed=$true
    $result.stage='enrich'
    if($OfflineOnly){
      # Lease/network failure must not open more pages or wait for external
      # enrichment. Keep old evidence, postprocess only committed SQLite rows.
      $enrich=Join-Path $OutputDir ('browser_enrichment.recovery.'+[Guid]::NewGuid().ToString('N')+'.jsonl')
      [IO.File]::WriteAllText($enrich,'',(New-Object Text.UTF8Encoding($false)))
      $result.remoteEnrichmentSkipped=$true
    } else {
      $enrichArgs=@($Enricher,$raw,$enrich);if($CollectComments){$enrichArgs+='--comments'}
      & $Node @enrichArgs | Out-Host
      if($LASTEXITCODE -ne 0){throw 'Enrichment failed'}
    }
    $result.stage='postprocess'
    $postArgs=@($Postprocessor,$raw,$enrich,$final);if($CollectComments){$postArgs+='--comments'}
    & $Node @postArgs | Out-Host
    if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $final)){throw 'Postprocessing unconfirmed'}
    if($DatabaseEnabled){
      $result.stage='import'
      # A lost COMMIT reply may mean data is already committed. Never let
      # the salvage path silently bypass the importer's no-replay decision.
      $previousImportStatus=Join-Path $OutputDir 'mysql_import_status.json'
      if(Test-Path -LiteralPath $previousImportStatus){
        $previousImport=Get-Content -LiteralPath $previousImportStatus -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
        if($previousImport.status -eq 'failed' -and $previousImport.commitState -in @('unknown','committed')){
          $result.requiresCommitReconciliation=$true
          $result.mysql=$previousImport
          $result.stage='commit_confirmation_required'
          throw 'Previous transaction commit outcome requires reconciliation; automatic import replay blocked'
        }
      }
      $commentFile=Join-Path $OutputDir 'ods_social_media_comment_channels_final.jsonl'
      # A unique status filename prevents an old success file proving this import.
      $statusFile=Join-Path $OutputDir ('mysql_salvage_status.'+[Guid]::NewGuid().ToString('N')+'.json')
      $result.importStatusFile=$statusFile
      $importArgs=@($Importer,'--posts',$final,'--status',$statusFile)
      if($StopFile){$importArgs+=@('--stop-file',$StopFile)}
      if($StandbyMinutes -ge 0){$importArgs+=@('--standby-minutes',[string]$StandbyMinutes)}
      if($CollectComments -and (Test-Path -LiteralPath $commentFile)){$importArgs+=@('--comments',$commentFile)}
      & $Node @importArgs | Out-Host
      $importExit=$LASTEXITCODE
      if($importExit -ne 0){
        if(Test-Path -LiteralPath $statusFile){
          $failedReceipt=Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
          if($failedReceipt.status -eq 'failed'){$result.mysql=$failedReceipt}
          if($failedReceipt.status -eq 'failed' -and $failedReceipt.commitState -in @('unknown','committed')){
            $result.mysql=$failedReceipt
            $result.requiresCommitReconciliation=$true
            $result.stage='commit_confirmation_required'
          }
        }
        throw 'MySQL import failed'
      }
      $mysqlResult=Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
      if($mysqlResult.status -ne 'success'){throw 'MySQL import not confirmed'}
      $result.mysql=$mysqlResult
      $result.importConfirmed=$true
    } else {$result.mysql=@{status='disabled'}}
    $result.stage='finished';$result.success=$true
  } catch {
    $result.errorType=$_.Exception.GetType().Name
    if($DatabaseEnabled -and -not $result.requiresCommitReconciliation -and $result.mysql.status -ne 'failed'){$result.mysql=@{status='failed';stage=$result.stage}}
  }
  if($DatabaseEnabled){
    # Preserve the conventional latest-import filename for existing readers,
    # but never leave a stale success marker after failed/unattempted recovery.
    $latestStatus=Join-Path $OutputDir 'mysql_import_status.json'
    $temporaryStatus=$latestStatus+'.tmp.'+[Guid]::NewGuid().ToString('N')
    try {
      [IO.File]::WriteAllText($temporaryStatus,($result.mysql | ConvertTo-Json -Depth 15),(New-Object Text.UTF8Encoding($false)))
      if(Test-Path -LiteralPath $latestStatus){[IO.File]::Replace($temporaryStatus,$latestStatus,($latestStatus+'.previous.'+[Guid]::NewGuid().ToString('N')),$true)}
      else{[IO.File]::Move($temporaryStatus,$latestStatus)}
    } catch {
      $result.success=$false
      $result.stage='status_publish'
      $result.errorType=$_.Exception.GetType().Name
    } finally {
      if(Test-Path -LiteralPath $temporaryStatus){Remove-Item -LiteralPath $temporaryStatus -Force}
    }
  }
  return [pscustomobject]$result
}

function Get-KeywordRecoveryMessage($Salvage) {
  if($null -eq $Salvage){return 'Recovery was not attempted; import is unconfirmed.'}
  if($Salvage.importConfirmed){return 'Committed SQLite rows were exported and MySQL import was confirmed.'}
  if($Salvage.exportConfirmed){return 'SQLite export confirmed; MySQL import is NOT confirmed. Keep local files for recovery.'}
  return 'SQLite export and MySQL import are NOT confirmed. Keep local checkpoints for recovery.'
}
