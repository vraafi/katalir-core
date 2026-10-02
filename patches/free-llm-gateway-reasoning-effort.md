# PATCH free-llm-gateway — dukung `reasoning_effort` (2026-10-03)

Terapkan ke container `free-llm-gateway` (host Docker, port 8080):

```bash
docker exec free-llm-gateway python /tmp/pg.py     # skrip patcher di bawah
docker restart free-llm-gateway
```

Idempoten (bertanda `# PATCH 2026-10-03` sebagai penanda) dan selalu
membuat backup `/app/<file>.bak.<timestamp>` sebelum menulis.

## Mengapa patch ini perlu

Menambahkan `reasoning_effort: none` ke `models.yaml` **tidak mengubah apa pun**. Dibuktikan:

```
$ grep -c 'reasoning_effort' /opt/free-llm-gateway/models.yaml
0
$ docker exec free-llm-gateway grep -rn reasoning_effort / --include=*.py
(tidak ada hasil)
```

Adapter Gemini hanya pernah membangun dua kunci `generationConfig`:

```python
gen: dict[str, Any] = {}
if payload.get("temperature") is not None:
    gen["temperature"] = payload["temperature"]
if payload.get("max_tokens"):
    gen["maxOutputTokens"] = payload["max_tokens"]
```

Tidak ada `thinkingConfig`, tidak ada passthrough parameter tak dikenal.
Gayanya juga `ChatCompletionRequest` (Pydantic) tidak punya field
`reasoning_effort`, sehingga field itu dibuang sebelum mencapai adapter.

Kalau `reasoning_effort` ditambahkan diam-diam ke `models.yaml`, hasilnya
adalah **konfigurasi mati**: terlihat seperti sudah diperbaiki, padahal tidak
berpengaruh apa pun.

## Isi perubahan

### `/app/providers.py` — di dalam adapter Gemini

```diff
     gen: dict[str, Any] = {}
     if payload.get("temperature") is not None:
         gen["temperature"] = payload["temperature"]
     if payload.get("max_tokens"):
         gen["maxOutputTokens"] = payload["max_tokens"]
+    # PATCH 2026-10-03 (reasoning_effort -> thinkingConfig)
+    eff=(payload.get("reasoning_effort") or "").strip().lower()
+    if eff == "none":
+        gen["thinkingConfig"]={"thinkingBudget":0}
+    elif eff in ("low","medium","high") and isinstance(payload.get("reasoning_tokens"),int):
+        gen["thinkingConfig"]={"thinkingBudget":max(0,int(payload["reasoning_tokens"]))}
     if gen:
         gemini_body["generationConfig"] = gen
```

### `/app/main.py` — skema request

```diff
     max_tokens: int | None = Field(default=None, gt=0)
+    # PATCH 2026-10-03 (reasoning_effort)
+    reasoning_effort: str | None = None
+    reasoning_tokens: int | None = Field(default=None, ge=0)
```

## Sifat perubahan

**Opt-in.** Tanpa klien yang mengirim `reasoning_effort`, `eff` kosong dan
tidak ada baris baru yang dieksekusi — perilaku gateway identik dengan
sebelumnya untuk semua model dan semua klien.

## Yang SUDAH diverifikasi

- `py_compile` kedua berkas: `SYNTAX_OK`
- Field benar-benar ada di sumber: `VERIFY_providers=True`, `VERIFY_main=True`
- Setelah restart: container `Up (healthy)`
- Model non-Gemini masih jalan: `qwen/qwen3.8-27b` → `HTTP=200` + content

## Yang BELUM terverifikasi (sengaja, tidak diklaim)

- Efek `thinkingBudget: 0` pada model berpikir, mis. `gemini-3.8-flash`
  dengan `max_tokens: 64`.

Alasannya kuota, bukan kode: kuota free-tier Google sudah habis
(`429 ... generate_content_free_tier_requests, limit: 20`). Percobaan
`gemini-3.8-flash` + flag berakhir `HTTP 000` karena antrean retry
rate-limit (menunggu 60 detik per percobaan), bukan karena penolakan flag.

Karena itu `gateway_roster.py` **sengaja belum** ikut mengirim
`reasoning_effort: "none"` di probe. Mengaktifkannya tanpa bukti bisa
menghilangkan model yang tadinya sehat bila suatu model menolak
`thinkingConfig` dengan `INVALID_ARGUMENT`. Nyalakan setelah kuota pulih
dan `gemini-3.8-flash` terbukti menjawab dalam 64 token.