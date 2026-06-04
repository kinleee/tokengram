# Tokengram — yeni tester ucun license key yaradir (CANLI server: tokengram.click).
#
# Istifade:
#   .\new_tester_key.ps1 -Email "tester@example.com"
#   .\new_tester_key.ps1 -Email "x@y.com" -DurationDays 90 -Note "Acme Inc dev"
#
# Admin giris: -AdminEmail/-AdminPassword param, ve ya env
# TOKENGRAM_ADMIN_EMAIL / TOKENGRAM_ADMIN_PASSWORD, yoxsa sorusulacaq.
#
# QEYD: acarlar CANLI serverin DB-sinde yaradilir (https://tokengram.click ->
# admin-server, better-sqlite3). Kohne `wrangler d1` / Cloudflare-worker yolu
# ARTIQ ISLEMIR — o DB-ni production oxumur, orada yaradilan acar validate olmur.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Email,

    [string]$Plan = "alpha",
    [int]$DurationDays = 365,
    [string]$Note = "",

    [string]$Server = "https://tokengram.click",
    [string]$AdminEmail = $env:TOKENGRAM_ADMIN_EMAIL,
    [string]$AdminPassword = $env:TOKENGRAM_ADMIN_PASSWORD
)

$ErrorActionPreference = "Stop"

if ($Email -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
    Write-Host "ERROR: '$Email' duzgun email formatinda deyil." -ForegroundColor Red
    exit 1
}

$Server = $Server.TrimEnd('/')
if (-not $AdminEmail)    { $AdminEmail = Read-Host "Admin email" }
if (-not $AdminPassword) {
    $sec = Read-Host "Admin password" -AsSecureString
    $AdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

Write-Host "`n=== Yeni tester key (server: $Server) ===" -ForegroundColor Cyan
Write-Host "Email: $Email   Plan: $Plan   Muddet: $DurationDays gun`n"

# 1) Admin login -> session cookie
try {
    $null = Invoke-RestMethod -Uri "$Server/admin/login" -Method POST `
        -Body (@{ email = $AdminEmail; password = $AdminPassword } | ConvertTo-Json) `
        -ContentType 'application/json' -SessionVariable sess -TimeoutSec 15
} catch {
    Write-Host "Admin login alinmadi: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "AdminEmail/AdminPassword-u yoxla ($Server/admin/login)." -ForegroundColor Red
    exit 1
}

# 2) Acari yarat
try {
    $r = Invoke-RestMethod -Uri "$Server/admin/keys" -Method POST `
        -Body (@{ email = $Email; plan = $Plan; duration_days = $DurationDays; note = $Note } | ConvertTo-Json) `
        -ContentType 'application/json' -WebSession $sess -TimeoutSec 15
} catch {
    Write-Host "Key yaradilmadi: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$licenseKey = $r.key
if (-not $licenseKey) {
    Write-Host "Server key qaytarmadi: $($r | ConvertTo-Json -Compress)" -ForegroundColor Red
    exit 1
}

# Lokal audit log (rahatliq ucun)
$auditLine = "$(Get-Date -Format 'yyyy-MM-dd HH:mm') | $Email | $licenseKey | $Plan | $DurationDays gun | $Note"
Add-Content -Path "$PSScriptRoot\tester_audit.log" -Value $auditLine

$expiryDate = (Get-Date).AddDays($DurationDays).ToString('yyyy-MM-dd')

Write-Host "`n=== HAZIRDIR ===" -ForegroundColor Green
Write-Host "TESTER KEY: " -NoNewline; Write-Host $licenseKey -ForegroundColor Green
Write-Host "Etibarli:   $expiryDate-e qeder ($DurationDays gun)`n"
Write-Host "--- Testere gonderilen mesaj ---" -ForegroundColor Cyan

@"

Tokengram alpha — qurasdirma

Telebler: Windows 10/11, VSCode 1.85+, Claude Code.
(Python LAZIM DEYIL — installer Python 3.12-ni ozu getirir.)

Senin license key:
  $licenseKey

Qurasdirma:
  1. tokengram VSIX-i ac: Extensions paneli -> "..." menyu -> Install from VSIX...
     (ve ya:  code --install-extension tokengram-<version>.vsix )
  2. VSCode-u reload et. Ilk qurulum ~300 MB endirir (status bar-da faiz gorunur).
  3. Status bar-daki Tokengram widgetine bas -> "Enter license key" -> bu key-i yapisdir.
  4. Claude Code-u yeniden baslat.

"@ | Write-Host -ForegroundColor White

try {
    Set-Clipboard -Value $licenseKey -ErrorAction Stop
    Write-Host "Key panoya kopyalandi." -ForegroundColor DarkGreen
} catch { }
