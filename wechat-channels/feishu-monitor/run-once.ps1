param([switch]$Send,[switch]$AlertsOnly,[switch]$Watch)
$ErrorActionPreference='Stop'
$monitorMutex=New-Object System.Threading.Mutex($false,'Local\ChannelsFeishuMonitor20260926Prod01')
$monitorLockAcquired=$false
try {
  try {$monitorLockAcquired=$monitorMutex.WaitOne(0)} catch [System.Threading.AbandonedMutexException] {$monitorLockAcquired=$true}
  if (-not $monitorLockAcquired) {Write-Host 'Monitor already collecting/publishing; skipped overlapping run.'; exit 0}
$monitorRoot=$PSScriptRoot
$config=Get-Content -LiteralPath (Join-Path $monitorRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$python=Join-Path $monitorRoot '..\common\runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {$python=(Get-Command python -ErrorAction Stop).Source}
& $python (Join-Path $monitorRoot 'collect.py')
if ($LASTEXITCODE -ne 0) {throw 'Monitor collection failed'}
# Read-only local process evidence. Never export raw command lines or treat this
# sampling as a worker-emitted heartbeat; remote machines remain unconfirmed.
$observedProcesses=@(Get-CimInstance Win32_Process)
$localSupervisors=@()
$packageRoot=Split-Path -Parent (Split-Path -Parent $monitorRoot)
foreach($platformName in @((-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66)),(-join @([char]0x6296,[char]0x97F3)))) {
  $platformDirectory=if($platformName -eq (-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66))){'xiaohongshu'}else{'douyin'}
  if($config.platform_directories -and $config.platform_directories.$platformName){$platformDirectory=$config.platform_directories.$platformName}
  $platformPath=Join-Path $packageRoot $platformDirectory
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
try {
  $reportPlatforms=@((-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66)),(-join @([char]0x6296,[char]0x97F3)))
  foreach ($reportPlatform in $reportPlatforms) {
    $env:MONITOR_PLATFORM_REDIS_PASSWORD=$null
    $platformSecure=$null
    $platformPointer=[IntPtr]::Zero
    try {
      $platformDirectory=if($reportPlatform -eq (-join @([char]0x5C0F,[char]0x7EA2,[char]0x4E66))){'xiaohongshu'}else{'douyin'}
      if($config.platform_directories -and $config.platform_directories.$reportPlatform){$platformDirectory=$config.platform_directories.$reportPlatform}
      $platformCredentialPath=Join-Path $monitorRoot "..\..\$platformDirectory\worker-01\.state\redis-password.dpapi"
      if (Test-Path -LiteralPath $platformCredentialPath) {
        $platformCipher=(Get-Content -LiteralPath $platformCredentialPath -Raw -Encoding UTF8).Trim()
        $platformSecure=ConvertTo-SecureString -String $platformCipher
        $platformPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($platformSecure)
        $env:MONITOR_PLATFORM_REDIS_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($platformPointer)
      }
    } catch { Write-Host "$reportPlatform encrypted credential unavailable; observer will report unknown." }
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
try {
  if (Test-Path -LiteralPath $credentialPath) {
    $monitorCredential=Import-Clixml -LiteralPath $credentialPath
    $env:MYSQL_USER=$monitorCredential.UserName
    $env:MYSQL_PASSWORD=$monitorCredential.GetNetworkCredential().Password
  }
  & node (Join-Path $monitorRoot 'database.mjs')
  if ($LASTEXITCODE -ne 0) {throw 'Database observation failed'}
} finally {
  $env:MYSQL_USER=$oldMysqlUser
  $env:MYSQL_PASSWORD=$oldMysqlPassword
  $monitorCredential=$null
}
$publishArgs=@((Join-Path $monitorRoot 'publish.py'))
if ($Send) {$publishArgs+='--send'}
if ($AlertsOnly) {$publishArgs+='--alerts-only'}
if ($Watch) {$publishArgs+='--watch'}
$oldWebhook=$env:FEISHU_WEBHOOK
$oldSignSecret=$env:FEISHU_SIGN_SECRET
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
} finally {
  if ($monitorLockAcquired) {$monitorMutex.ReleaseMutex()}
  $monitorMutex.Dispose()
}
