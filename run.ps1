# PCB Inspector launcher for Windows PowerShell. Same options as run.bat:
#   .\run.ps1 [--test] [--skip-install] [--no-easyocr]
# If scripts are blocked:  powershell -ExecutionPolicy Bypass -File .\run.ps1
& "$PSScriptRoot\run.bat" @args
exit $LASTEXITCODE
