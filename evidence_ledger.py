"""evidence_ledger.py — ledger bukti ber-rantai hash (tamper-evident).

MOTIVASI (rujuk n8n-autopilot Phase 4 "verification" + praktik audit 2026)
------------------------------------------------------------------------
Agent yang mengklaim "sudah diuji" tanpa jejak yang bisa diaudit tidak bisa
dipercaya. Ledger ini menyimpan setiap bukti (hasil test, keputusan, eksekusi)
dalam rantai hash: setiap entri mengikat entri sebelumnya, sehingga mengubah
satu entri lama memutus SELURUH rantai setelahnya — dan itu terdeteksi.

STRUKTUR ENTRI
--------------
    seq          urutan 0..n (genesis = 0)
    id           uuid
    ts           epoch detik
    content_hash sha256(canonical_json(content))
    prev_hash    hash entri sebelumnya ("" untuk genesis)
    hash         sha256(prev_hash + ":" + content_hash + ":" + seq)
    sig          HMAC-SHA256(key, hash)  (atau Ed25519 bila key Ed25519)

Jaminan:
  * **Integritas** — `verify_chain` menghitung ulang tiap hash & tautan.
  * **Deteksi tamper** — ubah `content`/`hash`/`prev_hash` mana pun -> chain
    pecah pada entri itu (dan semua entri setelahnya tidak lagi terverifikasi).
  * **Autentikasi** — `sig` membuktikan entri dibuat oleh pemegang kunci.
  * **Serialisasi aman** — `canonical_json` (kunci terurut) membuat hash stabil
    lintas proses/mesin.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Iterable

GENESIS_HASH = ""
DEFAULT_KEY_ENV = "EVIDENCE_LEDGER_KEY"
#: "postgres" (default bila kredensial ada) | "memory"
STORE_ENV = "KATALIR_EVIDENCE_STORE"


class LedgerError(Exception):
    """Operasi ledger tidak valid."""


class ChainBrokenError(LedgerError):
    """Rantai hash terputus (tamper / entri hilang)."""

    def __init__(self, seq: int, reason: str):
        self.seq = seq
        self.reason = reason
        super().__init__(f"rantai pecah pada seq={seq}: {reason}")


# --------------------------------------------------------------------------
# Helper
# --------------------------------------------------------------------------
def canonical_json(content: Any) -> str:
    """JSON kanonik (kunci terurut, tanpa spasi) supaya hash deterministik."""
    return json.dumps(content, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def content_hash(content: Any) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def chain_hash(prev_hash: str, chash: str, seq: int) -> str:
    material = f"{prev_hash}:{chash}:{seq}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _resolve_key(key: bytes | str | None) -> bytes:
    if key is None:
        key = os.getenv(DEFAULT_KEY_ENV) or ""
    if isinstance(key, str):
        key = key.encode("utf-8")
    if not key:
        raise LedgerError(
            f"kunci ledger kosong (set {DEFAULT_KEY_ENV} atau lewatkan key=)"
        )
    return key


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
class MemoryEvidenceStore:
    """Store in-memory (untuk test / proses tunggal)."""

    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._lock = threading.Lock()

    def load(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._rows]

    def append(self, entry: dict) -> None:
        with self._lock:
            self._rows.append(dict(entry))


class PostgresEvidenceStore:
    """Store Supabase/Postgres untuk tabel ``evidence_ledger``."""

    DDL = """
    CREATE TABLE IF NOT EXISTS evidence_ledger (
      seq          bigint PRIMARY KEY,
      id           uuid NOT NULL,
      ts           double precision NOT NULL,
      content      jsonb NOT NULL,
      content_hash text NOT NULL,
      prev_hash    text NOT NULL,
      hash         text NOT NULL,
      sig          text NOT NULL,
      created_at   timestamptz DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_evidence_ledger_hash ON evidence_ledger (hash);
    """

    def __init__(self, dsn_factory: Callable[[], Any] | None = None):
        self._dsn_factory = dsn_factory

    def _connect(self):
        import psycopg2
        if self._dsn_factory is not None:
            return psycopg2.connect(**self._dsn_factory())
        # Pooler Supabase. CATATAN: sebelumnya modul ini mengimpor
        # `connector_verification_store._dsn` yang **tidak pernah ada**
        # (nama fungsinya `connect`) sehingga store Postgres selalu
        # ImportError dan ledger jatuh ke memori tanpa disadari.
        from connector_verification_store import connect as _supabase_connect
        return _supabase_connect()

    def ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self.DDL)

    def load(self) -> list[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT seq,id,ts,content,content_hash,prev_hash,hash,sig "
                "FROM evidence_ledger ORDER BY seq ASC"
            )
            cols = ("seq", "id", "ts", "content", "content_hash",
                    "prev_hash", "hash", "sig")
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["seq"] = int(d["seq"])
                d["id"] = str(d["id"])
                d["ts"] = float(d["ts"])
                out.append(d)
            return out

    def append(self, entry: dict) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO evidence_ledger "
                "(seq,id,ts,content,content_hash,prev_hash,hash,sig) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (seq) DO NOTHING",
                (entry["seq"], entry["id"], entry["ts"],
                 json.dumps(entry["content"], default=str),
                 entry["content_hash"], entry["prev_hash"],
                 entry["hash"], entry["sig"]),
            )


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
class EvidenceLedger:
    """Rantai bukti ber-hash. Thread-safe untuk append."""

    def __init__(self, *, key: bytes | str | None = None,
                 store: Any | None = None, clock: Callable[[], float] | None = None):
        self._key = _resolve_key(key)
        self._store = store if store is not None else MemoryEvidenceStore()
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._entries: list[dict] = list(self._store.load())
        self._verify_or_raise(self._entries)

    # -- internal --------------------------------------------------------
    @staticmethod
    def _verify_or_raise(entries: list[dict]) -> None:
        prev = GENESIS_HASH
        for i, e in enumerate(entries):
            if e.get("seq") != i:
                raise ChainBrokenError(i, f"seq tidak berurutan (dapat {e.get('seq')})")
            if e.get("prev_hash") != prev:
                raise ChainBrokenError(i, "prev_hash tidak menautkan entri sebelumnya")
            if e.get("content_hash") != content_hash(e.get("content")):
                raise ChainBrokenError(i, "content_hash tidak cocok dengan content")
            if e.get("hash") != chain_hash(prev, e.get("content_hash"), i):
                raise ChainBrokenError(i, "hash tidak cocok dengan rantai")
            prev = e["hash"]

    def _sign(self, digest: str) -> str:
        return hmac.new(self._key, digest.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_signature(self, entry: dict) -> bool:
        expect = self._sign(entry.get("hash", ""))
        return hmac.compare_digest(expect, str(entry.get("sig", "")))

    # -- public ----------------------------------------------------------
    def append(self, content: Any) -> dict:
        """Tambah bukti baru. Kembalikan entri lengkap."""
        with self._lock:
            seq = len(self._entries)
            prev = self._entries[-1]["hash"] if self._entries else GENESIS_HASH
            chash = content_hash(content)
            h = chain_hash(prev, chash, seq)
            entry = {
                "seq": seq,
                "id": str(uuid.uuid4()),
                "ts": float(self._clock()),
                "content": content,
                "content_hash": chash,
                "prev_hash": prev,
                "hash": h,
                "sig": self._sign(h),
            }
            self._entries.append(entry)
            self._store.append(entry)
            return dict(entry)

    def get(self, seq: int) -> dict | None:
        if 0 <= seq < len(self._entries):
            return dict(self._entries[seq])
        return None

    def find(self, entry_id: str) -> dict | None:
        for e in self._entries:
            if e["id"] == entry_id:
                return dict(e)
        return None

    def verify_entry(self, entry: dict) -> bool:
        """Verifikasi satu entri: content_hash, hash, dan signature."""
        if entry.get("content_hash") != content_hash(entry.get("content")):
            return False
        seq = int(entry.get("seq", -1))
        if entry.get("hash") != chain_hash(entry.get("prev_hash", ""),
                                           entry.get("content_hash"), seq):
            return False
        return self.verify_signature(entry)

    def verify_chain(self, entries: Iterable[dict] | None = None) -> dict:
        """Verifikasi seluruh rantai. Kembalikan {ok, length, broken_at, reason}."""
        rows = list(self._entries if entries is None else entries)
        prev = GENESIS_HASH
        for i, e in enumerate(rows):
            if e.get("seq") != i:
                return {"ok": False, "length": len(rows), "broken_at": i,
                        "reason": f"seq tidak berurutan: {e.get('seq')}"}
            if e.get("prev_hash") != prev:
                return {"ok": False, "length": len(rows), "broken_at": i,
                        "reason": "prev_hash tidak cocok"}
            if e.get("content_hash") != content_hash(e.get("content")):
                return {"ok": False, "length": len(rows), "broken_at": i,
                        "reason": "content_hash tidak cocok (content diubah)"}
            if e.get("hash") != chain_hash(prev, e.get("content_hash"), i):
                return {"ok": False, "length": len(rows), "broken_at": i,
                        "reason": "hash tidak cocok (entri diubah)"}
            if not self.verify_signature(e):
                return {"ok": False, "length": len(rows), "broken_at": i,
                        "reason": "signature tidak valid"}
            prev = e["hash"]
        return {"ok": True, "length": len(rows), "broken_at": None, "reason": None}

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def head(self) -> str:
        return self._entries[-1]["hash"] if self._entries else GENESIS_HASH


# --------------------------------------------------------------------------
# Singleton + endpoint helper
# --------------------------------------------------------------------------
_LEDGER: EvidenceLedger | None = None
_LEDGER_LOCK = threading.Lock()


def auto_store(*, dsn_factory: Callable[[], Any] | None = None,
               prefer: str | None = None) -> Any:
    """Pilih store terbaik yang BENAR-BENAR bisa dipakai (Gap #2 iterasi 3).

    Urutan: **Postgres/Supabase** (bila kredensial ada, koneksi berhasil, dan
    DDL terpasang) → **memori**. Kegagalan apa pun diturunkan ke memori dengan
    peringatan — kehilangan persistensi lebih baik daripada endpoint
    ``/evidence`` mati total.

    Paksa memori dengan ``KATALIR_EVIDENCE_STORE=memory`` (dipakai test agar
    tidak menyentuh jaringan).
    """
    import logging
    pref = (prefer if prefer is not None else os.environ.get(STORE_ENV, ""))
    pref = (pref or "").strip().lower()
    if pref in ("memory", "mem", "off", "0"):
        return MemoryEvidenceStore()
    try:
        store = PostgresEvidenceStore(dsn_factory)
        store.ensure_schema()
        return store
    except Exception as exc:  # noqa: BLE001 - degradasi yang disengaja
        logging.getLogger(__name__).warning(
            "evidence ledger: Postgres tidak tersedia (%s: %s) — memakai "
            "store memori; entri TIDAK bertahan setelah restart.",
            type(exc).__name__, exc,
        )
        return MemoryEvidenceStore()


def get_ledger() -> EvidenceLedger:
    """Ledger proses-tunggal (lazy). Store Postgres bila tersedia.

    Bila ``EVIDENCE_LEDGER_KEY`` belum diset, kunci efemera dibuat (peringatan
    dicatat) supaya endpoint tetap hidup; konsekuensinya entri lama tidak bisa
    diverifikasi setelah restart — set env di produksi.
    """
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            store = auto_store()
            try:
                _LEDGER = EvidenceLedger(store=store)
            except LedgerError:
                import logging
                import secrets
                logging.getLogger(__name__).warning(
                    "%s belum diset — ledger memakai kunci efemera; entri tidak "
                    "akan terverifikasi setelah restart.", DEFAULT_KEY_ENV,
                )
                _LEDGER = EvidenceLedger(key=secrets.token_bytes(32),
                                         store=store)
        return _LEDGER


def set_ledger(ledger: EvidenceLedger) -> None:
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = ledger


def verify_payload(ledger: EvidenceLedger, entry_id: str) -> dict:
    """Bentuk respons untuk ``GET /evidence/{id}/verify``."""
    entry = ledger.find(entry_id)
    if entry is None:
        return {"found": False, "entry_id": entry_id,
                "valid": False, "reason": "entri tidak ditemukan"}
    chain = ledger.verify_chain()
    return {
        "found": True,
        "entry_id": entry_id,
        "seq": entry["seq"],
        "valid": bool(ledger.verify_entry(entry) and chain["ok"]),
        "entry_valid": ledger.verify_entry(entry),
        "chain_ok": chain["ok"],
        "chain_length": chain["length"],
        "broken_at": chain["broken_at"],
        "reason": chain["reason"],
        "head": ledger.head,
    }


__all__ = [
    "DEFAULT_KEY_ENV",
    "GENESIS_HASH",
    "STORE_ENV",
    "ChainBrokenError",
    "EvidenceLedger",
    "LedgerError",
    "MemoryEvidenceStore",
    "PostgresEvidenceStore",
    "auto_store",
    "canonical_json",
    "chain_hash",
    "content_hash",
    "get_ledger",
    "set_ledger",
    "verify_payload",
]
