# MLA Agent — yeni alpha tester üçün license key yaradır.
#
# İstifadə:
#   .\new_tester_key.ps1 -Email "tester@example.com"
#   .\new_tester_key.ps1 -Email "x@y.com" -DurationDays 90 -Note "Acme Inc dev"
#
# Bu skript license-server/ qovluğundan icra edilməlidir.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Email,

    [string]$Plan = "alpha",

    [int]$DurationDays = 365,

    [string]$Note = ""
)

$ErrorActionPreference = "Stop"

# Skript-i hardan cagirilmasindan asili olmayaraq license-server/ qovlugunda isle
# (wrangler.toml burdadir, lokal node_modules/wrangler v3 Node 20-de isleyir;
# kenar qovluqdan npx avtomatik v4-u fetch edir, Node 22 isteyir)
Set-Location $PSScriptRoot

if ($Email -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
    Write-Host "ERROR: '$Email' duzgun email formatinda deyil." -ForegroundColor Red
    exit 1
}

function New-Id($prefix) {
    return "$prefix$([guid]::NewGuid().ToString('N').Substring(0, 16))"
}

function Invoke-D1 {
    param([string]$Sql)
    $output = npx wrangler d1 execute mla-licenses --remote --command $Sql 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nD1 sorgu xetasi:" -ForegroundColor Red
        $output | Select-Object -Last 10 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        exit 1
    }
}

$licenseKey = New-Id "mla_live_"
$userId     = New-Id "usr_"
$subId      = New-Id "sub_"
$polarFake  = "fake_polar_" + $subId.Substring(4)
$periodSec  = $DurationDays * 86400

Write-Host "`n=== Yeni tester yaradilir ===" -ForegroundColor Cyan
Write-Host "Email:    $Email"
Write-Host "Plan:     $Plan ($DurationDays gun)"
Write-Host ""

Write-Host "1/3  User..." -ForegroundColor Yellow
Invoke-D1 "INSERT INTO users (id, email, created_at) VALUES ('$userId', '$Email', strftime('%s','now'));"

Write-Host "2/3  License..." -ForegroundColor Yellow
Invoke-D1 "INSERT INTO licenses (key, user_id, created_at) VALUES ('$licenseKey', '$userId', strftime('%s','now'));"

Write-Host "3/3  Subscription..." -ForegroundColor Yellow
Invoke-D1 "INSERT INTO subscriptions (id, user_id, polar_subscription_id, status, current_period_end, plan, created_at, updated_at) VALUES ('$subId', '$userId', '$polarFake', 'active', strftime('%s','now')+$periodSec, '$Plan', strftime('%s','now'), strftime('%s','now'));"

# Audit log
$auditLine = "$(Get-Date -Format 'yyyy-MM-dd HH:mm') | $Email | $licenseKey | $Plan | $DurationDays gun | $Note"
Add-Content -Path "$PSScriptRoot\tester_audit.log" -Value $auditLine

$expiryDate = (Get-Date).AddDays($DurationDays).ToString('yyyy-MM-dd')

Write-Host "`n=== HAZIRDIR ===" -ForegroundColor Green
Write-Host ""
Write-Host "TESTER KEY: " -NoNewline
Write-Host $licenseKey -ForegroundColor Green
Write-Host "Etibarli:   $expiryDate-e qeder ($DurationDays gun)"
Write-Host ""
Write-Host "--- Testere gonderilen mesaj ---" -ForegroundColor Cyan
@"

MLA Agent alpha — qurasdirma

Telebler:
  - Windows 10/11
  - Python 3.12 (python --version yoxla)
  - VSCode 1.85+
  - Claude Code (npm install -g @anthropic-ai/claude-code)

Senin license key:
  $licenseKey

Qurasdirma (5 deq):
  1. mla-agent-0.1.0-alpha-win64-py312.zip fayli ac (mes. C:\mla-alpha).
  2. PowerShell ac (Shift + sag klik -> Open PowerShell window here).
  3. Icra et:

     Set-ExecutionPolicy -Scope Process Bypass -Force
     .\install.ps1 -ProjectPath C:\path\to\your\project -LicenseKey $licenseKey -PublicKeyPath .\mla_pubkey.pem

  4. Claude Code-u yeniden baslat.
  5. VSCode status bar-da 'MLA' widget gorunecek.

"@ | Write-Host -ForegroundColor White

try {
    Set-Clipboard -Value $licenseKey -ErrorAction Stop
    Write-Host "Key panoya kopyalandi." -ForegroundColor DarkGreen
} catch { }
