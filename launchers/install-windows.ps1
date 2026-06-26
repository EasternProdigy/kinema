# Add a Kinema icon to your Windows desktop & Start Menu (opt-in — only run this
# if you want the icon). By default the icon opens Kinema as a normal browser
# tab; pass a mode to change that:
#   powershell -ExecutionPolicy Bypass -File launchers\install-windows.ps1          # tab (default)
#   powershell -ExecutionPolicy Bypass -File launchers\install-windows.ps1 app      # dedicated window
#   powershell -ExecutionPolicy Bypass -File launchers\install-windows.ps1 kiosk    # fullscreen
param([ValidateSet("tab", "app", "kiosk")][string]$Mode = "tab")
$ErrorActionPreference = "Stop"

$Dir  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$flag = @{ tab = ""; app = "--app"; kiosk = "--kiosk" }[$Mode]
$bat  = Join-Path $Dir "launchers\Kinema.bat"
$exe  = Join-Path $Dir "kinema.exe"
$icon = Join-Path $Dir "launchers\kinema.ico"

# Release bundle ships kinema.exe at the root; a source checkout uses the .bat.
if (Test-Path $exe) { $target = $exe; $arguments = $flag }
else                { $target = $bat; $arguments = $flag }

$ws = New-Object -ComObject WScript.Shell
function New-KinemaShortcut([string]$LnkPath) {
  $sc = $ws.CreateShortcut($LnkPath)
  $sc.TargetPath       = $target
  $sc.Arguments        = $arguments
  $sc.WorkingDirectory = $Dir
  $sc.WindowStyle      = 7    # start minimized so the console stays out of the way
  $sc.Description      = "Kinema - your video library in a browser"
  if (Test-Path $icon) { $sc.IconLocation = $icon }
  $sc.Save()
}

$desktop  = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
New-KinemaShortcut (Join-Path $desktop  "Kinema.lnk")
New-KinemaShortcut (Join-Path $programs "Kinema.lnk")

Write-Host "Installed Kinema shortcuts (mode: $Mode) on your Desktop and Start Menu." -ForegroundColor Green
