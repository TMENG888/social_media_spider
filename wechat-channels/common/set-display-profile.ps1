param(
  [ValidateSet('auto','2560x1440','1920x1080')][string]$Profile = 'auto',
  [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'

if (-not ('WechatRpaDisplay.NativeMethods' -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace WechatRpaDisplay {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
  public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
    public short dmSpecVersion;
    public short dmDriverVersion;
    public short dmSize;
    public short dmDriverExtra;
    public int dmFields;
    public int dmPositionX;
    public int dmPositionY;
    public int dmDisplayOrientation;
    public int dmDisplayFixedOutput;
    public short dmColor;
    public short dmDuplex;
    public short dmYResolution;
    public short dmTTOption;
    public short dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
    public short dmLogPixels;
    public int dmBitsPerPel;
    public int dmPelsWidth;
    public int dmPelsHeight;
    public int dmDisplayFlags;
    public int dmDisplayFrequency;
    public int dmICMMethod;
    public int dmICMIntent;
    public int dmMediaType;
    public int dmDitherType;
    public int dmReserved1;
    public int dmReserved2;
    public int dmPanningWidth;
    public int dmPanningHeight;
  }

  public static class NativeMethods {
    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern bool EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);
    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern int ChangeDisplaySettings(ref DEVMODE devMode, int flags);
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")]
    public static extern uint GetDpiForSystem();

    public static int[] GetCurrentMode() {
      DEVMODE mode = new DEVMODE();
      mode.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
      if (!EnumDisplaySettings(null, -1, ref mode)) {
        throw new Win32Exception(Marshal.GetLastWin32Error(), "EnumDisplaySettings failed");
      }
      return new int[] { mode.dmPelsWidth, mode.dmPelsHeight };
    }

    public static int ChangeResolution(int width, int height) {
      DEVMODE mode = new DEVMODE();
      mode.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
      if (!EnumDisplaySettings(null, -1, ref mode)) {
        throw new Win32Exception(Marshal.GetLastWin32Error(), "EnumDisplaySettings failed");
      }
      mode.dmPelsWidth = width;
      mode.dmPelsHeight = height;
      mode.dmFields = 0x00080000 | 0x00100000;
      return ChangeDisplaySettings(ref mode, 0x00000001);
    }
  }
}
'@
}

function Get-CurrentDisplayMode {
  try { [void][WechatRpaDisplay.NativeMethods]::SetProcessDPIAware() } catch { }
  $dimensions = [WechatRpaDisplay.NativeMethods]::GetCurrentMode()
  $dpi = 96
  try { $dpi = [int][WechatRpaDisplay.NativeMethods]::GetDpiForSystem() } catch { }
  [pscustomobject]@{
    width = [int]$dimensions[0]
    height = [int]$dimensions[1]
    dpi = $dpi
    scalePercent = [int][Math]::Round(($dpi / 96.0) * 100)
  }
}

$supported = @('2560x1440', '1920x1080')
$supportedScalePercents = @(100, 150)
$before = Get-CurrentDisplayMode
$beforeName = "$($before.width)x$($before.height)"
$changed = $false
$changeCode = 0

if ($supportedScalePercents -notcontains $before.scalePercent) {
  $result = [pscustomobject]@{
    ok = $false; profile = $Profile; before = $beforeName; current = $beforeName
    dpi = $before.dpi; scalePercent = $before.scalePercent; changed = $false
    message = 'Windows display scaling must be 100% or 150% before running the WeChat RPA.'
  }
  $result | ConvertTo-Json -Compress
  exit 3
}

if ($Profile -ne 'auto' -and $beforeName -ne $Profile) {
  if ($ValidateOnly) {
    $result = [pscustomobject]@{
      ok = $false; profile = $Profile; before = $beforeName; current = $beforeName
      dpi = $before.dpi; scalePercent = $before.scalePercent; changed = $false
      message = "Current resolution does not match selected profile $Profile."
    }
    $result | ConvertTo-Json -Compress
    exit 4
  }
  $parts = $Profile.Split('x')
  $changeCode = [WechatRpaDisplay.NativeMethods]::ChangeResolution([int]$parts[0], [int]$parts[1])
  if ($changeCode -ne 0) {
    $result = [pscustomobject]@{
      ok = $false; profile = $Profile; before = $beforeName; current = $beforeName
      dpi = $before.dpi; scalePercent = $before.scalePercent; changed = $false
      changeCode = $changeCode
      message = 'Windows rejected the requested display mode. Select a resolution supported by this monitor.'
    }
    $result | ConvertTo-Json -Compress
    exit 5
  }
  Start-Sleep -Milliseconds 1200
  $changed = $true
}

$after = Get-CurrentDisplayMode
$afterName = "$($after.width)x$($after.height)"
$expected = if ($Profile -eq 'auto') { $supported -contains $afterName } else { $afterName -eq $Profile }
$result = [pscustomobject]@{
  ok = [bool]($expected -and ($supportedScalePercents -contains $after.scalePercent))
  profile = $Profile
  before = $beforeName
  current = $afterName
  dpi = $after.dpi
  scalePercent = $after.scalePercent
  changed = $changed
  changeCode = $changeCode
  message = if ($expected -and ($supportedScalePercents -contains $after.scalePercent)) { 'Display profile is ready.' } elseif (-not $expected) { 'Only 2560x1440 and 1920x1080 are supported.' } else { 'Only 100% and 150% display scaling are supported.' }
}
$result | ConvertTo-Json -Compress
if (-not $result.ok) { exit 6 }
