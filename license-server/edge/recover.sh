#!/usr/bin/env bash
# Tokengram — one-shot recovery for "https://tokengram.click doesn't respond".
# Paste this WHOLE block into the EC2 browser shell (AWS Console -> EC2 ->
# instance -> Connect -> EC2 Instance Connect / Session Manager), then press Enter.
# It diagnoses, restarts both services, enables auto-start on reboot, and verifies.
set +e

echo "================ 0. who am I / public IP ================"
# IMDSv2 (token), fall back to IMDSv1. Compare this to the DNS A record for tokengram.click.
TOK=$(curl -sS -m 3 -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null)
PUBIP=$(curl -sS -m 3 -H "X-aws-ec2-metadata-token: $TOK" \
        http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null)
[ -z "$PUBIP" ] && PUBIP=$(curl -sS -m 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null)
echo "This instance public IP : ${PUBIP:-<unknown>}"
echo "DNS expects (A record)  : 54.163.13.24"
echo "  -> If these differ, the EC2 public IP changed on stop/start."
echo "     Fix: attach an Elastic IP, or update the Namecheap A record to ${PUBIP}."

echo "================ 1. current state (before) ================"
systemctl is-active caddy tokengram-admin 2>/dev/null
echo "--- app on :3000 reachable locally? ---"
curl -fsS -m 5 http://localhost:3000/pubkey >/dev/null 2>&1 \
  && echo "  app :3000 = UP" || echo "  app :3000 = DOWN"
echo "--- anything listening on 80/443/3000? ---"
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ':(80|443|3000)\b' || echo "  (nothing on 80/443/3000)"

echo "================ 2. restart both services ================"
sudo systemctl daemon-reload
sudo systemctl enable  tokengram-admin caddy 2>/dev/null
sudo systemctl restart tokengram-admin
sleep 2
sudo systemctl restart caddy
sleep 4

echo "================ 3. state (after) ================"
systemctl is-active caddy tokengram-admin 2>/dev/null
echo "--- caddy recent log (if it failed, the reason is here) ---"
sudo journalctl -u caddy --no-pager -n 15 2>/dev/null | tail -n 15
echo "--- admin app recent log ---"
sudo tail -n 8 /var/log/tokengram-admin.log 2>/dev/null

echo "================ 4. verify ================"
echo "--- local app :3000 ---"
curl -fsS -m 5 http://localhost:3000/pubkey | head -c 60; echo
echo "--- public HTTPS (TLS via Caddy) ---"
curl -sS -m 15 -o /dev/null -w "https://tokengram.click/pubkey -> HTTP %{http_code}\n" https://tokengram.click/pubkey
echo
echo "If step 4 shows the PEM line and HTTP 200, the site is back."
echo "If caddy is still failing, read its journalctl block above (cert/port/permission)."
