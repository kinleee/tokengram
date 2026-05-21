# Tokengram — Sənin tərəfinin quraşdırma bələdçisi

Bu sənəd **ancaq sənin etməli olduqların** üçündür. Kolleqalara verəcəyin paket onsuz da hazırdır (`dist/mla-agent-0.1.0-alpha-win64-py312.zip` + `install.ps1`).

Lakin paket işləməsi üçün **3 şey lazımdır**:
1. **License server canlıdır** (Cloudflare Worker deploy edilib)
2. **JWT açar cütü** (server private key-i bilir, paket public key-i bilir)
3. **Hər kolleq üçün dev license key** (D1 DB-də qeyd olunub)

Bunların hamısı **bir dəfəlik setup-dır**. Yarım gün iş, sonra unudursan.

---

## 1. JWT açar cütü yarat (~5 dəq)

JWT — biz kolleqaya "etibarlı" deyəndə imzalanan kiçik mətndir. İki açar var:
- **Private key** (gizlidir, Worker-də saxlanır) — yeni JWT imzalayır
- **Public key** (paylaşılır, paketlə gedir) — JWT-nin əsl olduğunu yoxlayır

Yarat:
```powershell
# Private key (Worker üçün — heç vaxt paylaşma)
openssl genpkey -algorithm RSA -out mla_private.pem -pkeyopt rsa_keygen_bits:2048

# Public key (paketə girir)
openssl rsa -in mla_private.pem -pubout -out mla_pubkey.pem
```

İki fayl yarandı:
- `mla_private.pem` — bir azdan Worker secret-ə qoyacağıq
- `mla_pubkey.pem` — kolleqaya verəcəyin paketin içinə əlavə olacaq

> Windows-da openssl yoxsa: Git Bash ilə birlikdə gəlir (`C:\Program Files\Git\usr\bin\openssl.exe`).

---

## 2. Cloudflare Worker deploy et (~30 dəq, ilk dəfə)

### 2.1. Cloudflare hesabı

[cloudflare.com](https://cloudflare.com) — pulsuz hesab. Free tier bizə kifayət edir
(gündə 100k request, biz indi ayda 100 alarıq olsa-olsa).

### 2.2. Lazımi alətlər

```powershell
# Node.js varsa, wrangler (Cloudflare-in CLI alətidir)
cd license-server
npm install
npx wrangler login
# Brauzer açılır, Cloudflare hesabınla login ol.
```

### 2.3. D1 database yarat

D1 — Cloudflare-in SQLite-əsaslı pulsuz DB-si. Lisenziya açarları, subscription
statusları orada saxlanır.

```powershell
npx wrangler d1 create mla-licenses
```

Çıxışda belə bir şey görəcəksən:
```
database_name = "mla-licenses"
database_id = "abc12345-6789-0abc-def0-123456789abc"
```

`database_id`-ni kopyalat və `license-server/wrangler.toml`-da `REPLACE_WITH_REAL_DB_ID`
yazısını bu ID ilə əvəz et.

### 2.4. KV namespace yarat

KV — kiçik key-value cache. Worker bunu istifadə edir.

```powershell
npx wrangler kv:namespace create CACHE
```

Çıxan id-ni `wrangler.toml`-da `REPLACE_WITH_REAL_KV_ID` yerinə yaz.

### 2.5. DB sxemasını tətbiq et

```powershell
npx wrangler d1 execute mla-licenses --remote --file=schema.sql
```

### 2.6. Secret-ləri qoş

Worker-in 2 secret-i var. Birincisi az əvvəl yaratdığımız JWT private key:

```powershell
# Get-Content fayl məzmununu Worker secret-ə göndərir
Get-Content ..\mla_private.pem -Raw | npx wrangler secret put JWT_PRIVATE_KEY
```

İkincisi Polar.sh webhook secret. Polar.sh hələ istəmirsənsə, dummy dəyər qoy
(internal alpha-da webhook çağırılmır):

```powershell
"dummy_for_alpha" | npx wrangler secret put POLAR_WEBHOOK_SECRET
"dummy_for_alpha" | npx wrangler secret put POLAR_API_KEY
```

### 2.7. Deploy

```powershell
npx wrangler deploy
```

URL alacaqsan, məs.: `https://mla-license-server.YOUR-NAME.workers.dev`

Bunu yaddaşda saxla — kolleqaya verəcəyik.

### 2.8. Yoxlama

```powershell
curl https://mla-license-server.YOUR-NAME.workers.dev/
# Cavab: "Tokengram License Server — OK"
```

İşləyirsə Worker canlıdır.

---

## 3. Hər kolleq üçün dev license key (~2 dəq / kolleq)

Polar.sh sandbox quraşdırmaq mürəkkəbdir — alpha üçün **D1-ə əl ilə qoş**.

```powershell
# 1. User və subscription yarat
$email = "colleague1@erp-intel.com"
$licenseKey = "mla_live_dev_" + (-join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }))

Write-Host "Generated key for $email: $licenseKey"

# 2. D1-ə INSERT
$sql = @"
INSERT INTO users (email, created_at) VALUES ('$email', strftime('%s','now'))
ON CONFLICT(email) DO NOTHING;

INSERT INTO licenses (key, user_id, status, revoked, created_at)
SELECT '$licenseKey', id, 'active', 0, strftime('%s','now')
FROM users WHERE email = '$email';

INSERT INTO subscriptions (user_id, status, current_period_end, created_at)
SELECT id, 'active', strftime('%s','now') + 30*86400, strftime('%s','now')
FROM users WHERE email = '$email';
"@

$sql | Out-File -Encoding UTF8 _temp_insert.sql
npx wrangler d1 execute mla-licenses --remote --file=_temp_insert.sql
Remove-Item _temp_insert.sql
```

Bu kolleq üçün:
- `mla_live_dev_xxxxxxxxxxxxxxxxxxxxxxxx` key yaranır
- 30 günlük active subscription verilir
- D1-də user + license + subscription qeydi olur

**Bu key-i kolleqaya ver** (Slack DM və ya şifrəli kanal).

---

## 4. Kolleqaya verəcəyin paket

Bütün bunlar hazır olandan sonra, hər kolleqa belə bir paket göndərirsən:

**1) `dist/mla-agent-0.1.0-alpha-win64-py312.zip`** — distribution arxivi  
**2) `mla_pubkey.pem`** — JWT public key  
**3) Quraşdırma əmri** (təxminən):

```powershell
# Kolleq açır, sonra:
.\install.ps1 `
  -ProjectPath C:\path\to\your\repo `
  -LicenseKey "mla_live_dev_xxxxxxxxxxxxxxxxxxxxxxxx" `
  -LicenseServerUrl "https://mla-license-server.YOUR-NAME.workers.dev" `
  -PublicKeyPath ".\mla_pubkey.pem"
```

Bu installer:
1. Python 3.12 yoxlayır
2. Venv yaradır, deps quraşdırır (2-3 dəq)
3. `~/.mla/license_key.txt`, `~/.mla/server_url.txt`, `~/.mla/pubkey.pem` yazır
4. Layihə qovluğuna `.mcp.json` yerləşdirir
5. VSCode extension-ı install edir

Kolleq Claude Code-u yenidən başladır → işləyir.

---

## 5. Smoke test (real Worker-ə qarşı, MUTLAQ et!)

Kolleqaya verməzdən qabaq özün test et:

```powershell
# Öz maşınında install et
cd C:\temp\mla-test
Expand-Archive mla-agent-0.1.0-alpha-win64-py312.zip -DestinationPath .
cd mla-agent-0.1.0-alpha

# Özünə dev key generate et (yuxarıdakı PowerShell skripti ilə)
# Sonra:
.\install.ps1 `
  -ProjectPath C:\temp\test-project `
  -LicenseKey "mla_live_dev_TESTKEY..." `
  -LicenseServerUrl "https://mla-license-server.YOUR-NAME.workers.dev" `
  -PublicKeyPath C:\path\to\mla_pubkey.pem
```

Yoxlamalı olduqların:
- [ ] `install.ps1` xətasız bitir
- [ ] `~/.mla/license_key.txt` yazılıb, doğru key var
- [ ] Claude Code restart-dan sonra MCP server start olur (Output panel-də `View → Output → Claude Code`)
- [ ] `search_code` MCP tool çağırışı işləyir (məs. Claude Code-da "auth funksiyaları" sual)
- [ ] Status bar `Tokengram: X.Xk saved` göstərir
- [ ] `~/.mla/token.jwt` faylı yarandı (cache, expires_at + fingerprint daxil)

Hamısı uğurlu olarsa **kolleqalara paylaşa bilərsən**.

---

## Tez-tez verilən suallar

**S: Free tier kifayət edir?**  
B: Bəli. Cloudflare Workers free 100k request/gün. 100 paying user × gündə 10 search-də belə 1000 request/gün-ə çatmırsan.

**S: Polar.sh hələ lazımdır?**  
B: Yox, internal alpha üçün. Production-da paylı bir dəfə qoş — webhook ilə avtomatik license issue olur. İndi əl ilə INSERT kifayət.

**S: Kolleq key paylaşsa nə olur?**  
B: Fingerprint mismatch → reject. İlk machine-də activation zamanı fingerprint yazılır, ikinci machine-də `403 fingerprint mismatch` alır.

**S: Internet yoxdursa?**  
B: 7 gün cache offline işləyir. Sonra refresh tələb olunur.

**S: Server down olarsa?**  
B: Cached token expire window-dan kənardırsa işləyir. Yoxsa kolleq tool-larda "license xətası" görür. **Bu hal üçün offline grace period əlavə edirik** (sonrakı versiyada).
