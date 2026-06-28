# Kadmu one-line installer for Windows.
#
#   irm https://raw.githubusercontent.com/EasternProdigy/kadmu/main/install.ps1 | iex
#
# Downloads the latest release (ffmpeg bundled — nothing else to install) and
# launches it. Falls back to running from source with Python if no build exists.
#
# Env overrides: KADMU_REPO, KADMU_HOME (install dir).
$ErrorActionPreference = "Stop"

$Repo = if ($env:KADMU_REPO) { $env:KADMU_REPO } else { "EasternProdigy/kadmu" }
$Dest = if ($env:KADMU_HOME) { $env:KADMU_HOME } else { Join-Path $env:LOCALAPPDATA "Kadmu" }

Write-Host "Kadmu installer — finding the latest release of $Repo ..." -ForegroundColor Cyan
try {
  $rel   = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "kadmu-installer" }
  $asset = $rel.assets | Where-Object { $_.name -eq "kadmu-windows.zip" } | Select-Object -First 1
} catch {
  $asset = $null
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

if ($asset) {
  $zip = Join-Path $env:TEMP "kadmu.zip"
  Write-Host "Downloading $($asset.name) ..." -ForegroundColor Cyan
  Invoke-WebRequest $asset.browser_download_url -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $Dest -Force
  Remove-Item $zip
  Write-Host "Installed to $Dest" -ForegroundColor Green
  Write-Host "Starting Kadmu ..." -ForegroundColor Cyan
  & (Join-Path $Dest "kadmu.exe")
}
else {
  Write-Host "No release binary found — falling back to source (needs Python 3)." -ForegroundColor Yellow
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
  if (-not $py) { throw "Python 3 is required. Install from https://www.python.org/downloads/ (tick 'Add to PATH')." }

  $zip = Join-Path $env:TEMP "kadmu-src.zip"
  Write-Host "Downloading source ..." -ForegroundColor Cyan
  Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $Dest -Force
  Remove-Item $zip
  $root = Get-ChildItem $Dest -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  Write-Host "Installed source to $($root.FullName)" -ForegroundColor Green
  & $py.Source (Join-Path $root.FullName "src\server.py")
}
