# Fetch the Linux VSIX (+ linux wheel) from the GitHub Actions "Build Linux
# artifacts" run and drop the VSIX into the CANONICAL, versioned location:
#     vscode-extension/tokengram-linux-x64-<version>.vsix
#
# Niyə bu skript var: `gh run download` artefaktı nested + (köhnə CI-da)
# versiyasız qovluğa açır → VSIX "yoxa çıxmış" kimi görünürdü. Bu, təkrarlanan
# "linux vsix yoxdur" problemi idi. Bu skript onu həmişə düzgün yerə köçürür.
#
# İstifadə:
#   .\fetch_linux_vsix.ps1                 # package.json versiyasını götürür, son uğurlu run
#   .\fetch_linux_vsix.ps1 -Version 0.2.7  # versiyanı açıq ver
#   .\fetch_linux_vsix.ps1 -RunId 28878099659

[CmdletBinding()]
param(
    [string]$Version,
    [string]$RunId
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $Version) {
    $Version = (Get-Content "vscode-extension\package.json" -Raw | ConvertFrom-Json).version
}
Write-Host "Hədəf versiya: $Version" -ForegroundColor Cyan

if (-not $RunId) {
    # build-linux.yml-in son UĞURLU run-u.
    $RunId = (gh run list --workflow build-linux.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId')
    if (-not $RunId) { Write-Host "ERROR: uğurlu build-linux run tapılmadı." -ForegroundColor Red; exit 1 }
}
Write-Host "CI run: $RunId" -ForegroundColor Cyan

$tmp = Join-Path $env:TEMP "tokengram-linux-$Version"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Force $tmp | Out-Null

gh run download $RunId --dir $tmp
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gh run download uğursuz." -ForegroundColor Red; exit 1 }

# Nested strukturdan VSIX-i tap (adı versiyalı OLA da bilər, olmaya da — köhnə run-lar versiyasız idi).
$srcVsix = Get-ChildItem $tmp -Recurse -Filter "*linux-x64*.vsix" | Select-Object -First 1
if (-not $srcVsix) { Write-Host "ERROR: artefaktda linux VSIX tapılmadı." -ForegroundColor Red; exit 1 }

$dstVsix = "vscode-extension\tokengram-linux-x64-$Version.vsix"
Copy-Item $srcVsix.FullName $dstVsix -Force
Write-Host ("  ✓ VSIX → {0} ({1} MB)" -f $dstVsix, [math]::Round((Get-Item $dstVsix).Length/1MB,2)) -ForegroundColor Green

# Linux wheel-i də dist/-ə gətir (PyPI/manylinux işi üçün lazım ola bilər).
$srcWhl = Get-ChildItem $tmp -Recurse -Filter "tokengram-*linux*.whl" | Select-Object -First 1
if ($srcWhl) {
    New-Item -ItemType Directory -Force "dist" | Out-Null
    Copy-Item $srcWhl.FullName "dist\" -Force
    Write-Host ("  ✓ wheel → dist\{0}" -f $srcWhl.Name) -ForegroundColor Green
}

Write-Host "`nHazır. İndi publish:  .\publish_release.ps1" -ForegroundColor Green
