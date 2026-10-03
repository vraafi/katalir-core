"""sheets_dynamic.py — Tulis ke Google Sheets dengan header DINAMIS.

MASALAH YANG DISELESAIKAN
------------------------
API `values.append` milik Google Sheets MEMBUTUHKAN `matchingColumns`
(daftar nama header) yang tidak kosong. Kalau sheet kosong atau user
mengubah nama kolom, append gagal atau menumpuk data di kolom yang salah.
Pola community yang umum: "biarkan n8n membuat header otomatis saat append
pertama" - tapi begitu juga header lama tidak pernah diperbarui, jadi kolom
baru dari AI diam-diam hilang.

STRATEGI (deterministik, tanpa LLM)
------------------------------------
1. Baca baris 1 sebagai header yang ada.
2. Sheet kosong  -> tulis header dari kunci data.
3. Cocokkan kunci data ke header yang ada memakai normalisasi + kamus
   sinonim (bisa lintas bahasa: `qty` = `jumlah` = `quantity`).
4. Kunci yang tidak punya pasangan -> kolom BARU ditambahkan di kanan.
5. Tappend satu baris dengan urutan header final.

CATATAN KEPUTUSAN (penting)
--------------------------
Task awal meminta `semantic_match` berbasis LLM. Implementasi ini
menyengaja TIDAK memanggil LLM di dalam tool, alasannya:
  * Sheets write harus deterministik dan bisa diuji tanpa jaringan,
  * panggilan LLM menambah 3-10 detik dan bisa gagal (rate limit),
  * keputusan "kolom mana" adalah hal yang bisa diverifikasi user; salah
    kolom berarti data salah diam-diam - lebih buruk daripada kolom baru.
Kamera dicadangkan: `semantic_match_headers(..., llm_mapper=fn)` menerima
callback opsional sehinggazew是一致的 model matching bisa disisipkan nanti
tanpa mengubah struktur kode.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
MAX_HEADER_SCAN = 200
DEFAULT_TIMEOUT_S = 30.0

# Sinon lintas bahasa untuk pencocokan header. Sengaja kecil dan bisa
# diaudit - ini bukan tempat menaruh model bahasa.
_SYNONYMS: dict[str, set[str]] = {
    "qty": {"jumlah", "quantity", "qty", "count", "jml"},
    "quantity": {"jumlah", "qty", "count"},
    "jumlah": {"qty", "quantity", "count", "jml"},
    "name": {"nama", "item", "product", "produk"},
    "nama": {"name", "item", "product", "produk"},
    "item": {"nama", "name", "produk"},
    "price": {"harga", "price", "unit_price"},
    "harga": {"price", "unit_price"},
    "date": {"tanggal", "date", "tgl"},
    "tanggal": {"date", "tgl"},
    "total": {"total", "jumlah_total", "sum"},
    "note": {"catatan", "notes", "note", "keterangan"},
    "catatan": {"note", "notes", "keterangan"},
    "email": {"email", "surel", "surel", "mail"},
    "supplier": {"supplier", "pemasok", "vendor"},
    "pemasok": {"supplier", "vendor"},
}


def normalize_header(value: Any) -> str:
    """Normalisasi nama header/kunci jadi token pembanding.

    Lowercase, buang aksen, ganti non-alnum jadi `_`, rapikan separator.
    """
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def _synonym_family(token: str) -> set[str]:
    """Kumpulan token yang dianggap sama dengan `token`."""
    fam = {token}
    for key, members in _SYNONYMS.items():
        if token == key or token in members:
            fam |= members
            fam.add(key)
    return fam


def _candidate_names(key: str, header: str) -> bool:
    """True bila `key` dan `header` dianggap kolom yang sama."""
    nk, nh = normalize_header(key), normalize_header(header)
    if not nk or not nh:
        return False
    if nk == nh:
        return True
    return bool(_synonym_family(nk) & _synonym_family(nh))


def _related(key: Any, header: Any) -> bool:
    """True bila kunci data dan header dianggap kolom yang sama.

    Dua lapis, dari yang paling yakin:
      1. normalisasi sama persis (`harga` vs `Harga `);
      2. himpunan kata/sinonim beririsan (`name` vs `Nama Barang`: token
         `nama` ada di keluarga sinonim `name`).

    Lapis kedua dipakai hanya bila hasilnya TUNGGAL - lihat
    `semantic_match_headers`.
    """
    nk, nh = normalize_header(key), normalize_header(header)
    if not nk or not nh:
        return False
    if nk == nh:
        return True
    k_tok = {nk} | set(nk.split("_")) - {""}
    h_tok = {nh} | set(nh.split("_")) - {""}
    fam_k = set().union(*[_synonym_family(t) for t in k_tok]) if k_tok else set()
    fam_h = set().union(*[_synonym_family(t) for t in h_tok]) if h_tok else set()
    return bool(fam_k & fam_h)


def semantic_match_headers(
    data: dict,
    headers: list,
    llm_mapper: Callable[[dict, list], dict] | None = None,
) -> tuple[dict, list]:
    """Pasangkan kunci data ke header yang ada.

    Returns `(values_by_header, new_keys)`:
      * `values_by_header` - nilai yang destined untuk header LAMA,
      * `new_keys`         - kunci yang tidak punya header -> kolom baru.

    `llm_mapper(data, headers) -> {data_key: header_or_null}` bersifat opsional
    dan dipakai SETELAHIOCUP matching deterministik gagal, sehingga tidak
    pernah menimpa pasangan yang sudah yakin benar.
    """
    data = dict(data or {})
    old = list(headers or [])

    matched: dict = {}
    new_keys: list[str] = []
    pending: dict = {}

    # Kunci yang cocok PERSIS (setelah normalisasi) selalu menang - tidak perlu
    # tebakan. Kunci lain dicatat dulu untuk dicocokkan oleh token.
    exact_keys: dict = {}
    for key, val in data.items():
        norm = normalize_header(key)
        exact = next((h for h in old if normalize_header(h) == norm), None)
        if exact is not None and exact not in matched:
            matched[exact] = val
            exact_keys[key] = exact
        else:
            pending[key] = val

    # Pencocokan looser (token/sinonim) HANYA untuk kunci yang belum punya
    # pasangan, dan HANYA bila hasilnya TUNGGAL - kalau dua header sama-sama
    # cocok kuncinya ambigu, lebih aman membuat kolom baru daripada menulis ke
    # kolom yang salah (kolom baru itu kelihatan; kolom salah tidak).
    if pending:
        for key, val in list(pending.items()):
            cands = [h for h in old if h not in matched and _related(key, h)]
            if len(cands) == 1:
                matched[cands[0]] = val
                del pending[key]

    # Sisa yang tidak punya pasangan -> kolom baru.
    new_keys.extend(pending.keys())

    if pending and llm_mapper is not None:
        try:
            mapped = llm_mapper(pending, old) or {}
        except Exception:  # noqa: BLE001 - LLM adalah bonus, bukan syarat
            mapped = {}
        for key, val in list(pending.items()):
            target = mapped.get(key)
            if target and target in old and target not in matched:
                matched[target] = val
                pending.pop(key, None)

    new_keys = [k for k in new_keys if k in pending] + [
        k for k in pending if k not in new_keys]
    return matched, list(pending.keys())


def _read_headers(service_client: Any, spreadsheet_id: str, sheet_name: str) -> list:
    """Baca baris 1 sebagai header. Sheet kosong -> `[]`."""
    rng = f"'{sheet_name}'!A1:{chr(64 + min(MAX_HEADER_SCAN, 26))}1"
    resp = service_client.get(
        f"{SHEETS_API}/{spreadsheet_id}/values/{_encode(rng)}"
    )
    if resp.status_code == 404:
        return []
    if resp.status_code >= 400:
        raise RuntimeError(f"Gagal membaca header sheet: HTTP {resp.status_code}")
    values = resp.json().get("values") or []
    if not values:
        return []
    return [str(v) for v in (values[0] or []) if str(v).strip() != ""]


def _encode(path: str) -> str:
    """URL-encode satu nilai range Sheets."""
    from urllib.parse import quote

    return quote(path, safe="!:'$-_./")


def write_sheets_dynamic(
    spreadsheet_id: str,
    sheet_name: str,
    data: dict,
    email: str,
    *,
    llm_mapper: Callable[[dict, list], dict] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client: Any = None,
) -> dict:
    """Tulis satu baris dengan header yang menyesuaikan data.

    Tidak butuh `matchingColumns`: header dibuat/diperbarui lebih dulu lalu
    baris di-append pada kolom yang sudah pasti urutannya.

    Mengembalikan dict berisi header final dan baris yang ditulis.
    Melempar `CredentialMissingError` bila user belum Connect Google.
    """
    import httpx

    import oauth_google
    import database as db
    from tools import CredentialMissingError

    if not spreadsheet_id:
        raise ValueError("spreadsheet_id wajib diisi.")
    if not isinstance(data, dict) or not data:
        raise ValueError("`data` harus dict tidak kosong.")

    try:
        token = oauth_google.access_token(email)
    except RuntimeError as exc:
        raise CredentialMissingError("google_sheets") from exc

    # `client` bisa disuntikkan di test; produksi membuat client sendiri.
    client = client if client is not None else httpx.Client(timeout=timeout_s)
    headers_existing = _read_headers(client, spreadsheet_id, sheet_name)

    matched, new_keys = semantic_match_headers(data, headers_existing, llm_mapper)
    final_headers = list(headers_existing)
    for k in new_keys:
        if k not in final_headers:
            final_headers.append(str(k))

    # Header harus ditulis DULUAN, karena append butuh header sudah ada.
    # BUG FIX 2026-10-03: sebelumnya blok ini hanya jalan saat sheet KOSONG.
    # Kalau sheet sudah punya header dan data menambah kunci baru, header BARU
    # tidak pernah ditulis - hasilnya nilai append mendarat di kolom tanpa
    # judul (data benar tapi tak terlihat). Sheet kosong dan penambahan kolom
    # harus lewat jalur yang sama.
    if final_headers and final_headers != list(headers_existing):
        _write_row(client, spreadsheet_id, sheet_name, "A1", [final_headers], token)

    values_by_header = dict(matched)
    for k in new_keys:
        values_by_header.setdefault(k, data.get(k))
    row = [values_by_header.get(h, "") for h in final_headers]

    appended = _append_row(client, spreadsheet_id, sheet_name, row, token)

    return {
        "status": "ok",
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "headers": final_headers,
        "row_written": row,
        "new_columns_added": [str(k) for k in new_keys],
        "matched_existing": [h for h in matched],
        "appended_range": appended,
        "email": email,
    }


def _write_row(client: Any, sid: str, sheet: str, a1: str, values: list, token: str) -> None:
    resp = client.put(
        f"{SHEETS_API}/{sid}/values/{_encode(f'{sheet}!{a1}')}",
        headers={"Authorization": f"Bearer {token}"},
        params={"valueInputOption": "USER_ENTERED"},
        json={"range": f"'{sheet}'!{a1}", "majorDimension": "ROWS", "values": values},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Gagal menulis header: HTTP {resp.status_code} {resp.text[:160]}")


def _append_row(client: Any, sid: str, sheet: str, row: list, token: str) -> str:
    rng = f"'{sheet}'!A1"
    resp = client.post(
        f"{SHEETS_API}/{sid}/values/{_encode(rng)}:append",
        headers={"Authorization": f"Bearer {token}"},
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json={"majorDimension": "ROWS", "values": [row]},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Gagal append baris: HTTP {resp.status_code} {resp.text[:160]}")
    return str((resp.json() or {}).get("updates", {}).get("updatedRange", ""))