@echo off
REM Kadmu launcher for Windows. Double-click to start.
REM Works as a source checkout (src\server.py) or a release bundle (kadmu.exe).
REM Passes any arguments through, e.g.:  Kadmu.bat --app
cd /d "%~dp0\.."

if exist "kadmu.exe" ( "kadmu.exe" %* & goto :eof )

if exist "src\server.py" (
  where python >nul 2>nul && ( python src\server.py %* & goto :eof )
  where py >nul 2>nul && ( py -3 src\server.py %* & goto :eof )
  echo Python 3 is required but was not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^) and try again.
  pause
  goto :eof
)

echo Could not find Kadmu ^(neither src\server.py nor kadmu.exe^).
pause
