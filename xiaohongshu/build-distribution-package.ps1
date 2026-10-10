[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Source=[IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$Parent=Split-Path -Parent $Source
$ReleaseRoot=Join-Path $Parent 'release-packages'
$Stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$PackageName="xiaohongshu-distributed-$Stamp"
$Stage=[IO.Path]::GetFullPath((Join-Path $ReleaseRoot $PackageName))
$Zip=Join-Path $ReleaseRoot ($PackageName+'.zip')
if(-not(Test-Path -LiteralPath $ReleaseRoot)){New-Item -ItemType Directory -Path $ReleaseRoot -Force|Out-Null}
$ReleasePrefix=[IO.Path]::GetFullPath($ReleaseRoot).TrimEnd('\')+'\'
if(-not($Stage+'\').StartsWith($ReleasePrefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe staging path'}
if(Test-Path -LiteralPath $Stage){Remove-Item -LiteralPath $Stage -Recurse -Force}
New-Item -ItemType Directory -Path $Stage -Force|Out-Null
Write-Host 'Copying clean deployment files...'
$RoboArgs=@($Source,$Stage,'/E','/R:1','/W:1','/NFL','/NDL','/NJH','/NJS','/NP','/XD','.state','runs','.update-backups','__pycache__','.asr-temp','python-site','release-packages',(Join-Path $Source 'common\test'),(Join-Path $Source 'common\test-support'),(Join-Path $Source 'common\.verification'),(Join-Path $Source 'common\src\src'),'/XF','*.pyc','deployment-file-manifest.json')
& robocopy.exe @RoboArgs
$RoboCode=$LASTEXITCODE
if($RoboCode -ge 8){throw "robocopy failed with exit code $RoboCode"}
Write-Host 'Validating production PowerShell entry points...'
$Scripts=@(Get-ChildItem -LiteralPath $Stage -Recurse -File -Filter '*.ps1' | Where-Object {$_.FullName -notmatch '\\(node_modules|runtime)\\'})
foreach($Script in $Scripts){
  $Tokens=$null
  $ParseErrors=$null
  [Management.Automation.Language.Parser]::ParseFile($Script.FullName,[ref]$Tokens,[ref]$ParseErrors)|Out-Null
  if($ParseErrors.Count){throw "PowerShell parse failed: $($Script.FullName): $($ParseErrors.Message -join '; ')"}
}
$UnexpectedTestFiles=@(Get-ChildItem -LiteralPath $Stage -Recurse -File | Where-Object {
  $_.FullName -match '\\worker-0[1-5]\\' -and $_.Name -match '(?i)test|测试'
})
if($UnexpectedTestFiles.Count){throw 'Worker test artifacts remain in the production package.'}
$ReparseItems=@(Get-ChildItem -LiteralPath $Stage -Recurse -Force | Where-Object {
  ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
})
if($ReparseItems.Count){
  $Names=($ReparseItems | Select-Object -First 20 | ForEach-Object {$_.FullName.Substring($Stage.Length).TrimStart('\')}) -join '; '
  throw "Portable package contains symbolic links or junctions and cannot be copied safely: $Names"
}
Write-Host 'Building SHA-256 deployment manifest...'
$Files=@(Get-ChildItem -LiteralPath $Stage -Recurse -File -Force|Where-Object{$_.Name -ne 'deployment-file-manifest.json'}|Sort-Object FullName)
$Entries=@()
$Index=0
foreach($File in $Files){
  $Index+=1
  $Relative=$File.FullName.Substring($Stage.Length).TrimStart('\').Replace('\','/')
  $Entries += [ordered]@{path=$Relative;length=[long]$File.Length;sha256=(Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash}
  if(($Index % 250) -eq 0){Write-Host "Hashed $Index/$($Files.Count) files..."}
}
$Manifest=[ordered]@{formatVersion=1;createdAt=(Get-Date).ToString('o');fileCount=$Entries.Count;files=$Entries}
$Manifest|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $Stage 'deployment-file-manifest.json') -Encoding UTF8
Write-Host 'Creating ZIP archive...'
Compress-Archive -LiteralPath $Stage -DestinationPath $Zip -CompressionLevel Optimal -Force
$ZipHash=(Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash
($ZipHash+'  '+(Split-Path -Leaf $Zip))|Set-Content -LiteralPath ($Zip+'.sha256.txt') -Encoding ASCII
Remove-Item -LiteralPath $Stage -Recurse -Force
Write-Host "Package: $Zip"
Write-Host "SHA256:  $ZipHash"
