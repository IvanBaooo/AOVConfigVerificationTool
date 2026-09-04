@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$healthy=$false; try { $response=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8780/health' -TimeoutSec 2; $healthy=([int]$response.StatusCode -eq 200) } catch {}; if (-not $healthy) { Start-Process -FilePath 'python' -ArgumentList @('-m','archive_backend.server','--host','127.0.0.1','--port','8780','--no-auth') -WorkingDirectory '%~dp0' -WindowStyle Hidden -RedirectStandardOutput '%~dp0backend.stdout.log' -RedirectStandardError '%~dp0backend.stderr.log'; Start-Sleep -Milliseconds 800 }"
call run_electron_packer.bat
