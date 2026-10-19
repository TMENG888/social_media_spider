[CmdletBinding()]
param([switch]$Check)
$ErrorActionPreference = 'Stop'
$cloudMutex = New-Object System.Threading.Mutex($false, 'Local\SocialMediaFeishuCloudLogSync')
$locked = $false
$syncExitCode = 1
$oldId = $env:FEISHU_DOC_APP_ID
$oldSecret = $env:FEISHU_DOC_APP_SECRET
$appCredential = $null
try {
    try { $locked = $cloudMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Another cloud synchronization is active; not confirmed.' }
    $credentialPath = Join-Path $PSScriptRoot '.credentials\feishu-doc-app.xml'
    $useCloudCli = Test-Path -LiteralPath (Join-Path $PSScriptRoot 'cloud-log-cli.json')
    if (-not $useCloudCli -and (Test-Path -LiteralPath $credentialPath)) {
        try {
            $appCredential = Import-Clixml -LiteralPath $credentialPath
            $idCredential = New-Object System.Management.Automation.PSCredential('id', $appCredential.AppId)
            $secretCredential = New-Object System.Management.Automation.PSCredential('secret', $appCredential.AppSecret)
            $env:FEISHU_DOC_APP_ID = $idCredential.GetNetworkCredential().Password
            $env:FEISHU_DOC_APP_SECRET = $secretCredential.GetNetworkCredential().Password
        } catch { throw 'Document app credential cannot be decrypted by this Windows user.' }
    }
    . (Join-Path $PSScriptRoot 'monitor-paths.ps1')
    $config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $videoName = -join @([char]0x89C6, [char]0x9891, [char]0x53F7)
    $platformRoot = Get-MonitorPlatformRoot -MonitorRoot $PSScriptRoot -PlatformName $videoName -Config $config
    $cloudPython = Join-Path $platformRoot 'common\runtime\python\python.exe'
    if (-not (Test-Path -LiteralPath $cloudPython)) { $cloudPython = (Get-Command python -ErrorAction Stop).Source }
    $syncModule = if ($useCloudCli) { 'lark_cloud_log.py' } else { 'cloud_log.py' }
    $syncArgs = @((Join-Path $PSScriptRoot $syncModule))
    if ($Check) { $syncArgs += '--check' }
    & $cloudPython @syncArgs
    $syncExitCode = $LASTEXITCODE
} catch {
    # Never emit raw exception text, which may contain credential material.
    Write-Host 'Cloud log sync NOT confirmed: local setup/runtime failure. See CLOUD-LOG-SETUP.md.'
    $syncExitCode = 1
} finally {
    $env:FEISHU_DOC_APP_ID = $oldId; $env:FEISHU_DOC_APP_SECRET = $oldSecret
    $idCredential = $null; $secretCredential = $null; $appCredential = $null
    if ($locked) { $cloudMutex.ReleaseMutex() }
    $cloudMutex.Dispose()
}
exit $syncExitCode
