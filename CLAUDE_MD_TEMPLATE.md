# Tokengram — CLAUDE.md template

İş yoldaşları öz layihələrinin kök qovluğunda **CLAUDE.md** faylına bu məzmunu yapışdırırlar. Bu fayl Claude Code-a deyir ki, hər reload-dan sonra söhbət tarixçəsini sıfırdan yükləməsin — əvəzinə Tokengram-dan axtarış etsin.

---

## CLAUDE.md məzmunu (kopyala layihə kökünə)

```markdown
# Layihə kontekst qaydaları

## Söhbət yaddaşı — Token qənaət

Bu layihədə Tokengram quraşdırılıb. Reload-dan sonra və ya uzun söhbətdə **bütün
keçmiş söhbəti yenidən söhbət tarixçəsinə yükləmə** — bu Claude API kvotasını
yeyər. Əvəzinə:

1. **Sual gələndə** əvvəlcə `search_conversation` MCP alətini çağır:
   ```
   search_conversation(query="user-in son sualı və ya əsas mövzu")
   ```
2. Qaytarılan **3-5 turn snippet**-i context kimi istifadə et.
3. Yalnız yetərsiz olsa Read/search_code ilə əlavə kontekst topla.

**Nə vaxt search_conversation çağırmaq:**
- User "əvvəlki qərarı xatırla", "keçmişdə nə dedik", "X haqqında danışmışdıq" deyir
- Reload-dan sonra ilk turn-də (söhbət tarixçəsi qısaltdırılıb)
- User qeyri-müəyyən referans verir ("o variant", "həmin yanaşma")

**Nə vaxt YOX:**
- Sırf kod axtarışı (`search_code` istifadə)
- Cari turn-də yetərincə kontekst varsa
- Hər tool çağırışı qarşısında refleksiv olaraq

## İndeksin yenilənməsi

Yeni sessiyalar əlavə oldukda manual:
```
reindex_conversations()
```

Bu, `~/.claude/projects/.../*.jsonl` fayllarını oxuyur və ChromaDB
"conversations" collection-ına əlavə edir (mövcud entry-lər upsert
olunur, dublikat yox).
```

---

## Necə işləyir (texniki izah)

1. Claude Code hər söhbəti `~/.claude/projects/<id>/<session>.jsonl`-ə yazır
2. `conversation_indexer.py` bu faylları oxuyur, turn-ləri çıxarır (user prompt + assistant cavab)
3. Sentence-transformers ilə embed olunur, ChromaDB "conversations" collection-da saxlanır
4. `search_conversation(query)` MCP tool semantic axtarış edir, top-K snippet qaytarır
5. Agent reload-dan sonra bu tool ilə **lazımi kontekst-i on-demand** götürür

## Real qənaət (təxmini)

| Reload öncəsi söhbət uzunluğu | Köhnə cost (token) | Tokengram conversation memory ilə |
|---|---|---|
| 1 saatlıq | ~30,000 | ~10,000 |
| 3 saatlıq | ~80,000 | ~25,000 |
| 8 saatlıq | ~150,000 | ~45,000 |

**Tipik qənaət: 60-70% reload-da**, agent disipliplinə görə.
