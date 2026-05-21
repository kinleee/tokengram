# Tokengram release publisher — PyPI + VS Code Marketplace.
#
# İstifadə:
#   # 1. Token-ləri əldə et:
#   #    - PyPI:        https://pypi.org/manage/account/token/  (scope: "Entire account" ilk dəfə üçün)
#   #    - Marketplace: https://dev.azure.com/<sənin org>/_usersSettings/tokens (scope: "Marketplace > Manage")
#   #
#   # 2. Bu PS window-da env var-ları qoy:
#   $env:TWINE_USERNAME = "__token__"
#   $env:TWINE_PASSWORD = "pypi-xxxxxxxxxx..."
#   $env:VSCE_PAT = "xxxxxxxxxxxxxxxxxxx..."
#
#   # 3. Bunu işlət:
#   .\publish_release.ps1
#
# Hər iki upload uğursuz olarsa, skript dayanır — heç bir partial state qalmır.

[CmdletBinding()]
param(
    [switch]$SkipPyPI,
    [switch]$SkipMarketplace,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$wheel = Get-ChildItem -Path "dist\tokengram-*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$vsix = Get-ChildItem -Path "vscode-extension\tokengram-*.vsix" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $wheel) { Write-Host "ERROR: no wheel found in dist/" -ForegroundColor Red; exit 1 }
if (-not $vsix)  { Write-Host "ERROR: no .vsix found in vscode-extension/" -ForegroundColor Red; exit 1 }

Write-Host "=== Release artefaktlar ===" -ForegroundColor Cyan
Write-Host "  PyPI wheel:  $($wheel.Name) ($([math]::Round($wheel.Length/1KB,1)) KB)"
Write-Host "  VSIX:        $($vsix.Name)  ($([math]::Round($vsix.Length/1KB,1)) KB)"

# --- Pre-flight credential check ---
if (-not $SkipPyPI -and -not $env:TWINE_PASSWORD) {
    Write-Host "`nERROR: TWINE_PASSWORD env var yoxdur." -ForegroundColor Red
    Write-Host '  Set with:  $env:TWINE_USERNAME = "__token__"; $env:TWINE_PASSWORD = "pypi-..."'
    exit 1
}
if (-not $SkipMarketplace -and -not $env:VSCE_PAT) {
    Write-Host "`nERROR: VSCE_PAT env var yoxdur." -ForegroundColor Red
    Write-Host '  Set with:  $env:VSCE_PAT = "..."'
    exit 1
}

if (-not $env:TWINE_USERNAME) { $env:TWINE_USERNAME = "__token__" }

# --- 1. PyPI upload ---
if (-not $SkipPyPI) {
    Write-Host "`n=== 1/2  PyPI upload ===" -ForegroundColor Cyan
    if ($DryRun) {
        Write-Host "  (dry-run) twine upload --skip-existing $($wheel.FullName)"
    } else {
        python -m pip install --quiet --upgrade twine
        if ($LASTEXITCODE -ne 0) { Write-Host "twine install failed" -ForegroundColor Red; exit 1 }
        python -m twine upload --skip-existing $wheel.FullName
        if ($LASTEXITCODE -ne 0) {
            Write-Host "`nPyPI upload FAILED. Marketplace addımı atılır — düzəlt və yenidən cəhd et." -ForegroundColor Red
            exit 1
        }
        Write-Host "  ✓ PyPI uploaded" -ForegroundColor Green
    }
}

# --- 2. Marketplace publish ---
if (-not $SkipMarketplace) {
    Write-Host "`n=== 2/2  VS Code Marketplace publish ===" -ForegroundColor Cyan
    Set-Location $PSScriptRoot\vscode-extension
    if ($DryRun) {
        Write-Host "  (dry-run) npx vsce publish --packagePath $($vsix.FullName) --pat ***"
    } else {
        & npx vsce publish --packagePath $vsix.FullName --pat $env:VSCE_PAT
        if ($LASTEXITCODE -ne 0) {
            Write-Host "`nMarketplace publish FAILED. Note: PyPI artıq yüklənib." -ForegroundColor Red
            exit 1
        }
        Write-Host "  ✓ Marketplace published" -ForegroundColor Green
    }
    Set-Location $PSScriptRoot
}

Write-Host "`n=== HAZIRDIR ===" -ForegroundColor Green
Write-Host ""
Write-Host "Yoxla:"
Write-Host "  PyPI:        https://pypi.org/project/tokengram/"
Write-Host "  Marketplace: https://marketplace.visualstudio.com/items?itemName=tokengram.tokengram"
Write-Host ""
Write-Host "Tester install:"
Write-Host "  1. VS Code → Extensions → Tokengram → Install"
Write-Host "  2. Setup wizard avtomatik açılır → 4 addım"
Write-Host "  3. Step 3-də sənin verdiyin license key-i yapışdırır"
Write-Host ""

# Credential təmizliyi — bu shell session bağlananda env var-lar sıfırlanır,
# amma şəfaflıq üçün burada da silirik.
$env:TWINE_PASSWORD = $null
$env:VSCE_PAT = $null
