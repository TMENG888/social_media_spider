param(
    [ValidateSet('Start','Stop','Status','InstallStartup','RemoveStartup')]
    [string]$Action = 'Status',
    [string]$Python = 'python',
    [string]$PythonWindowless = 'pythonw',
    [string]$Config = (Join-Path $PSScriptRoot 'config.json'),
    [string]$TaskName = 'SocialMedia-Feishu-LoginBot'
)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskConfig = (Resolve-Path -LiteralPath $Config).Path
$botConfig = Get-Content -LiteralPath $taskConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeRoot = $botConfig.runtime_dir
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$taskPython = (Get-Command $Python -ErrorAction Stop).Source
$taskPythonWindowless = $PythonWindowless
$taskScript = Join-Path $taskRoot 'bot.py'
$taskName = $TaskName
switch ($Action) {
    'Start' {
        $statusPath = Join-Path $runtimeRoot 'status.json'
        if (Test-Path -LiteralPath $statusPath) {
            $serviceState = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            $existingProcess = Get-Process -Id $serviceState.pid -ErrorAction SilentlyContinue
            $nowSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            if ($existingProcess -and -not $serviceState.stopped -and ($nowSeconds - $serviceState.updated) -lt 20) {
                Write-Output ('Already running: ' + $serviceState.pid)
                return
            }
        }
        $taskArguments = @('-B', ('"' + $taskScript + '"'), 'run', '--config', ('"' + $taskConfig + '"'))
        $taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'process.stdout.log') -RedirectStandardError (Join-Path $runtimeRoot 'process.stderr.log')
        Write-Output ('Started PID: ' + $taskProcess.Id)
    }
    'Stop' {
        New-Item -ItemType File -Path (Join-Path $runtimeRoot 'stop.request') -Force | Out-Null
        Write-Output 'Graceful stop requested; current request can take up to three minutes to finish.'
    }
    'Status' {
        $statusPath = Join-Path $runtimeRoot 'status.json'
        if (Test-Path -LiteralPath $statusPath) { Get-Content -LiteralPath $statusPath -Raw }
        else { Write-Output 'No status file yet.' }
    }
    'InstallStartup' {
        $taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $taskArguments = '-B "' + $taskScript + '" run --config "' + $taskConfig + '"'
        $taskPythonWindowless = (Get-Command $PythonWindowless -ErrorAction Stop).Source
        $scheduledAction = New-ScheduledTaskAction -Execute $taskPythonWindowless -Argument $taskArguments -WorkingDirectory $taskRoot
        $scheduledTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
        $scheduledPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
        $scheduledSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        $previousTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($previousTask) {
            Set-ScheduledTask -TaskName $taskName -Action $scheduledAction -Trigger $scheduledTrigger -Principal $scheduledPrincipal -Settings $scheduledSettings | Select-Object TaskName,State
        } else {
            Register-ScheduledTask -TaskName $taskName -Action $scheduledAction -Trigger $scheduledTrigger -Principal $scheduledPrincipal -Settings $scheduledSettings -Description 'Feishu login maintenance bot; configured chat only, mention commands, single model worker.' | Select-Object TaskName,State
        }
    }
    'RemoveStartup' {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
}
