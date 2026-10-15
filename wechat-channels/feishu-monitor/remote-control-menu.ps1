$ErrorActionPreference='Stop'
Write-Host 'Redis safe-stop control (Xiaohongshu / Douyin). No forced process kills.'
$Platform=(Read-Host 'Platform: xhs or douyin').Trim()
& (Join-Path $PSScriptRoot 'remote-control.ps1') -Platform $Platform -Action status
if($LASTEXITCODE -ne 0){throw 'Status query failed. No command sent.'}
Write-Host 'An empty list means no new-version heartbeat/stop records; it does NOT mean all machines are stopped.'
$Action=(Read-Host 'Action: status / stop / release (Enter to quit)').Trim()
if(-not $Action){exit 0}
$Computer=(Read-Host 'Exact target computer name (hostname on that machine)').Trim().ToUpperInvariant()
$Worker=(Read-Host 'Exact worker ID, for example worker-01').Trim().ToLowerInvariant()
$Parameters=@{Platform=$Platform;Action=$Action;Computer=$Computer;Worker=$Worker}
if($Action -ne 'status'){
  $Target=$Computer+'/'+$Worker
  Write-Host ('Target: '+$Target)
  Write-Host 'Stop only requests safe cleanup. Release only clears the remote hold; it never launches a collector.'
  $Parameters.ConfirmTarget=(Read-Host ('Type '+$Target+' to confirm')).Trim()
  if($Action -eq 'release'){$Parameters.CommandId=(Read-Host 'Exact commandId from the latest status output').Trim()}
}
& (Join-Path $PSScriptRoot 'remote-control.ps1') @Parameters
exit $LASTEXITCODE
