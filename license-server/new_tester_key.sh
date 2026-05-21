#!/usr/bin/env bash
# Tokengram — yeni alpha tester üçün license key yaradır (Linux/bash variantı).
#
# İstifadə:
#   ./new_tester_key.sh -e tester@example.com
#   ./new_tester_key.sh -e x@y.com -d 90 -n "Acme Inc dev"
#
# Tələblər:
#   - CLOUDFLARE_API_TOKEN env var qoyulmalıdır (D1:Edit + Workers:Edit izni).
#     Misal: export CLOUDFLARE_API_TOKEN=xxxx (və ya .env faylına yaz).
#   - npm install bir dəfə icra olunmalı (lokal wrangler).

set -euo pipefail

EMAIL=""
PLAN="alpha"
DURATION_DAYS=365
NOTE=""

usage() {
    cat <<EOF
İstifadə: $0 -e EMAIL [-p PLAN] [-d DURATION_DAYS] [-n NOTE]
  -e   Tester email (məcburi)
  -p   Plan adı (default: alpha)
  -d   Müddət gün ilə (default: 365)
  -n   Audit log üçün qeyd
EOF
}

while getopts ":e:p:d:n:h" opt; do
    case "$opt" in
        e) EMAIL="$OPTARG" ;;
        p) PLAN="$OPTARG" ;;
        d) DURATION_DAYS="$OPTARG" ;;
        n) NOTE="$OPTARG" ;;
        h) usage; exit 0 ;;
        *) usage; exit 1 ;;
    esac
done

if [[ -z "$EMAIL" ]]; then
    echo "ERROR: -e EMAIL məcburidir." >&2
    usage
    exit 1
fi

if ! [[ "$EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
    echo "ERROR: '$EMAIL' düzgün email formatında deyil." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# .env faylını yüklə (CLOUDFLARE_API_TOKEN üçün)
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    echo "ERROR: CLOUDFLARE_API_TOKEN qoyulmayıb." >&2
    echo "  $SCRIPT_DIR/.env faylına yaz, ya da: export CLOUDFLARE_API_TOKEN=..." >&2
    exit 1
fi

new_id() {
    local prefix="$1"
    local hex
    hex="$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    echo "${prefix}${hex}"
}

run_d1() {
    local sql="$1"
    local out
    if ! out="$(npx --yes wrangler d1 execute mla-licenses --remote --command "$sql" 2>&1)"; then
        echo "" >&2
        echo "D1 sorğu xətası:" >&2
        echo "$out" | tail -n 20 | sed 's/^/  /' >&2
        exit 1
    fi
}

LICENSE_KEY="$(new_id "mla_live_")"
USER_ID="$(new_id "usr_")"
SUB_ID="$(new_id "sub_")"
POLAR_FAKE="fake_polar_${SUB_ID#sub_}"
PERIOD_SEC=$((DURATION_DAYS * 86400))

printf '\n\033[36m=== Yeni tester yaradılır ===\033[0m\n'
echo   "Email:    $EMAIL"
echo   "Plan:     $PLAN ($DURATION_DAYS gün)"
echo

echo -e "\033[33m1/3  User...\033[0m"
run_d1 "INSERT INTO users (id, email, created_at) VALUES ('$USER_ID', '$EMAIL', strftime('%s','now'));"

echo -e "\033[33m2/3  License...\033[0m"
run_d1 "INSERT INTO licenses (key, user_id, created_at) VALUES ('$LICENSE_KEY', '$USER_ID', strftime('%s','now'));"

echo -e "\033[33m3/3  Subscription...\033[0m"
run_d1 "INSERT INTO subscriptions (id, user_id, polar_subscription_id, status, current_period_end, plan, created_at, updated_at) VALUES ('$SUB_ID', '$USER_ID', '$POLAR_FAKE', 'active', strftime('%s','now')+$PERIOD_SEC, '$PLAN', strftime('%s','now'), strftime('%s','now'));"

AUDIT_LINE="$(date '+%Y-%m-%d %H:%M') | $EMAIL | $LICENSE_KEY | $PLAN | $DURATION_DAYS gün | $NOTE"
echo "$AUDIT_LINE" >> "$SCRIPT_DIR/tester_audit.log"

EXPIRY_DATE="$(date -d "+$DURATION_DAYS days" '+%Y-%m-%d')"

printf '\n\033[32m=== HAZIRDIR ===\033[0m\n\n'
printf 'TESTER KEY: \033[32m%s\033[0m\n' "$LICENSE_KEY"
echo  "Etibarlı:   $EXPIRY_DATE-ə qədər ($DURATION_DAYS gün)"
echo
echo -e "\033[36m--- Testerə göndərilən mesaj ---\033[0m"
cat <<EOF

Tokengram alpha — quraşdırma

Tələblər:
  - Windows 10/11
  - Python 3.12 (python --version yoxla)
  - VSCode 1.85+
  - Claude Code (npm install -g @anthropic-ai/claude-code)

Sənin license key:
  $LICENSE_KEY

Quraşdırma (5 dəq):
  1. tokengram-0.1.x-alpha-win64-py312.zip faylı aç (məs. C:\\tokengram).
  2. PowerShell aç.
  3. İcra et:

     Set-ExecutionPolicy -Scope Process Bypass -Force
     .\\install.ps1 -ProjectPath C:\\path\\to\\your\\project -LicenseKey $LICENSE_KEY -PublicKeyPath .\\tokengram_pubkey.pem

  4. Claude Code-u yenidən başlat.
  5. VSCode status bar-da 'TG' widget görünəcək.

EOF
