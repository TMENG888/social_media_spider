[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Common=Split-Path -Parent $MyInvocation.MyCommand.Path
$PortablePython=Join-Path $Common 'runtime\python\python.exe'
$Python=if(Test-Path -LiteralPath $PortablePython){$PortablePython}else{(Get-Command python -ErrorAction Stop).Source}
$Target=Join-Path $Common 'runtime\python-site'
$Requirements=Join-Path $Common 'requirements-asr.txt'
if(-not(Test-Path -LiteralPath $Requirements)){throw "Missing requirements file: $Requirements"}
if(-not(Test-Path -LiteralPath $Target)){New-Item -ItemType Directory -Path $Target -Force|Out-Null}
$OldPythonPath=$env:PYTHONPATH
try {
  $env:PYTHONUTF8='1'
  $env:PYTHONPATH=if($OldPythonPath){"$Target;$OldPythonPath"}else{$Target}
  Write-Host "Installing ASR dependencies into $Target"
  & $Python '-m' 'pip' 'install' '--disable-pip-version-check' '--no-input' '--prefer-binary' '--upgrade' '--target' $Target '-r' $Requirements
  if($LASTEXITCODE -ne 0){throw "pip failed with exit code $LASTEXITCODE"}
  & $Python '-B' '-c' "import faster_whisper, av, numpy; print('ASR dependencies ready')"
  if($LASTEXITCODE -ne 0){throw "ASR import check failed with exit code $LASTEXITCODE"}
  Write-Host 'ASR dependency installation completed.'
} finally {
  $env:PYTHONPATH=$OldPythonPath
}
