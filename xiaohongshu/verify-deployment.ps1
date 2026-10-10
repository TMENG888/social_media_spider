[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Root=[IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$ManifestPath=Join-Path $Root 'deployment-file-manifest.json'
if(-not(Test-Path -LiteralPath $ManifestPath)){throw "Missing deployment manifest: $ManifestPath"}
$Manifest=Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8|ConvertFrom-Json
$Prefix=$Root.TrimEnd('\')+'\'
$ReparseItems=@(Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {
  ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
})
if($ReparseItems.Count){
  Write-Host 'Symbolic links or junctions were found. This folder is not a clean portable deployment.'
  $ReparseItems|Select-Object -First 30|ForEach-Object{Write-Host "  $($_.FullName)"}
  throw 'Deployment verification failed because reparse-point files cannot be safely migrated with Windows Explorer.'
}
$Missing=New-Object System.Collections.Generic.List[string]
$WrongSize=New-Object System.Collections.Generic.List[string]
$WrongHash=New-Object System.Collections.Generic.List[string]
$Index=0
foreach($Entry in @($Manifest.files)){
  $Index+=1
  $Relative=[string]$Entry.path
  $Full=[IO.Path]::GetFullPath((Join-Path $Root ($Relative.Replace('/','\'))))
  if(-not $Full.StartsWith($Prefix,[StringComparison]::OrdinalIgnoreCase)){throw "Manifest path escapes deployment root: $Relative"}
  if(-not(Test-Path -LiteralPath $Full -PathType Leaf)){$Missing.Add($Relative);continue}
  $Item=Get-Item -LiteralPath $Full
  if([long]$Item.Length -ne [long]$Entry.length){$WrongSize.Add($Relative);continue}
  $Hash=(Get-FileHash -LiteralPath $Full -Algorithm SHA256).Hash
  if($Hash -ne [string]$Entry.sha256){$WrongHash.Add($Relative)}
  if(($Index % 250) -eq 0){Write-Host "Verified $Index/$($Manifest.fileCount) files..."}
}
Write-Host "Deployment verification: files=$($Manifest.fileCount), missing=$($Missing.Count), wrongSize=$($WrongSize.Count), wrongHash=$($WrongHash.Count)"
if($Missing.Count){Write-Host 'Missing files:'; $Missing|Select-Object -First 30|ForEach-Object{Write-Host "  $_"}}
if($WrongSize.Count){Write-Host 'Wrong-size files:'; $WrongSize|Select-Object -First 30|ForEach-Object{Write-Host "  $_"}}
if($WrongHash.Count){Write-Host 'Hash-mismatch files:'; $WrongHash|Select-Object -First 30|ForEach-Object{Write-Host "  $_"}}
if($Missing.Count -or $WrongSize.Count -or $WrongHash.Count){throw 'Deployment verification failed. Do not start a worker from this folder.'}
Write-Host 'Deployment verification passed.'
