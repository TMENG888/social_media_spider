param([switch]$FromStdin)
# Local credential setup only. Does not create a bot or send a message.
$ErrorActionPreference='Stop'
$CredentialRoot=Join-Path $PSScriptRoot '.credentials'
$CredentialPath=Join-Path $CredentialRoot 'feishu-bot.xml'
if ($FromStdin) {
  [Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
  try { $SetupInput=[Console]::In.ReadToEnd() | ConvertFrom-Json } catch { throw 'Invalid credential input; no credential saved.' }
  $ExpectedGroup=[string]::Concat([char[]]@(35270,39057,21495,37319,38598,30417,25511,65288,35797,36816,34892,65289))
  if ($SetupInput.confirm -cne 'YES' -or $SetupInput.groupName -ne $ExpectedGroup -or -not $SetupInput.webhook -or -not $SetupInput.signSecret) {
    throw 'Expected confirmed destination and signed-bot credentials; no credential saved.'
  }
  $WebhookSecure=ConvertTo-SecureString -String $SetupInput.webhook -AsPlainText -Force
  $SignSecure=ConvertTo-SecureString -String $SetupInput.signSecret -AsPlainText -Force
  $GroupName=$SetupInput.groupName
  $SetupInput=$null
} else {
  $WebhookSecure=Read-Host 'Feishu custom bot Webhook (hidden input; do not paste into chat)' -AsSecureString
}
$WebhookPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($WebhookSecure)
try {
  $WebhookPlain=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($WebhookPointer)
  $WebhookUri=[Uri]$WebhookPlain
  if ($WebhookUri.Scheme -ne 'https' -or $WebhookUri.Host -ne 'open.feishu.cn' -or -not $WebhookUri.AbsolutePath.StartsWith('/open-apis/bot/v2/hook/') -or $WebhookUri.UserInfo) {
    throw 'Expected official Feishu HTTPS custom bot Webhook; no credential saved.'
  }
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($WebhookPointer)
  $WebhookPlain=$null
}
if (-not $FromStdin) {
  $SignSecure=Read-Host 'Optional bot signing secret (hidden input; Enter if not configured)' -AsSecureString
  $GroupName=Read-Host 'Destination group name (for local audit only)'
}
if (-not $GroupName) { throw 'Destination group name is required; no credential saved.' }
if ($FromStdin) { $Confirm='YES' }
else { $Confirm=Read-Host "Save credentials for group '$GroupName' on THIS Windows account? Type YES" }
if ($Confirm -cne 'YES') { Write-Host 'Cancelled.'; exit 10 }
New-Item -ItemType Directory -Force -Path $CredentialRoot | Out-Null
$TemporaryPath=$CredentialPath+'.tmp.'+[Guid]::NewGuid().ToString('N')
[pscustomobject]@{GroupName=$GroupName;Webhook=$WebhookSecure;SignSecret=$SignSecure;ConfiguredAt=(Get-Date).ToString('o')} | Export-Clixml -LiteralPath $TemporaryPath
if (Test-Path -LiteralPath $CredentialPath) { [System.IO.File]::Replace($TemporaryPath,$CredentialPath,($CredentialPath+'.bak'),$true) }
else { [System.IO.File]::Move($TemporaryPath,$CredentialPath) }
Write-Host 'Credential saved with Windows account-bound encryption. No message sent.'
Write-Host 'Tell the assistant setup is complete; do not send Webhook or signing secret in chat.'
