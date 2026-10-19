[CmdletBinding(SupportsShouldProcess=$true)]
param()
$ErrorActionPreference = 'Stop'
$taskName = 'SocialMedia-Feishu-Daily-09-14-18'
$monitorRoot = $PSScriptRoot
if ((Get-TimeZone).Id -ne 'China Standard Time') { throw 'Expected Beijing system timezone; no task was changed.' }
$entry = Join-Path $monitorRoot 'run-scheduled-report.ps1'
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'Scheduled report entry missing.' }
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $entry + '"'
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing -and ($existing.Description -notlike 'Managed Feishu three-platform daily report.*' -or
    @($existing.Actions).Count -ne 1 -or $existing.Actions[0].Arguments -ne $arguments)) {
    throw 'A different task already uses this name; no task was changed.'
}
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $monitorRoot
$triggers = @(9,14,18 | ForEach-Object { New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.AddHours($_)) })
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$description = 'Managed Feishu three-platform daily report. Beijing 09:00/14:00/18:00. Requires the current Windows user to be logged on for existing DPAPI credentials. No automatic send retry.'
if ($PSCmdlet.ShouldProcess($taskName, 'Register Windows daily Feishu report')) {
    Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description $description -Force | Out-Null
    $registered = Get-ScheduledTask -TaskName $taskName -TaskPath '\'
    if (@($registered.Triggers).Count -ne 3 -or $registered.Principal.LogonType -ne 'Interactive' -or
        $registered.Actions[0].Arguments -ne $arguments -or -not $registered.Settings.Enabled) { throw 'Task registration verification failed.' }
    Write-Host ('Registered and verified: ' + $taskName)
}
