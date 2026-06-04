# Tokengram Admin — one-time deploy script.
#
# ⚠️ KÖHNƏLİB (2026-06-04): bu skript Cloudflare WORKER-i deploy edir. Cari prod
# server EC2-dədir (admin-server + Caddy → https://tokengram.click). Worker RETIRED;
# yeni açar üçün license-server/new_tester_key.ps1 işlət (EC2 admin API).
#
# Bunu işlət:
#   .\deploy_admin.ps1
#
# Nə edir:
#   1. ADMIN_TOKEN (32-byte random hex) yaradır
#   2. wrangler secret put ADMIN_TOKEN — worker-ə qoyur
#   3. wrangler secret put JWT_PUBLIC_KEY — public PEM-i worker-ə qoyur
#   4. ~/.tokengram/admin_config.json yaradır (admin UI üçün)
#   5. wrangler deploy --env production — yeni endpoint-lər canlı olur
#
# Bu skript license-server/ qovluğundan icra olunmalıdır.

[CmdletBinding()]
param(
    [string]$Environment = "production",
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ------------------------------------------------------------------
# 1. ADMIN_TOKEN generate
# ------------------------------------------------------------------
$tokenBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($tokenBytes)
$adminToken = -join ($tokenBytes | ForEach-Object { $_.ToString("x2") })

Write-Host "`n=== Tokengram Admin Deploy ===" -ForegroundColor Cyan
Write-Host "Generated ADMIN_TOKEN (64 hex chars). Store this carefully — it grants full admin access.`n"

# ------------------------------------------------------------------
# 2. wrangler secret put ADMIN_TOKEN
# ------------------------------------------------------------------
Write-Host "1/4  Setting ADMIN_TOKEN..." -ForegroundColor Yellow
$adminToken | & npx wrangler secret put ADMIN_TOKEN --env $Environment
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED" -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------
# 3. wrangler secret put JWT_PUBLIC_KEY
# ------------------------------------------------------------------
$pubkeyPath = Join-Path $PSScriptRoot "keys\jwt_public.pem"
if (-not (Test-Path $pubkeyPath)) {
    Write-Host "ERROR: $pubkeyPath not found." -ForegroundColor Red
    exit 1
}
$pubkeyContent = Get-Content $pubkeyPath -Raw

Write-Host "2/4  Setting JWT_PUBLIC_KEY..." -ForegroundColor Yellow
$pubkeyContent | & npx wrangler secret put JWT_PUBLIC_KEY --env $Environment
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED" -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------
# 4. Local admin config
# ------------------------------------------------------------------
$tokengramHome = Join-Path $env:USERPROFILE ".tokengram"
New-Item -ItemType Directory -Path $tokengramHome -Force | Out-Null
$configPath = Join-Path $tokengramHome "admin_config.json"

$workerUrl = if ($Environment -eq "production") {
    "https://mla-license-server-production.n-ilkin-humbatov.workers.dev"
} else {
    "https://mla-license-server-staging.n-ilkin-humbatov.workers.dev"
}

$config = @{
    server_url  = $workerUrl
    admin_token = $adminToken
} | ConvertTo-Json

Write-Host "3/4  Writing $configPath..." -ForegroundColor Yellow
Set-Content -Path $configPath -Value $config -Encoding UTF8

# ------------------------------------------------------------------
# 5. Deploy worker
# ------------------------------------------------------------------
if ($SkipDeploy) {
    Write-Host "4/4  Skipping deploy (--SkipDeploy)" -ForegroundColor DarkYellow
} else {
    Write-Host "4/4  Deploying worker..." -ForegroundColor Yellow
    & npx wrangler deploy --env $Environment
    if ($LASTEXITCODE -ne 0) { Write-Host "DEPLOY FAILED" -ForegroundColor Red; exit 1 }
}

Write-Host "`n=== DONE ===" -ForegroundColor Green
Write-Host "`nNext steps:"
Write-Host "  1. Run admin UI:   " -NoNewline; Write-Host "python ..\tools\admin_ui.py" -ForegroundColor Cyan
Write-Host "  2. Open browser:   " -NoNewline; Write-Host "http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "  3. Generate your own key for testing.`n"

Write-Host "Worker URL:  $workerUrl"
Write-Host "Config:      $configPath"
Write-Host ""
