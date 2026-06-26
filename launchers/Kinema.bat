@echo off
REM Kinema launcher for Windows. Double-click to start.
REM Passes any arguments through to server.py.
cd /d "%~dp0\.."

where python >nul 2>nul
if %errorlevel%==0 (
  python server.py %*
  goto :eof
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py %*
  goto :eof
)

echo Python 3 is required but was not found.
echo Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^) and try again.
pause
