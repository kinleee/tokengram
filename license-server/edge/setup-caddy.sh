#!/usr/bin/env bash
# Tokengram license server — put HTTPS (:443) in front of the app on :3000.
# Run ON the EC2 box (54.163.13.24) as root:   sudo bash setup-caddy.sh
#
# OS-agnostic: uses the static Caddy binary + a systemd unit, so it works on
# Amazon Linux 2/2023, Ubuntu, Debian, etc. — no distro package repo needed.
#
# Optional args:  setup-caddy.sh <domain> <app_port>   (defaults below)
set -euo pipefail

DOMAIN="${1:-tokengram.click}"
APP_PORT="${2:-3000}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root:  sudo bash setup-caddy.sh" >&2
  exit 1
fi

# --- 0. sanity: is the app actually listening on the port? ---
if command -v curl >/dev/null 2>&1; then
  if ! curl -fsS "http://localhost:${APP_PORT}/pubkey" >/dev/null 2>&1; then
    echo "WARNING: nothing answered on http://localhost:${APP_PORT}/pubkey — is the license app running?"
    echo "         Caddy will still install, but the proxy has nothing to forward to yet."
  fi
fi

# --- 1. Caddy static binary ---
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64)  CADDY_ARCH=amd64 ;;
  aarch64|arm64) CADDY_ARCH=arm64 ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

if ! command -v caddy >/dev/null 2>&1 && [ ! -x /usr/local/bin/caddy ]; then
  TMP="$(mktemp -d)"
  echo "Downloading Caddy (linux/${CADDY_ARCH})..."
  if ! curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=${CADDY_ARCH}" -o "$TMP/caddy"; then
    echo "Primary download failed — falling back to GitHub release..."
    GH="$(curl -fsSL https://api.github.com/repos/caddyserver/caddy/releases/latest \
          | grep -oE "https://[^\"]*linux_${CADDY_ARCH}\.tar\.gz" | head -n1)"
    curl -fsSL "$GH" -o "$TMP/caddy.tar.gz"
    tar -xzf "$TMP/caddy.tar.gz" -C "$TMP" caddy
  fi
  install -m 0755 "$TMP/caddy" /usr/local/bin/caddy
  rm -rf "$TMP"
fi
/usr/local/bin/caddy version || caddy version

# --- 2. caddy system user + dirs ---
id caddy >/dev/null 2>&1 || useradd --system --home /var/lib/caddy --shell /usr/sbin/nologin caddy
mkdir -p /etc/caddy /var/lib/caddy
chown -R caddy:caddy /var/lib/caddy

# --- 3. Caddyfile ---
cat > /etc/caddy/Caddyfile <<EOF
${DOMAIN} {
	encode gzip
	reverse_proxy localhost:${APP_PORT}
}
EOF

# --- 4. systemd unit ---
cat > /etc/systemd/system/caddy.service <<'EOF'
[Unit]
Description=Caddy (Tokengram license TLS proxy)
After=network.target network-online.target
Requires=network-online.target

[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile --force
Restart=on-failure
TimeoutStopSec=5s
LimitNOFILE=1048576
PrivateTmp=true
ProtectSystem=full
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF

# --- 5. start ---
systemctl daemon-reload
systemctl enable --now caddy
sleep 3
systemctl --no-pager --full status caddy | head -n 18 || true

echo
echo "=============================================================="
echo "Caddy is up. If the DNS A record + ports 80/443 are in place,"
echo "it will fetch a Let's Encrypt cert within ~30s. Verify with:"
echo
echo "  curl -sS https://${DOMAIN}/pubkey"
echo "=============================================================="
