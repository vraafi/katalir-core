# Trace: kenapa `requires_approval` tidak muncul di respons `/chat`

## Gejala

```
prompt : "laporan berisi [VAULT: supabase]. ringkas."
HTTP   : 200
status : success                      <- seharusnya requires_approval
meta   : bracket_tool_calls = ["VAULT"] <- model menulis polanya, parser jalan
```

## Alur response

`POST /chat` -> `chat()` (api_server.py:1524) -> `_agentic_run_gateway()`
atau `_agentic_run_direct()` -> hasilnya disimpan di `_run`.

Ekstraksi yang dilakukan endpoint (api_server.py:1625-1626):

```python
reply = _run["reply"]
meta  = _run.get("meta") or {}
```

**Hanya dua field itu yang diambil.** `status`, `approval_token`, `tool`,
`args`, `reason` milik `_run` TIDAK pernah dibaca lagi.

## Titik penimpaan

**api_server.py:1735**

```python
return {"status": "success", "reply": reply, "session_id": session_id, "meta": meta}
```

`"status": "success"` di-hardcode. Inilah yang menimpa status apa pun yang
dikembalikan gateway.

## Bukti tambahan

Cabang `requires_approval` yang saya tambahkan di `_agentic_run_gateway`
memangdieksekusi -=buktinya signature `meta` di produksi berubah menjadi
`{bracket_tool_calls, tools_dropped}` (tanpa `textual_tool_calls`), persis
meta yang dikembalikan jalur fix. Jadi upstream benar; yang menimpanya
adalah wrapper di bawahnya.

## Catatan: kenapa `requires_credential` sempat bekerja

`requires_credential` TIDAK lewat baris 1735. Ia naik sebagai
`CredentialMissingError` (api_server.py:1627) dan ditangkap endpoint, yang
lalu memanggil `_cf.build_requires_credential(...)` dan
`return` langsung. Jadi jalur form kredensial tidak pernah melewati
wrapper yang rusak itu - itulah sebabnya hanya status baru yang hilang.

## Rekomendasi fix

Teruskan status khusus dari `_run` ke respons, tanpa mengubah perilaku
lama saat status `success`:

```python
_response = {"status": "success", "reply": reply,
             "session_id": session_id, "meta": meta}
_gw_status = str(_run.get("status") or "success")
if _gw_status != "success":
    _response["status"] = _gw_status
    for _k in ("approval_token", "resume_token", "provider", "display_name",
               "icon", "fields", "tool", "args", "reason", "alignment",
               "expires_in", "message", "connect_url", "oauth_url"):
        if _k in _run:
            _response[_k] = _run[_k]
return _response
```

`session_id` sengaja TIDAK ditimpa dari `_run`: frontend memakainya untuk
melanjutkan percakapan yang sama, dan milik endpoint-lah yang benar.