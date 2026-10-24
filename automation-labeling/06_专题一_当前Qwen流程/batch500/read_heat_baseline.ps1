$ErrorActionPreference='Stop'
$TaskNode='C:/Users/YS-Insight/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$TaskCredential=Import-Clixml -LiteralPath 'E:/Codex/work/20261019_两专题每日统计/private/mysql_credential.clixml'
if ($TaskCredential -isnot [Management.Automation.PSCredential]) { throw 'Invalid configured credential' }
$TaskSecretPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($TaskCredential.Password)
try {
  $env:MYSQL_USER=$TaskCredential.UserName
  $env:MYSQL_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($TaskSecretPointer)
  & $TaskNode (Join-Path $PSScriptRoot 'export_heat_baseline.mjs')
  $TaskResultCode=$LASTEXITCODE
} finally {
  $env:MYSQL_PASSWORD=$null
  $env:MYSQL_USER=$null
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($TaskSecretPointer)
  $TaskCredential.Password.Dispose()
}
exit $TaskResultCode
