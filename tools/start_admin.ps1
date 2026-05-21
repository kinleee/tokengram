# Tokengram Admin UI launcher.
# Usage:  .\start_admin.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $env:USERPROFILE ".tokengram\venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

& $python "$PSScriptRoot\admin_ui.py" @args
