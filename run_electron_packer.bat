@echo off
cd /d "%~dp0"
if exist "node_modules\electron\dist\electron.exe" (
  "node_modules\electron\dist\electron.exe" .
  exit /b %errorlevel%
)
if not exist "node_modules\.bin\electron.cmd" (
  echo Electron dependencies are missing. Run pnpm install first.
  pause
  exit /b 1
)
call "node_modules\.bin\electron.cmd" .
