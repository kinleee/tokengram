# ============================================
# MLA Agent - Windows Setup
# ============================================
# Usage: ./setup.ps1
#        ./setup.ps1 -ProjectDir "C:\path\to\project"  (index another project)
#        ./setup.ps1 -SkipIndex                          (only install deps)

[CmdletBinding()]
param(
    [string]$ProjectDir = ".",
    [switch]$SkipIndex
)

$ErrorActionPreference = "Stop"
$AgentRoot = $PSScriptRoot

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }

# ============================================
# 1. Check Python
# ============================================
Write-Step "Checking Python"
try {
    $pyVersion = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "python command not found" }
    Write-Ok "$pyVersion"

    $verMatch = $pyVersion -match "Python (\d+)\.(\d+)"
    if ($verMatch) {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
            Write-Warn "Python 3.10+ recommended (you have $major.$minor)"
        }
    }
} catch {
    Write-Host "  [ERROR] Python not found. Install from https://python.org (3.10+)" -ForegroundColor Red
    exit 1
}

# ============================================
# 2. .env file
# ============================================
Write-Step "Environment file (.env)"
$envFile = Join-Path $AgentRoot ".env"
$envExample = Join-Path $AgentRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Ok ".env created from .env.example"
        Write-Warn "Edit .env if you need API keys (optional for Claude Code)"
    } else {
        Write-Warn ".env.example not found, skipping"
    }
} else {
    Write-Ok ".env already exists"
}

# ============================================
# 3. Python packages
# ============================================
Write-Step "Installing dependencies (pip install)"
& python -m pip install --quiet --upgrade pip
& python -m pip install -r (Join-Path $AgentRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] pip install failed" -ForegroundColor Red
    exit 1
}
Write-Ok "All packages installed"

# ============================================
# 4. Initial indexing
# ============================================
if (-not $SkipIndex) {
    Write-Step "Initial indexing"
    $resolvedProject = (Resolve-Path $ProjectDir).Path
    Write-Host "  Target: $resolvedProject"
    Write-Warn "First time: embedding model downloads (~130MB), 1-3 min"

    Push-Location $AgentRoot
    try {
        $env:PYTHONIOENCODING = "utf-8"
        & python main.py index $resolvedProject --fresh
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR] Indexing failed" -ForegroundColor Red
            exit 1
        }
        Write-Ok "Indexing complete"
    } finally {
        Pop-Location
    }
} else {
    Write-Step "Indexing skipped (-SkipIndex)"
    Write-Warn "Run later: python main.py index <dir> --fresh"
}

# ============================================
# 5. Done
# ============================================
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Setup COMPLETE" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Fully close VS Code, then reopen (so MCP server picks up config)"
Write-Host "  2. In Claude Code, type /mcp - mla-agent should be 'connected'"
Write-Host "  3. Ask: 'use mla-agent to find where authentication is implemented'"
Write-Host ""
Write-Host "Troubleshooting: see PROBLEMS.md and README.md"
Write-Host ""
