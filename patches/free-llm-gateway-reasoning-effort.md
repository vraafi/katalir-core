# PATCH free-llm-gateway — dukung `reasoning_effort` (2026-10-03, revisi B)

Revisi A memakai `thinkingBudget: 0` untuk semua model. Revisi B (sekarang)
membedakan **keluarga model**, karena Gemini 3.x memakai kunci yang berbeda.

Terapkan ke container `free-llm-gateway` (host Docker, port 8080):

```bash
docker exec free-llm-gateway python /tmp/pg3.py    # skrip patcher
docker restart free-llm-gateway
```

Idempoten (penanda `# PATCH 2026-10-03b`) dan selalu membuat backup
`/app/providers.py.bak.<timestamp>` sebelum menulis.

## Kenapa revisi B diperlukan — sumber resmi

Dokumentasi resmi Google + PR terverifikasi:

> "Send `reasoning_effort` as `thinkingConfig.thinkingLevel` (lowercase)."
> "Gemini 2.5 still puts its token number inside `thinkingConfig`."
> — [kwaroran/Risuai#1475](https://github.com/kwaroran/Risuai/pull/1475) (merged, Jul 2026)

Dokumentasi Gemini juga menyebut "Control thinking budget" dan level
`minimal | low | medium | high`, dengan catatan `gemini-3.1-pro-preview`
tidak mendukung level `minimal`. Karena itu revisi B memakai `"low"`, yang
valid untuk semua Gemini 3.x.

## Klaim yang DIBATALKAN: "`thinkingBudget: 0` memicu bug 429"

Diuji dengan uji kontrol pada key yang sama, hari yang sama:

| # | body | hasil |
|---|------|-------|
| T1 | `thinkingConfig:{thinkingLevel:"low"}` | `429 "You exceeded your current quota"` |
| T2 | `thinkingConfig:{thinkingBudget:0}` | `429 "You exceeded your current quota"` |
| T3 | **tanpa** `thinkingConfig` (kontrol) | `429 "You exceeded your current quota"` |

Kontrol T3 juga 429, jadi 429 disebabkan **kuota**, bukan oleh
`thinkingBudget: 0`. Thread forum yang dikutip melaporkan pesan berbeda
("prepayment credits are depleted") — itu kondisi billing, bukan kondisi
kuota yang kita lihat. Risiko sebenarnya dari kunci yang salah adalah
`400 INVALID_ARGUMENT`, bukan 429.

## Isi perubahan (`/app/providers.py`)

```diff
     gen: dict[str, Any] = {}
     if payload.get("temperature") is not None:
         gen["temperature"] = payload["temperature"]
     if payload.get("max_tokens"):
         gen["maxOutputTokens"] = payload["max_tokens"]
-    # PATCH 2026-10-03 (lama: selalu thinkingBudget, salah untuk 3.x)
-    eff=(payload.get("reasoning_effort") or "").strip().lower()
-    if eff == "none":
-        gen["thinkingConfig"]={"thinkingBudget":0}
-    elif eff in ("low","medium","high") and isinstance(payload.get("reasoning_tokens"),int):
-        gen["thinkingConfig"]={"thinkingBudget":max(0,int(payload["reasoning_tokens"]))}
+    # PATCH 2026-10-03b: reasoning_effort -> thinkingConfig, PER FAMILY MODEL.
+    mname=(model or "").strip().lower()
+    eff=(payload.get("reasoning_effort") or "").strip().lower()
+    if eff == "none":
+        if mname.startswith("gemini-3"):
+            gen["thinkingConfig"]={"thinkingLevel":"low"}
+        elif mname.startswith("gemini-2.5-pro"):
+            pass
+        elif mname.startswith("gemini-2.5-flash") and "flash-lite" not in mname:
+            gen["thinkingConfig"]={"thinkingBudget":0}
```

### Dua jebakan yang harus dihindari

1. **Urutan `elif`.** Kode `if` naif seperti
   `elif name.startswith("gemini-2.5")` akan **menyerap** `gemini-2.5-pro`
   lebih dulu, sehingga cabang khusus 2.5-Pro menjadi kode mati. Karena itu
   `gemini-2.5-pro` diperiksa lebih dulu, dan `flash-lite` dikecualikan
   eksplisit karena namanya diawali `gemini-2.5-flash`.
2. **Cakupan `gen` dan `model`.** Kode logika harus tetap DI DALAM adapter
   Gemini; `gen` dan `model` hanya ada di scope situ. Memindahkannya ke
   fungsi terpisah `def _apply_reasoning(payload, model_name)` seperti pada
   contoh awal akan menghasilkan `NameError` karena `gen` tidak dikenal.

## Yang SUDAH diverifikasi

- `py_compile /app/providers.py` → `SYNTAX_OK`
- Penanda terpasang: `HAS_3b=True`, `HAS_thinkingLevel=True`
- Backup: `/app/providers.py.bak.20261002185135`
- Setelah restart: container `Up (healthy)`
- Regresi non-Gemini: `qwen/qwen3.8-27b` → `HTTP=200` + content
- **`INVALID_ARGUMENT` / 400 / 422 dalam 30 menit terakhir = 0** — patch ini
  tidak memunculkan satu pun error validasi upstream

## Yang BELUM terverifikasi

- `gemini-2.5-flash` dan `gemini-3.8-flash` + flag → `HTTP 200`.

Alasannya kuota, bukan kode: seluruh permintaan Gemini berakhir
`google_gemini: rate limited` dan antrean retry menahan request beberapa
menit. `gemini-2.5-flash` **tanpa** flag pun sudah membuktikan bisa
menjawab dalam 64 token (`HTTP 200`, `content="Ping!"`,
`finish_reason=stop`), jadi tidak ada alasan teknis untuk mengaktifkan flag
pada model 2.5 — patch itu bersifat opt-in dan belum dipakai siapa pun.

`gateway_roster.py` **sengaja belum** mengirim `reasoning_effort` di probe.
Aktifkan hanya setelah kuota pulih dan `gemini-3.8-flash` terbukti menjawab
`"pong"` dalam 64 token memakai `thinkingLevel: "low"`.