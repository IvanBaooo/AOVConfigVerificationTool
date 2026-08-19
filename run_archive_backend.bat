@echo off
setlocal
cd /d "%~dp0"

python -m archive_backend.server %*
