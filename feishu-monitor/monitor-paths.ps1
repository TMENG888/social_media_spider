function Get-MonitorPlatformRoot {
 param([string]$MonitorRoot,[string]$PlatformName,[object]$Config)
 $MonitorPackageRoot=Split-Path -Parent $MonitorRoot
 $MonitorDirectory=@{'小红书'='xiaohongshu';'抖音'='douyin';'视频号'='wechat-channels'}[$PlatformName]
 if($Config -and $Config.platform_directories -and $Config.platform_directories.$PlatformName){$MonitorDirectory=$Config.platform_directories.$PlatformName}
 elseif(Test-Path -LiteralPath (Join-Path $MonitorPackageRoot $PlatformName)){$MonitorDirectory=$PlatformName}
 $MonitorResolved=[IO.Path]::GetFullPath((Join-Path $MonitorPackageRoot $MonitorDirectory))
 if(-not $MonitorResolved.StartsWith([IO.Path]::GetFullPath($MonitorPackageRoot).TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'PLATFORM_DIRECTORY_OUTSIDE_PACKAGE'}
 return $MonitorResolved
}
