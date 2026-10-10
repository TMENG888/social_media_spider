param([switch]$Once)
$entry = Join-Path $PSScriptRoot 'common\start-central-log-sink.ps1'
& $entry -Once:$Once
exit $LASTEXITCODE
