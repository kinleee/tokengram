# MLA Agent — Slash Commands

Claude Code ilə işlədikdə istifadəyə hazır slash command-lar. Hamısı `.claude/commands/` qovluğunda yazılıb.

| Command | Funksiya | Skript |
|---|---|---|
| `/MlaOn` | Read-enforcement aktiv et — böyük (≥50 sətir) indekslənmiş faylları blokla, search_code istifadəsini məcburi et | `hooks/toggle_mla.py on` |
| `/MlaOff` | Enforcement deaktiv et — Read sərbəst, search_code məsləhət deyil | `hooks/toggle_mla.py off` |
| `/MlaRefreshBar` | VS Code status bar widget-i indi yenilə — yeni savings yazılıbsa dərhal göstər | `hooks/refresh_bar.py` |
| `/MlaResetBar` | Savings history-i sıfırla (köhnəsi backup-a köçürülür), status bar 0-dan başlasın | `hooks/reset_savings.py` |
| `/MlaArch` | Auto-generated arch doc-u göstər — search_code çağırışlarından tərtib olunmuş fayl xəritəsi + son 20 axtarış mövzusu | `hooks/show_arch.py` |
| `/MlaSync` | Pending `.mla_session_log.jsonl` entry-lərini manual olaraq history-yə köçür (Stop hook interrupt-dən recovery — P16) | `hooks/savings_report.py` |

## Enforcement davranışı

`hooks/pre_read_check.py` PreToolUse hook-u Read tool-u yoxlayır. Yalnız layihə daxilindəki `.py / .md / .sol / .sql` faylları üçün işləyir.

| Sətir sayı | Davranış |
|---|---|
| ≥ 50 | **Block** (exit 2) — search_code istifadə et |
| 30 – 49 | **Allow + soft tip** (stderr) — search_code daha sərfəli olardı |
| < 30 | **Silent allow** — cüzi faydadır |

State faylı: `.mla_enforcement.flag` (`on` / `off`). **OFF olduqda** `arch_doc.py`, `savings_report.py` və `pre_read_check.py` heç biri işləmir — sayğac dayanır, log yığılmır.

## Token Tracking Mənbələri (4 tip)

Stop hook `savings_report.py` hər task sonunda `.mla_session_log.jsonl`-i oxuyub bu dörd tip hadisəni cəm edir:

| Tip | Mənbə | Baseline | Actual |
|---|---|---|---|
| **search_code** | MCP tool çağırışı | qaytarılan faylların tam ölçüsü | qaytarılan chunk-ların token sayı |
| **Grep** (`post_grep_check.py`) | Grep tool indeksli fayl üzərində (≥30 sətir) | `lines * 10` | `baseline * 15%` (heuristik) |
| **Bash-inspect** (`post_bash_check.py`) | İndeksli fayl üzərində inspect komandası (≥50 sətir). Tutulan açar sözlər: `cat / head / tail / wc / less / more / awk / sed / type / findstr / gc / Get-Content / Select-String / sls / git show <ref>:<path>` | `lines * 10` | `baseline * 20%` (heuristik) |
| **Read-block** (`pre_read_check.py`) | Block hadisəsi (≥50 sətir) | `lines * 10` | 0 (oxunmadı) |

Hər birinin **baseline-ı toplu cəm-ə qatılır**, **actual** yalnız faktiki istifadədə (block-larda 0). Status bar widget bu cəmi göstərir, tooltip search/Grep/Read-block breakdown verir (bash-inspect total-a daxildir).

Heuristik token nisbətləri (15%/20%) fərziyyədir — gerçək Grep/Bash output token-ləri bilinmir, ona görə Read alternativi token nisbəti təxmin olunur. Konservativ tərəfə meylli (real qənaət bundan da çox ola bilər).

## Arch Doc Layer (Faza A)

`hooks/arch_doc.py` Stop hook hər task sonunda işə düşür (savings_report-dan əvvəl) və `.mla_session_log.jsonl`-dakı `search_code` çağırışlarını oxuyub `.mla_arch.md` faylını yenilədir. State `.mla_arch_state.json`-da JSON formasında saxlanır.

**Doc strukturu:**
- **Tapılmış Fayllar** — sıralanmış (görsənmə tezliyinə görə): hansı fayl neçə search-də qaytarıldı
- **Son 20 Axtarış Mövzusu** — yeni → köhnə, hər birinin tapıldığı fayllar

Hər yeni session-da Claude (sən) `/MlaArch` çağırışı ilə layihə kontekstini bir baxışda görə bilərsən — söhbətə start etməzdən əvvəl. Repeated query-lər üçün doc-da cavab varsa, search_code skip oluna bilər → əlavə qənaət.

**Lokal-only fayllar (gitignore-da):**
- `.mla_arch.md` (auto-generated, per-machine)
- `.mla_arch_state.json` (internal state)
- `.mla_enforcement.flag` (runtime state)
- `.mla_savings_history.jsonl{,.bak*}` (per-machine analytics)

## VS Code Extension

Status bar widget (`erp-intel.mla-agent`) `.mla_savings_history.jsonl` faylını oxuyub son 24 saatın qənaətini göstərir. Yaşıl dolu dairə = enforcement ON, boş dairə = OFF.

File watcher həm `.mla_enforcement.flag`, həm də `.mla_savings_history.jsonl` üçün quraşdırılıb — hər iki fayl dəyişəndə bar dərhal yenilənir.
