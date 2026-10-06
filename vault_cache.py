"""Cache kredensial vault di memori (TTL + invalidasi eksplisit).

KENAPA ADA
Setiap pemeriksaan kredensial (`check_credential` -> `has_credential` ->
`load_vault_credential`) melakukan urutan mahal: **query Supabase + dekripsi
Fernet + parse JSON**. Pemeriksaan itu terjadi berkali-kali dalam satu alur
(mis. tiap node ber-kredensial pada satu eksekusi workflow, dan tiap
pertanyaan "apakah kredensial X sudah ada?"). Isi vault nyaris tidak berubah
dalam rentang menit, jadi hasilnya layak di-cache.

CATATAN LOKASI (deviasi dari brief)
Brief meminta `tools/vault_cache.py`. Itu **tidak bisa diimpor**: repo ini punya
`tools.py` (modul) DAN direktori `tools/` tanpa `__init__.py`, sehingga
`import tools` menyelesaikan ke `tools.py` dan `tools.vault_cache` tidak akan
pernah ditemukan. Karena itu modul ini diletakkan di root repo, sejajar dengan
`vault_security.py` dan `vault_broker.py`.

KEAMANAN
Nilai yang di-cache adalah kredensial yang SUDAH didekripsi. Batas yang dipilih:
  * TTL pendek (default 300 s) — bukan cache abadi;
  * jumlah entri dibatasi (`VAULT_CACHE_MAX`, default 500) supaya tidak tumbuh
    tanpa batas di proses yang hidup lama;
  * invalidasi eksplisit saat kredensial disimpan/dihapus, jadi user yang baru
    mengisi form TIDAK menunggu TTL;
  * nilai tidak pernah dicetak/di-log.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

TTL_S = float(os.getenv("VAULT_CACHE_TTL", "300"))
MAX_ENTRIES = int(os.getenv("VAULT_CACHE_MAX", "500"))

_lock = threading.Lock()
_store: dict[tuple[str, str], tuple[float, Any]] = {}
_hits = 0
_misses = 0


def _key(email: str, provider: str) -> tuple[str, str]:
    return (str(email or "").strip().lower(), str(provider or "").strip().lower())


def get(email: str, provider: str) -> tuple[bool, Any]:
    """(hit, value). Entri kedaluwarsa dianggap miss dan dibuang."""
    global _hits, _misses
    k = _key(email, provider)
    now = time.time()
    with _lock:
        item = _store.get(k)
        if item and (now - item[0]) < TTL_S:
            _hits += 1
            return True, item[1]
        if item:
            _store.pop(k, None)
        _misses += 1
    return False, None


def put(email: str, provider: str, value: Any) -> None:
    k = _key(email, provider)
    with _lock:
        if len(_store) >= MAX_ENTRIES and k not in _store:
            # buang entri tertua (cukup untuk menjaga batas memori)
            oldest = min(_store.items(), key=lambda kv: kv[1][0])[0]
            _store.pop(oldest, None)
        _store[k] = (time.time(), value)


def invalidate(email: str | None = None, provider: str | None = None) -> int:
    """Buang entri. Tanpa argumen = bersihkan semua. Kembalikan jumlah dibuang."""
    with _lock:
        if email is None and provider is None:
            n = len(_store)
            _store.clear()
            return n
        if email is not None and provider is not None:
            return 0 if _store.pop(_key(email, provider), None) is None else 1
        # salah satu saja: buang semua yang cocok
        target_email = str(email).strip().lower() if email is not None else None
        target_prov = str(provider).strip().lower() if provider is not None else None
        doomed = [k for k in _store
                  if (target_email is None or k[0] == target_email)
                  and (target_prov is None or k[1] == target_prov)]
        for k in doomed:
            _store.pop(k, None)
        return len(doomed)


def stats() -> dict:
    with _lock:
        return {"entries": len(_store), "hits": _hits, "misses": _misses,
                "ttl_s": TTL_S, "max_entries": MAX_ENTRIES}


def reset_stats() -> None:
    global _hits, _misses
    with _lock:
        _hits = 0
        _misses = 0


def load_vault_credential_cached(user_email: str, vault_provider: str) -> dict | None:
    """Versi cache dari `credential_forms.load_vault_credential`.

    Hasil NEGATIF (`None` = belum ada kredensial) ikut di-cache — justru itu
    kasus yang paling sering diulang. Invalidasi saat simpan/hapus menjaga agar
    user tidak terjebak melihat status lama.
    """
    hit, value = get(user_email, vault_provider)
    if hit:
        return value

    import credential_forms as cf
    fresh = cf.load_vault_credential_uncached(user_email, vault_provider)
    # Simpan sebagai dict atau None eksplisit; deepcopy dangkal supaya pemanggil
    # tidak bisa memutasi isi cache secara tidak sengaja.
    put(user_email, vault_provider, dict(fresh) if isinstance(fresh, dict) else None)
    return dict(fresh) if isinstance(fresh, dict) else None
