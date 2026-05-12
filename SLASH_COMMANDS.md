# MLA Agent — Slash Commands

Claude Code ilə işlədikdə istifadəyə hazır 4 slash command. Hamısı `.claude/commands/` qovluğunda yazılıb.

| Command | Funksiya | Skript |
|---|---|---|
| `/MlaOn` | Read-enforcement aktiv et — böyük (≥50 sətir) indekslənmiş faylları blokla, search_code istifadəsini məcburi et | `hooks/toggle_mla.py on` |
| `/MlaOff` | Enforcement deaktiv et — Read sərbəst, search_code məsləhət deyil | `hooks/toggle_mla.py off` |
| `/MlaRefreshBar` | VS Code status bar widget-i indi yenilə — yeni savings yazılıbsa dərhal göstər | `hooks/refresh_bar.py` |
| `/MlaResetBar` | Savings history-i sıfırla (köhnəsi backup-a köçürülür), status bar 0-dan başlasın | `hooks/reset_savings.py` |

## Enforcement davranışı

`hooks/pre_read_check.py` PreToolUse hook-u Read tool-u yoxlayır. Yalnız layihə daxilindəki `.py / .md / .sol / .sql` faylları üçün işləyir.

| Sətir sayı | Davranış |
|---|---|
| ≥ 50 | **Block** (exit 2) — search_code istifadə et |
| 30 – 49 | **Allow + soft tip** (stderr) — search_code daha sərfəli olardı |
| < 30 | **Silent allow** — cüzi faydadır |

State faylı: `.mla_enforcement.flag` (`on` / `off`).

## VS Code Extension

Status bar widget (`erp-intel.mla-agent`) `.mla_savings_history.jsonl` faylını oxuyub son 24 saatın qənaətini göstərir. Yaşıl dolu dairə = enforcement ON, boş dairə = OFF.

File watcher həm `.mla_enforcement.flag`, həm də `.mla_savings_history.jsonl` üçün quraşdırılıb — hər iki fayl dəyişəndə bar dərhal yenilənir.
