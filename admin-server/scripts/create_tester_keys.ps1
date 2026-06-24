# Tester miqrasiyası (S2 — launch plan, A1 deploy-dan ƏVVƏL işlət).
#
# Trial enforcement açılmazdan əvvəl bütün aktiv testerlərə uzunmüddətli alpha
# açarı verilir ki, heç kim trial_expired divara dəyməsin. Açarlar serverdə
# /admin/keys endpoint-i ilə yaradılır, nəticə CSV-yə yazılır — hər testerə
# öz açarını email ilə göndər.
#
# İstifadə:
#   $env:TOKENGRAM_ADMIN_TOKEN = "<.env-dəki ADMIN_TOKEN>"
#   .\create_tester_keys.ps1 -Emails tester1@mail.com,tester2@mail.com
#   .\create_tester_keys.ps1 -Emails @(Get-Content testers.txt) -Days 365
#
# Parametrlər:
#   -Emails     bir və ya bir neçə tester email-i (məcburi)
#   -Days       açarın müddəti günlə (default 365)
#   -Plan       abunə planı etiketi (default 'alpha')
#   -ServerUrl  license server (default https://tokengram.click)
#   -OutCsv     nəticə faylı (default tester_keys_<tarix>.csv)

param(
    [Parameter(Mandatory = $true)]
    [string[]]$Emails,
    [int]$Days = 365,
    [string]$Plan = 'alpha',
    [string]$ServerUrl = 'https://tokengram.click',
    [string]$OutCsv = "tester_keys_$(Get-Date -Format 'yyyyMMdd_HHmm').csv"
)

Set-Location $PSScriptRoot

$adminToken = $env:TOKENGRAM_ADMIN_TOKEN
if (-not $adminToken) {
    Write-Error "TOKENGRAM_ADMIN_TOKEN env var boşdur. EC2-dəki admin-server/.env faylındakı ADMIN_TOKEN dəyərini qoy."
    exit 1
}

$ServerUrl = $ServerUrl.TrimEnd('/')
$results = @()
$failures = 0

foreach ($email in $Emails) {
    $email = $email.Trim().ToLower()
    if (-not $email) { continue }
    try {
        $res = Invoke-RestMethod -Method Post -Uri "$ServerUrl/admin/keys" `
            -Headers @{ 'x-admin-token' = $adminToken } `
            -ContentType 'application/json' `
            -Body (@{ email = $email; plan = $Plan; duration_days = $Days } | ConvertTo-Json) `
            -TimeoutSec 30
        $expires = [DateTimeOffset]::FromUnixTimeSeconds($res.expires_at).ToString('yyyy-MM-dd')
        $results += [pscustomobject]@{
            email       = $email
            license_key = $res.license_key
            plan        = $Plan
            expires     = $expires
        }
        Write-Host "  OK   $email → $($res.license_key) (bitmə: $expires)"
    } catch {
        $failures++
        Write-Host "  FAIL $email → $($_.Exception.Message)" -ForegroundColor Red
    }
}

if ($results.Count -gt 0) {
    $results | Export-Csv -Path $OutCsv -NoTypeInformation -Encoding UTF8
    Write-Host "`n$($results.Count) açar yaradıldı → $OutCsv"
    Write-Host "Növbəti addım: hər testerə öz açarını göndər; extension-da 'Set license key' ilə daxil edirlər."
}
if ($failures -gt 0) {
    Write-Host "$failures email uğursuz oldu — yuxarıdakı sətirlərə bax." -ForegroundColor Yellow
    exit 1
}
