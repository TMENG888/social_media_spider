param([switch]$Send,[switch]$AlertsOnly,[switch]$Watch,
      [ValidatePattern('^[a-zA-Z0-9_-]{1,100}$')][string]$RunId)
$ErrorActionPreference='Stop'
$monitorStage='INITIALIZE'
$monitorRunRecord=$null
$monitorRunPath=$null
$savedPythonEncoding=$env:PYTHONIOENCODING
$savedNoBytecode=$env:PYTHONDONTWRITEBYTECODE
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
function Save-MonitorRun {
  if($monitorRunPath){
    [IO.Directory]::CreateDirectory((Split-Path -Parent $monitorRunPath)) | Out-Null
    [IO.File]::WriteAllText($monitorRunPath+'.tmp',($monitorRunRecord|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath ($monitorRunPath+'.tmp') -Destination $monitorRunPath -Force
  }
}
function Set-MonitorStage([string]$Stage){
  $script:monitorStage=$Stage
  if($monitorRunRecord){$monitorRunRecord.stage=$Stage;Save-MonitorRun}
}
if($RunId){
  $monitorRunPath=Join-Path $PSScriptRoot ('output\runner\'+$RunId+'.json')
  $monitorRunRecord=[ordered]@{runId=$RunId;status='running';stage=$monitorStage;errorCode=$null;errorType=$null;
    startedAt=[DateTimeOffset]::Now.ToString('o');finishedAt=$null}
  Save-MonitorRun
}
$monitorMutex=New-Object System.Threading.Mutex($false,'Local\ChannelsFeishuMonitor20260926Prod01')
$monitorLockAcquired=$false
try {
  try {$monitorLockAcquired=$monitorMutex.WaitOne(0)} catch [System.Threading.AbandonedMutexException] {$monitorLockAcquired=$true}
  if (-not $monitorLockAcquired) {
    if($monitorRunRecord){$monitorRunRecord.status='skipped_existing_run'}
    Write-Host 'Monitor already collecting/publishing; skipped overlapping run.'; exit 0
  }
$monitorRoot=$PSScriptRoot
. (Join-Path $monitorRoot 'monitor-paths.ps1')
$config=Get-Content -LiteralPath (Join-Path $monitorRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$channelsCommon=Join-Path (Get-MonitorPlatformRoot -MonitorRoot $monitorRoot -PlatformName '视频号' -Config $config) 'common'
$python=Join-Path $channelsCommon 'runtime\python\python.exe'
$monitorNode=Join-Path $channelsCommon 'runtime\node\node.exe'
if (-not (Test-Path -LiteralPath $python)) {$python=(Get-Command python -ErrorAction Stop).Source}
if (-not (Test-Path -LiteralPath $monitorNode)) {$monitorNode=(Get-Command node -ErrorAction Stop).Source}
Set-MonitorStage 'COLLECT_REDIS'
& $python (Join-Path $monitorRoot 'collect.py')
if ($LASTEXITCODE -ne 0) {throw 'Monitor collection failed'}
# Read-only local process evidence. Never export raw command lines or treat this
# sampling as a worker-emitted heartbeat; remote machines remain unconfirmed.
$observedProcesses=@(Get-CimInstance Win32_Process)
$localSupervisors=@()
$packageRoot=Split-Path -Parent $monitorRoot
foreach($platformName in @((-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66)),(-join @([char]0x6296,[char]0x97F3)))) {
  $platformDirectory=if($platformName -eq (-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66))){'xiaohongshu'}else{'douyin'}
  if($config.platform_directories -and $config.platform_directories.$platformName){$platformDirectory=$config.platform_directories.$platformName}
  $platformPath=Get-MonitorPlatformRoot -MonitorRoot $monitorRoot -PlatformName $platformName -Config $config
  foreach($observedProcess in $observedProcesses) {
    if($observedProcess.Name -ne 'powershell.exe' -or -not $observedProcess.CommandLine){continue}
    $workerMatch=[regex]::Match($observedProcess.CommandLine,[regex]::Escape($platformPath)+'[\\/](worker-[0-9]{2})[\\/]run-worker\.ps1',[Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if(-not $workerMatch.Success){continue}
    $descendantIds=@([uint32]$observedProcess.ProcessId)
    for($depth=0;$depth -lt 5;$depth++) {
      $children=@($observedProcesses | Where-Object {$_.ParentProcessId -in $descendantIds -and $_.ProcessId -notin $descendantIds})
      if(-not $children.Count){break}
      $descendantIds+=@($children.ProcessId)
    }
    $collectorCount=@($observedProcesses | Where-Object {$_.ProcessId -in $descendantIds -and $_.Name -eq 'node.exe' -and $_.CommandLine -match '(run-worker|index)\.mjs'}).Count
    $localSupervisors+=@{platform=$platformName;worker=$workerMatch.Groups[1].Value;supervisorPid=$observedProcess.ProcessId;collectorCount=$collectorCount;createdAt=$observedProcess.CreationDate.ToUniversalTime().ToString('o')}
  }
}
$processEvidence=@{sampledAt=[DateTime]::UtcNow.ToString('o');computer=$env:COMPUTERNAME;supervisors=$localSupervisors}
$processOutput=Join-Path $monitorRoot 'output\local-supervisors.json'
[IO.File]::WriteAllText($processOutput+'.tmp',($processEvidence|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath ($processOutput+'.tmp') -Destination $processOutput -Force
# Independent read-only platform observations; reuse credentials without copying them.
$oldPlatformRedisPassword=$env:MONITOR_PLATFORM_REDIS_PASSWORD
Set-MonitorStage 'COLLECT_PLATFORMS'
try {
  $reportPlatforms=@((-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66)),(-join @([char]0x6296,[char]0x97F3)))
  foreach ($reportPlatform in $reportPlatforms) {
    $env:MONITOR_PLATFORM_REDIS_PASSWORD=$null
    $platformSecure=$null
    $platformPointer=[IntPtr]::Zero
    try {
      $platformDirectory=if($reportPlatform -eq (-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66))){'xiaohongshu'}else{'douyin'}
      if($config.platform_directories -and $config.platform_directories.$reportPlatform){$platformDirectory=$config.platform_directories.$reportPlatform}
      $platformCredentialPath=Join-Path (Get-MonitorPlatformRoot -MonitorRoot $monitorRoot -PlatformName $reportPlatform -Config $config) 'worker-01\.state\redis-password.dpapi'
      if (Test-Path -LiteralPath $platformCredentialPath) {
        $platformCipher=(Get-Content -LiteralPath $platformCredentialPath -Raw -Encoding UTF8).Trim()
        $platformSecure=ConvertTo-SecureString -String $platformCipher
        $platformPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($platformSecure)
        $env:MONITOR_PLATFORM_REDIS_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($platformPointer)
      }
    } catch {
      Write-Host ('Monitor credential diagnostic: '+(@{platform=$reportPlatform;errorCode='PLATFORM_CREDENTIAL_UNAVAILABLE';errorType=$_.Exception.GetType().Name}|ConvertTo-Json -Compress))
    }
    finally {
      if ($platformPointer -ne [IntPtr]::Zero) {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($platformPointer)}
      if ($platformSecure) {$platformSecure.Dispose()}
      $platformCipher=$null
    }
    & $python (Join-Path $monitorRoot 'platform_tasks.py') --platform $reportPlatform
    if ($LASTEXITCODE -ne 0) {throw 'Platform observation failed'}
  }
} finally {$env:MONITOR_PLATFORM_REDIS_PASSWORD=$oldPlatformRedisPassword}
$credentialPath=Join-Path $monitorRoot $config.mysql_credential
$oldMysqlUser=$env:MYSQL_USER
$oldMysqlPassword=$env:MYSQL_PASSWORD
$monitorMysqlSaved=@{}
Set-MonitorStage 'COLLECT_DATABASE'
foreach($monitorMysqlName in @('MYSQL_HOST','MYSQL_PORT','MYSQL_DATABASE')){$monitorMysqlSaved[$monitorMysqlName]=[Environment]::GetEnvironmentVariable($monitorMysqlName,'Process')}
try {
  $monitorMysqlDefaults=Get-Content -LiteralPath (Join-Path $channelsCommon 'src\mysql-defaults.json') -Raw -Encoding UTF8|ConvertFrom-Json
  if(-not $env:MYSQL_HOST){$env:MYSQL_HOST=$monitorMysqlDefaults.host}
  if(-not $env:MYSQL_PORT){$env:MYSQL_PORT=[string]$monitorMysqlDefaults.port}
  if(-not $env:MYSQL_DATABASE){$env:MYSQL_DATABASE=$monitorMysqlDefaults.database}
  if (Test-Path -LiteralPath $credentialPath) {
    $monitorCredential=Import-Clixml -LiteralPath $credentialPath
    $env:MYSQL_USER=$monitorCredential.UserName
    $env:MYSQL_PASSWORD=$monitorCredential.GetNetworkCredential().Password
  }
  & $monitorNode (Join-Path $monitorRoot 'database.mjs')
  if ($LASTEXITCODE -ne 0) {throw 'Database observation failed'}
} finally {
  $env:MYSQL_USER=$oldMysqlUser
  $env:MYSQL_PASSWORD=$oldMysqlPassword
  $monitorCredential=$null
  foreach($monitorMysqlName in $monitorMysqlSaved.Keys){[Environment]::SetEnvironmentVariable($monitorMysqlName,$monitorMysqlSaved[$monitorMysqlName],'Process')}
}
$publishArgs=@((Join-Path $monitorRoot 'publish.py'))
if ($Send) {$publishArgs+='--send'}
if ($AlertsOnly) {$publishArgs+='--alerts-only'}
if ($Watch) {$publishArgs+='--watch'}
if ($RunId) {$publishArgs+=@('--run-id',$RunId)}
$oldWebhook=$env:FEISHU_WEBHOOK
$oldSignSecret=$env:FEISHU_SIGN_SECRET
Set-MonitorStage 'PUBLISH'
try {
  $botCredentialPath=Join-Path $monitorRoot '.credentials\feishu-bot.xml'
  if ($Send -and -not $env:FEISHU_WEBHOOK -and (Test-Path -LiteralPath $botCredentialPath)) {
    $botCredential=Import-Clixml -LiteralPath $botCredentialPath
    $webhookCredential=New-Object System.Management.Automation.PSCredential('webhook',$botCredential.Webhook)
    $env:FEISHU_WEBHOOK=$webhookCredential.GetNetworkCredential().Password
    if ($botCredential.SignSecret -and $botCredential.SignSecret.Length -gt 0) {
      $signCredential=New-Object System.Management.Automation.PSCredential('sign',$botCredential.SignSecret)
      $env:FEISHU_SIGN_SECRET=$signCredential.GetNetworkCredential().Password
    }
    Write-Host 'Feishu credential loaded from local encrypted file.'
  }
  & $python @publishArgs
  if ($LASTEXITCODE -ne 0) {throw 'Monitor publishing failed'}
} finally {
  $env:FEISHU_WEBHOOK=$oldWebhook
  $env:FEISHU_SIGN_SECRET=$oldSignSecret
  $botCredential=$null
  $webhookCredential=$null
  $signCredential=$null
}
if ($Send) {
  Set-MonitorStage 'SYNC_CLOUD'
  # Separate cloud result. This also catches up archived reports when Watch skips a card.
  # The independent entry never invokes publish.py or resends a group message.
  $cloudPowerShell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  & $cloudPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $monitorRoot 'sync-cloud-log.ps1')
  if ($LASTEXITCODE -ne 0) {throw 'Group/report result is separate: cloud log synchronization NOT confirmed.'}
}
Set-MonitorStage 'COMPLETE'
if($monitorRunRecord){$monitorRunRecord.status='success'}
} catch {
  if($monitorRunRecord){
    $monitorRunRecord.status='failed'
    $monitorRunRecord.errorCode='MONITOR_'+$monitorStage+'_FAILED'
    $monitorRunRecord.errorType=$_.Exception.GetType().Name
  }
  Write-Host ('Monitor diagnostic: '+(@{stage=$monitorStage;errorCode=('MONITOR_'+$monitorStage+'_FAILED');errorType=$_.Exception.GetType().Name}|ConvertTo-Json -Compress))
  throw ('Monitor stage failed: '+$monitorStage)
} finally {
  if($monitorRunRecord){$monitorRunRecord.finishedAt=[DateTimeOffset]::Now.ToString('o');Save-MonitorRun}
  $env:PYTHONIOENCODING=$savedPythonEncoding
  $env:PYTHONDONTWRITEBYTECODE=$savedNoBytecode
  if ($monitorLockAcquired) {$monitorMutex.ReleaseMutex()}
  $monitorMutex.Dispose()
}
