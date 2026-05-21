# Tokengram - Internal Alpha Installer (Windows PowerShell)
#
# İstifadə:
#   .\install.ps1                              # cari qovluqda quraşdır
#   .\install.ps1 -ProjectPath C:\my\repo      # konkret layihə üçün .mcp.json yerləşdir
#   .\install.ps1 -SkipDeps                    # venv + deps quraşdırmasını atla
#
# Bu skript distribution zip-in içində olur. Açılan qovluqda işlədilməlidir.

[CmdletBinding()]
param(
    [string]$ProjectPath = "",
    [switch]$SkipDeps,
    [string]$LicenseKey = "",
    [string]$LicenseServerUrl = "https://mla-license-server-production.n-ilkin-humbatov.workers.dev",
    [string]$PublicKeyPath = ""
)

$ErrorActionPreference = "Stop"
$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step($msg) {
    Write-Host "`n=== $msg ===" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "  [WARN] $msg" -ForegroundColor Yellow
}

# ============================================================
# 1. Python 3.12 yoxlamasi
# ============================================================
Write-Step "Python yoxlamasi"
$pythonVersion = & python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python tapilmadi. Python 3.12 install et: https://www.python.org/downloads/"
    exit 1
}
if ($pythonVersion -notmatch "Python 3\.12") {
    Write-Error "Python 3.12 lazimdir. Cari: $pythonVersion. .pyd modullari yalniz 3.12-de isleyir."
    exit 1
}
Write-OK $pythonVersion

# ============================================================
# 2. Venv yaratmaq + dependencies
# ============================================================
if (-not $SkipDeps) {
    Write-Step "Virtual environment + dependencies"

    $venvPath = Join-Path $script:Root "venv"

    # venv movcuddursa yoxla — pyvenv.cfg-de referans verilen Python movcuddur?
    # Yoxsa kohne user-in pathlari qalib (helpdesk vs naghi.mn problemi).
    $venvBroken = $false
    if (Test-Path $venvPath) {
        $venvPy = Join-Path $venvPath "Scripts\python.exe"
        if (-not (Test-Path $venvPy)) {
            $venvBroken = $true
            Write-Warn "venv var amma python.exe yoxdur — sinik"
        } else {
            $cfg = Join-Path $venvPath "pyvenv.cfg"
            if (Test-Path $cfg) {
                $homeLine = (Get-Content $cfg | Where-Object { $_ -match "^home\s*=" } | Select-Object -First 1)
                if ($homeLine -match "^home\s*=\s*(.+)$") {
                    $cfgHome = $matches[1].Trim()
                    if (-not (Test-Path $cfgHome)) {
                        $venvBroken = $true
                        Write-Warn "venv pyvenv.cfg basqa Python-a baglidir (yoxdur): $cfgHome"
                    }
                }
            }
            # Smoke test — venv python-u isleyirmi?
            if (-not $venvBroken) {
                & $venvPy --version 2>$null | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    $venvBroken = $true
                    Write-Warn "venv python.exe islemir"
                }
            }
        }
    }

    if ($venvBroken) {
        Write-Warn "Sinik venv silinir, yenidan yaradilir"
        Remove-Item $venvPath -Recurse -Force
    }

    if (-not (Test-Path $venvPath)) {
        python -m venv $venvPath
        Write-OK "venv yaradildi"
    } else {
        Write-OK "venv movcuddur (atlanir)"
    }

    $pip = Join-Path $venvPath "Scripts\pip.exe"
    $reqs = Join-Path $script:Root "requirements.txt"

    Write-Host "  pip install -r requirements.txt (2-3 deq cekir)..."
    & $pip install --quiet --upgrade pip
    & $pip install --quiet -r $reqs

    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install ugursuz. requirements.txt-e bax."
        exit 1
    }
    Write-OK "Dependencies qosuldu"
} else {
    Write-Step "Dependencies (SKIP)"
}

# ============================================================
# 3. ~/.mla qovlugu hazirla
# ============================================================
Write-Step ".mla qovlugu (license cache + config)"
$mlaDir = Join-Path $env:USERPROFILE ".mla"
if (-not (Test-Path $mlaDir)) {
    New-Item -ItemType Directory -Path $mlaDir | Out-Null
    Write-OK "$mlaDir yaradildi"
} else {
    Write-OK "$mlaDir movcuddur"
}

# License key
if ($LicenseKey -ne "") {
    $keyFile = Join-Path $mlaDir "license_key.txt"
    Set-Content -Path $keyFile -Value $LicenseKey.Trim() -NoNewline -Encoding UTF8
    Write-OK "license_key.txt yazildi"
}

# Server URL
if ($LicenseServerUrl -ne "") {
    $urlFile = Join-Path $mlaDir "server_url.txt"
    Set-Content -Path $urlFile -Value $LicenseServerUrl.Trim() -NoNewline -Encoding UTF8
    Write-OK "server_url.txt yazildi"
}

# Public key
if ($PublicKeyPath -ne "" -and (Test-Path $PublicKeyPath)) {
    $pubkeyDest = Join-Path $mlaDir "pubkey.pem"
    Copy-Item $PublicKeyPath $pubkeyDest -Force
    Write-OK "pubkey.pem kopyalandi"
}

# ============================================================
# 4. .mcp.json hazirla (layihe qovlugu verilibse)
# ============================================================
if ($ProjectPath -ne "") {
    Write-Step ".mcp.json layihe qovluguna yerlesdir"

    if (-not (Test-Path $ProjectPath)) {
        Write-Warn "$ProjectPath tapilmadi, .mcp.json yerlesdirilmedi"
    } else {
        $venvPython = Join-Path $script:Root "venv\Scripts\python.exe"
        $wrapperPath = Join-Path $script:Root "run_mcp_server.py"
        $mcpConfig = @{
            mcpServers = @{
                "tokengram" = @{
                    command = $venvPython
                    args = @($wrapperPath)
                    env = @{
                        PYTHONUNBUFFERED = "1"
                        PYTHONIOENCODING = "utf-8"
                        PYTHONPATH = $script:Root
                    }
                }
            }
        }

        $mcpJsonPath = Join-Path $ProjectPath ".mcp.json"
        if (Test-Path $mcpJsonPath) {
            $backup = "$mcpJsonPath.bak"
            Copy-Item $mcpJsonPath $backup -Force
            Write-Warn "Movcud .mcp.json $backup-e backup-landi"
        }

        $mcpConfig | ConvertTo-Json -Depth 10 | Set-Content $mcpJsonPath -Encoding UTF8
        Write-OK ".mcp.json yazildi: $mcpJsonPath"

        # ============================================================
        # 4b. hooks/ qovlugunu layihe kokune kopyala
        # ============================================================
        Write-Step "Hooks qovlugu kopyalanir"
        $srcHooks = Join-Path $script:Root "hooks"
        $dstHooks = Join-Path $ProjectPath "hooks"
        if (Test-Path $srcHooks) {
            if (Test-Path $dstHooks) {
                Write-Warn "hooks/ movcuddur, ustune yazilir"
            }
            Copy-Item -Path $srcHooks -Destination $ProjectPath -Recurse -Force
            Write-OK "hooks/ kopyalandi: $dstHooks"
        } else {
            Write-Warn "Paketde hooks/ tapilmadi"
        }

        # ============================================================
        # 4c. Hook destek faylllari (mla_constants, i18n)
        # Compiled .pyd-leri ust-tutuluq, yoxsa .py fallback.
        # ============================================================
        Write-Step "Hook destek faylllari kopyalanir"
        foreach ($base in @("mla_constants", "i18n")) {
            $copied = $false
            foreach ($cand in @("$base.cp312-win_amd64.pyd", "$base.py")) {
                $src = Join-Path $script:Root $cand
                if (Test-Path $src) {
                    Copy-Item $src (Join-Path $ProjectPath $cand) -Force
                    Write-OK "$cand kopyalandi"
                    $copied = $true
                    break
                }
            }
            if (-not $copied) {
                Write-Warn "Paketde $base.* tapilmadi"
            }
        }

        # ============================================================
        # 4d. .claude/settings.json - hook qeydiyyati
        # ============================================================
        Write-Step ".claude/settings.json (Claude Code hook konfigurasiyasi)"
        $claudeDir = Join-Path $ProjectPath ".claude"
        if (-not (Test-Path $claudeDir)) {
            New-Item -ItemType Directory -Path $claudeDir | Out-Null
        }
        $settingsPath = Join-Path $claudeDir "settings.json"
        $hooksDir = Join-Path $ProjectPath "hooks"

        $hookCmd = { param($name) "python `"$(Join-Path $hooksDir $name)`"" }
        $hookSettings = @{
            hooks = @{
                PreToolUse = @(
                    @{
                        matcher = "Read"
                        hooks = @(@{ type = "command"; command = (& $hookCmd "pre_read_check.py") })
                    }
                )
                PostToolUse = @(
                    @{
                        matcher = "Edit|Write|MultiEdit"
                        hooks = @(@{ type = "command"; command = (& $hookCmd "queue_change.py") })
                    },
                    @{
                        matcher = "Grep"
                        hooks = @(@{ type = "command"; command = (& $hookCmd "post_grep_check.py") })
                    },
                    @{
                        matcher = "Bash"
                        hooks = @(@{ type = "command"; command = (& $hookCmd "post_bash_check.py") })
                    }
                )
                Stop = @(
                    @{
                        hooks = @(@{ type = "command"; command = (& $hookCmd "savings_report.py") })
                    }
                )
            }
        }

        if (Test-Path $settingsPath) {
            $backup = "$settingsPath.bak"
            Copy-Item $settingsPath $backup -Force
            Write-Warn "Movcud settings.json $backup-e backup-landi"
        }
        $hookSettings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Encoding UTF8
        Write-OK "settings.json yazildi: 5 hook qeydiyyatdan kecdi"

        # ============================================================
        # 4e. Enforcement flag (default ON)
        # ============================================================
        $flagPath = Join-Path $ProjectPath ".mla_enforcement.flag"
        if (-not (Test-Path $flagPath)) {
            Set-Content -Path $flagPath -Value "on" -NoNewline -Encoding UTF8
            Write-OK ".mla_enforcement.flag = on"
        }
    }
} else {
    Write-Step ".mcp.json + hooks + settings (atlanir - ProjectPath verilmeyib)"
    Write-Host "  Sonra layihe qovluguna qosmaq ucun:"
    Write-Host "  .\install.ps1 -ProjectPath C:\path\to\your\repo -SkipDeps"
}

# ============================================================
# 5. .vsix install (varsa)
# ============================================================
Write-Step "VSCode extension install"
$vsix = Get-ChildItem -Path $script:Root -Filter "*.vsix" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($vsix) {
    # Windows-da `code` PATH-da Code.exe-ye yonele biler (--install-extension dastaklamir).
    # code.cmd lazimdir. Bilinen yerlerden axtar.
    $codeCmd = $null
    $candidates = @(
        (Get-Command code.cmd -ErrorAction SilentlyContinue).Source,
        "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd",
        "$env:ProgramFiles\Microsoft VS Code\bin\code.cmd",
        "${env:ProgramFiles(x86)}\Microsoft VS Code\bin\code.cmd"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { $codeCmd = $c; break }
    }
    if ($codeCmd) {
        & $codeCmd --install-extension $vsix.FullName 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Extension install edildi: $($vsix.Name)"
        } else {
            Write-Warn "Extension install ugursuz (exit $LASTEXITCODE). Manual: $codeCmd --install-extension $($vsix.Name)"
        }
    } else {
        Write-Warn "code.cmd tapilmadi. Manual install: code --install-extension $($vsix.Name)"
    }
} else {
    Write-Warn ".vsix tapilmadi paketde"
}

# ============================================================
# Yekun
# ============================================================
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "QURASDIRMA TAMAMLANDI" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Sonraki addimlar:" -ForegroundColor Cyan
if ($LicenseKey -eq "") {
    Write-Host "  1. VSCode-da Ctrl+Shift+P -> 'Tokengram: Open menu' -> 'Set license key'"
}
if ($ProjectPath -eq "") {
    Write-Host "  2. Layihe qovluguna .mcp.json kopyalat (asagidaki sablon)"
}
Write-Host "  3. Claude Code-u yeniden basla"
Write-Host ""
Write-Host "Problem olarsa: n.ilkin.humbatov@gmail.com" -ForegroundColor Yellow
