@echo off
setlocal
cd /d "%~dp0"
"C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1111-570-0_26.1111.570.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe" "%~dp0wifi_sender.py"
if errorlevel 1 pause
