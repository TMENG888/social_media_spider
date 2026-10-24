[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WorkerRoot)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Text.UTF8Encoding]::new($false)
$previousRedisEnv=@{}
foreach($name in @('REDIS_URL','REDIS_USERNAME','REDIS_PASSWORD')) {
    $previousRedisEnv[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
}
$secure=$null
$exitStatus=1
$phase='ResolveDeployment'
function Get-LocalDeploymentPath([string]$Path) {
    $resolved=Resolve-Path -LiteralPath $Path
    if ($resolved.Provider.Name -ne 'FileSystem') { throw 'LOCAL_FILESYSTEM_REQUIRED' }
    if ($resolved.ProviderPath.StartsWith('\\') -or
        ($resolved.Drive.DisplayRoot -and $resolved.Drive.DisplayRoot.StartsWith('\\')) -or
        ($resolved.Drive.Root -and $resolved.Drive.Root.StartsWith('\\'))) {
        throw 'NETWORK_DEPLOYMENT_UNSUPPORTED'
    }
    return $resolved.ProviderPath
}
try {
    Write-Host '[Login launcher version] 20261020-v6'
    $common=Get-LocalDeploymentPath $PSScriptRoot
    $worker=Get-LocalDeploymentPath $WorkerRoot
    $phase='ReadTaskQueue'
    $queue=Get-Content -LiteralPath (Join-Path $worker 'tasks\task-queue.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($queue.workerId -and $queue.workerId -ne (Split-Path $worker -Leaf)) { throw 'Worker identity mismatch' }
    $state=Join-Path $worker '.state'
    if (((Split-Path (Split-Path $PSScriptRoot -Parent) -Leaf) -in @('xiaohongshu',([string][char]0x5C0F+[char]0x7EA2+[char]0x4E66))) -and $queue.stateRoot) {
        $state=[IO.Path]::GetFullPath((Join-Path (Join-Path $worker 'tasks') $queue.stateRoot))
    }
    $workerPrefix=$worker.TrimEnd([char]92)+[char]92
    if (-not ([IO.Path]::GetFullPath($state)).StartsWith($workerPrefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'State path outside worker' }
    $credential=Join-Path $state 'redis-password.dpapi'
    $phase='ReadLocalRedisConfig'
    $configFile=Join-Path $common 'redis-config.json'
    if (-not (Test-Path -LiteralPath $configFile -PathType Leaf)) { throw 'REDIS_CONFIG_MISSING' }
    try { $redisConfig=Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'REDIS_CONFIG_INVALID' }
    $redisUri=$null
    if (-not [Uri]::TryCreate([string]$redisConfig.url,[UriKind]::Absolute,[ref]$redisUri)) { throw 'REDIS_CONFIG_INVALID' }
    if ($redisUri.Scheme -notin @('redis','rediss') -or -not $redisUri.Host -or
        $redisUri.UserInfo -or $redisUri.Query -or $redisUri.Fragment) { throw 'REDIS_CONFIG_INVALID' }
    # The saved worker credential is paired with this platform's local config.
    # Ignore inherited overrides for this invocation only; restore in finally.
    $env:REDIS_URL=[string]$redisConfig.url
    $env:REDIS_USERNAME=[string]$redisConfig.username
    $env:REDIS_PASSWORD=$null
    $phase='LoadRedisCredential'
    $credentialSource='hidden_prompt'
    if (Test-Path -LiteralPath $credential) {
        try {
            $secure=ConvertTo-SecureString (Get-Content -LiteralPath $credential -Raw -Encoding UTF8).Trim()
            $credentialSource='worker_saved_dpapi'
            Write-Host '[Redis credential] Loaded the saved Windows-encrypted password.'
        } catch {
            Write-Warning 'Saved credential cannot be read by this Windows user. Enter it securely below; it will not be saved.'
        }
    }
    if ($null -eq $secure) {
        $secure=Read-Host 'Redis password (hidden; never printed)' -AsSecureString
    }
    $env:REDIS_PASSWORD=[Net.NetworkCredential]::new('', $secure).Password
    if (-not $env:REDIS_PASSWORD) { throw 'REDIS_CREDENTIAL_EMPTY' }
    Write-Host ('[Redis source] config=platform_local; credential='+$credentialSource+'; inherited Redis overrides ignored for this run.')
    $phase='CheckRuntimeFiles'
    $node=Join-Path $common 'runtime\node\node.exe'
    $entry=Join-Path $common 'src\login-browser.mjs'
    if (-not (Test-Path -LiteralPath $node -PathType Leaf)) { throw 'NODE_RUNTIME_MISSING' }
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'LOGIN_ENTRY_MISSING' }
    $phase='RunLoginRecovery'
    & $node $entry --worker-root $worker
    $exitStatus=$LASTEXITCODE
} catch {
    $safeCode='LOGIN_LAUNCH_FAILED'
    if ($_.Exception.Message -in @('NETWORK_DEPLOYMENT_UNSUPPORTED','LOCAL_FILESYSTEM_REQUIRED','NODE_RUNTIME_MISSING','LOGIN_ENTRY_MISSING','REDIS_CONFIG_MISSING','REDIS_CONFIG_INVALID','REDIS_CREDENTIAL_EMPTY')) { $safeCode=$_.Exception.Message }
    Write-Warning ('[Login recovery] stage='+$phase+'; code='+$safeCode+'; errorType='+$_.Exception.GetType().Name+'; no success confirmed.')
    if ($safeCode -eq 'NETWORK_DEPLOYMENT_UNSUPPORTED') {
        Write-Warning 'Copy the deployment package to a LOCAL folder on this collecting PC, then run its own worker login BAT. Do not run shared browser profiles/state from UNC or mapped network drives. Nothing was copied or cleared.'
    }
    $exitStatus=1
} finally {
    foreach($name in $previousRedisEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name,$previousRedisEnv[$name],'Process')
    }
    if ($null -ne $secure) { $secure.Dispose() }
}
exit $exitStatus
