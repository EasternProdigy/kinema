@echo off
REM Windows: double-click to try Kadmu with auto-generated sample videos (read-only).
cd /d "%~dp0\.."
if exist "kadmu.exe" ( "kadmu.exe" --demo %* & goto :eof )
where python >nul 2>nul && ( python src\server.py --demo %* & goto :eof )
where py >nul 2>nul && ( py -3 src\server.py --demo %* & goto :eof )
echo Python 3 is required. Install from https://www.python.org/downloads/ (tick "Add to PATH").
pause
