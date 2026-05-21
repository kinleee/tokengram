# Tokengram — Internal Alpha Setup (Cython hybrid)

İş yoldaşları üçün quraşdırma təlimatı. Bu, internal test mərhələsidir — production deploy axını DEYİL.

## Sistem tələbləri

- **OS**: Windows 10/11 (alpha-da yalnız Win-də test olunub)
- **Python 3.12** (digər versiyada `.pyd` işləməyəcək — `python --version` ilə yoxla)
- **Claude Code**: quraşdırılmış və işləyir
- **VSCode**: 1.85.0+ (extension üçün)
- **İnternet**: ilk activation + ilk axtarış (model download ~500 MB)

## Quraşdırma addımları

### 1. Distribution paketini aç

Sənə `mla-agent-0.1.0-alpha-win64-py312.zip` (təxminən 0.5 MB) verilir.
İstədiyin yerə aç, məs.:

```powershell
Expand-Archive mla-agent-0.1.0-alpha-win64-py312.zip -DestinationPath $HOME\mla-agent
cd $HOME\mla-agent\mla-agent-0.1.0-alpha
```

### 2. Virtual environment + dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

⚠ `pip install` 2-3 dəq çəkə bilər — chromadb + torch + sentence-transformers heavy.

### 3. .mcp.json-u layihə kök qovluğuna kopyalat

Test edəcəyin repo-nun kök qovluğunda `.mcp.json` lazımdır:

```powershell
Copy-Item .mcp.json $HOME\your-project\.mcp.json
```

`.mcp.json` Claude Code-a deyir ki, `python -m mcp_server` çağırsın. Lakin `mcp_server`
modulu yalnız `$HOME\mla-agent\mla-agent-0.1.0-alpha\` qovluğunda mövcuddur. Bu üçün
`PYTHONPATH` set olmalıdır. Ya `.mcp.json` env-də qoş, ya distrib yerini global pip
package kimi qurğula.

**Asand yol** — `.mcp.json` env əlavə edirik:

```json
{
  "mcpServers": {
    "mla-agent": {
      "command": "${userHome}/mla-agent/mla-agent-0.1.0-alpha/venv/Scripts/python.exe",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": "${userHome}/mla-agent/mla-agent-0.1.0-alpha"
      }
    }
  }
}
```

### 4. VSCode extension install et

```powershell
code --install-extension mla-agent-0.1.0.vsix
```

### 5. Lisenziya açarını daxil et

VSCode-da:
1. `Ctrl+Shift+P` → "Tokengram: Open menu"
2. "🔑 Set license key / Lisenziya açarı yaz" seç
3. Sizə verilən `mla_live_xxxxxxxxxxxxxxxxxxxxxxxx` açarını paste et

Açar `%USERPROFILE%\.mla\license_key.txt` faylına yazılır.

### 6. License server URL + public key

İlk activation üçün license server URL və public key lazımdır. İndilik bunları manual qoş:

```powershell
# License server URL
echo "https://license.mla-agent.workers.dev" > $env:USERPROFILE\.mla\server_url.txt

# Public key (sənə təqdim ediləcək PEM fayl)
Copy-Item mla_pubkey.pem $env:USERPROFILE\.mla\pubkey.pem
```

### 7. Claude Code-u yenidən başlat

MCP server `.mcp.json`-u yalnız Claude Code start-da oxuyur.

## Yoxlama

Claude Code-da:
```
hansı funksiyalar auth ilə bağlıdır?
```

İlk axtarış `~10-30 saniyə` (model load), sonrakılar `~50ms`.

Status bar: `Tokengram: X.Xk saved · YY%` görsənməlidir.

## Daxili struktur (paket içindəkilər)

```
mla-agent-0.1.0-alpha/
├── *.pyd                    # Bizim biznes modulları (compiled, mənbə qapalı)
│   ├── license.cp312-win_amd64.pyd
│   ├── mcp_server.cp312-win_amd64.pyd
│   ├── search_engine.cp312-win_amd64.pyd
│   ├── vector_store.cp312-win_amd64.pyd
│   ├── document_loader.cp312-win_amd64.pyd
│   └── smart_router.cp312-win_amd64.pyd
├── config.py                # Sabitlər (sensitive deyil)
├── main.py                  # CLI entry
├── mla_constants.py         # Sabitlər
├── i18n.py, file_watcher.py, llm_agent.py
├── hooks/                   # Claude Code shell hooks
├── requirements.txt         # Açıq Python paketləri
├── .mcp.json                # Claude Code config
└── README_SETUP.md
```

## Problem həlli

### `python -m mcp_server: No module named mcp_server`
- `PYTHONPATH` doğru qoyulub? `echo $env:PYTHONPATH` yoxla
- Virtual environment aktivləşdirilib? `.\venv\Scripts\Activate.ps1`

### "License xətası" — lisenziya etibarsız
- `$env:USERPROFILE\.mla\license_key.txt` mövcuddur?
- `$env:USERPROFILE\.mla\pubkey.pem` mövcuddur?
- `$env:USERPROFILE\.mla\server_url.txt` mövcuddur?
- Açar `mla_live_` ilə başlayır?
- İnternet bağlantısı?

### Status bar boşdur
- `Ctrl+Shift+P` → "Tokengram: Open menu" → "Refresh status bar"
- 5 dəq gözləyin (ilk activity-dən sonra)

### MCP server start olmur
- Claude Code log: `View → Output → Claude Code`
- `.mcp.json`-da `command` mövcud python.exe-ə yönəlir?
- `venv\Scripts\python.exe -m mcp_server` manual işlə test et

## Feedback

ilkin.ha@erp-intel.com — və ya layihə Slack kanalı.
Lütfən ekran şəkli + adımları əlavə edin.
