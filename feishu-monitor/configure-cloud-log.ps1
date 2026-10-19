[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
# This setup does not send messages or modify any cloud document.
$credentialRoot = Join-Path $PSScriptRoot '.credentials'
$credentialPath = Join-Path $credentialRoot 'feishu-doc-app.xml'
Write-Host 'Configure a published Feishu internal app with access to the dedicated log document.'
Write-Host 'Enter credentials ONLY here, never in chat. Both inputs are hidden.'
$idSecure = Read-Host 'App ID' -AsSecureString
$secretSecure = Read-Host 'App Secret' -AsSecureString
try {
    $idCredential = New-Object System.Management.Automation.PSCredential('app', $idSecure)
    $appId = $idCredential.GetNetworkCredential().Password
    if ($appId -notmatch '^cli_[A-Za-z0-9]+$' -or $secretSecure.Length -lt 8) {
        throw 'Invalid App ID or empty/short secret; nothing saved.'
    }
    $confirm = Read-Host 'Save for THIS Windows user and enable log sync on future reports? Type YES'
    if ($confirm -cne 'YES') { Write-Host 'Cancelled; nothing saved.'; exit 10 }
    New-Item -ItemType Directory -Force -Path $credentialRoot | Out-Null
    $temp = $credentialPath + '.tmp.' + [Guid]::NewGuid().ToString('N')
    [pscustomobject]@{
        AppId = $idSecure; AppSecret = $secretSecure
        ConfiguredAt = [DateTimeOffset]::Now.ToString('o')
    } | Export-Clixml -LiteralPath $temp
    if (Test-Path -LiteralPath $credentialPath) {
        [IO.File]::Replace($temp, $credentialPath, $credentialPath + '.bak', $true)
    } else { [IO.File]::Move($temp, $credentialPath) }
    Write-Host 'Saved with Windows user-bound encryption. No API call or message sent.'
    Write-Host 'Next: run sync-cloud-log.ps1 -Check, then sync-cloud-log.ps1 to sync without resending a group card.'
} finally {
    $appId = $null; $idCredential = $null
    if ($idSecure) { $idSecure.Dispose() }
    if ($secretSecure) { $secretSecure.Dispose() }
}
