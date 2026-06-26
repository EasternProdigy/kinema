# Kinema one-line installer for Windows.
#
#   irm https://raw.githubusercontent.com/EasternProdigy/kinema/main/install.ps1 | iex
#
# Downloads the latest release (ffmpeg bundled — nothing else to install) and
# launches it. Falls back to running from source with Python if no build exists.
#
# Env overrides: KINEMA_REPO, KINEMA_HOME (install dir).
$ErrorActionPreference = "Stop"

$Repo = if ($env:KINEMA_REPO) { $env:KINEMA_REPO } else { "EasternProdigy/kinema" }
$Dest = if ($env:KINEMA_HOME) { $env:KINEMA_HOME } else { Join-Path $env:LOCALAPPDATA "Kinema" }

Write-Host "Kinema installer — finding the latest release of $Repo ..." -ForegroundColor Cyan
try {
  $rel   = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "kinema-installer" }
  $asset = $rel.assets | Where-Object { $_.name -eq "kinema-windows.zip" } | Select-Object -First 1
} catch {
  $asset = $null
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

if ($asset) {
  $zip = Join-Path $env:TEMP "kinema.zip"
  Write-Host "Downloading $($asset.name) ..." -ForegroundColor Cyan
  Invoke-WebRequest $asset.browser_download_url -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $Dest -Force
  Remove-Item $zip
  Write-Host "Installed to $Dest" -ForegroundColor Green
  Write-Host "Starting Kinema ..." -ForegroundColor Cyan
  & (Join-Path $Dest "kinema.exe")
}
else {
  Write-Host "No release binary found — falling back to source (needs Python 3)." -ForegroundColor Yellow
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
  if (-not $py) { throw "Python 3 is required. Install from https://www.python.org/downloads/ (tick 'Add to PATH')." }

  $zip = Join-Path $env:TEMP "kinema-src.zip"
  Write-Host "Downloading source ..." -ForegroundColor Cyan
  Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $Dest -Force
  Remove-Item $zip
  $root = Get-ChildItem $Dest -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  Write-Host "Installed source to $($root.FullName)" -ForegroundColor Green
  & $py.Source (Join-Path $root.FullName "src\server.py")
}
