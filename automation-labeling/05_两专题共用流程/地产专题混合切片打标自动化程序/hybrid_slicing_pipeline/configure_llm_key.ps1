$ErrorActionPreference='Stop'
$taskSecret=$null
$taskSecretPointer=[IntPtr]::Zero
try {
 Write-Host 'Configure YS_LLM_API_KEY for the current Windows user.'
 Write-Host 'Input is hidden. Never paste this key into chat or source code.'
 Write-Host 'The user environment variable persists locally; it is not an encrypted secret vault.'
 $taskSecret=Read-Host 'API key' -AsSecureString
 if($taskSecret.Length -eq 0){throw 'Empty key; configuration unchanged'}
 $taskSecretPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskSecret)
 $taskPlainKey=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskSecretPointer)
 [Environment]::SetEnvironmentVariable('YS_LLM_API_KEY',$taskPlainKey,'User')
 $taskPlainKey=$null
 Write-Host 'Configured successfully. Return to Codex and say: configured.' -ForegroundColor Green
} catch {
 Write-Host 'Configuration failed; please try again. No key is displayed.' -ForegroundColor Red
} finally {
 if($taskSecretPointer -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskSecretPointer)}
 if($taskSecret){$taskSecret.Dispose()}
 $taskPlainKey=$null
}
Read-Host 'Press Enter to close' | Out-Null
