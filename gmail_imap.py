"""gmail_imap.py — Gmail Trigger via IMAP + App Password (NO OAuth).

KENAPA BUKAN OAUTH (keputusan arsitektur, 2026-10-03)
-------------------------------------------------
Scope `gmail.readonly` dan `gmail.modify` adalah RESTRICTED scope di Google.
Memakainya untuk aplikasi pihak ketiga memicu CASA review Tier 3: biaya
$500-$4.500 dan审核 4-12 minggu. Tidak realistis untuk deadline 3 hari, dan
butuh verifikasi aplikasi Google. Jadi JALUR INI sengaja TIDAK memakai
OAuth sama sekali.

IMAP + App PasswordJdengan]):
  * tidak butuh OAuth consent screen,
  * tidak butuh CASA / verifikasi aplikasi,
  * jalan di akun Gmail biasa (gratis),
  * scope yang diminta nol.

User membuat App Password sendiri di
https://myaccount.google.com/apppasswords (butuh 2FA aktif).

CATATAN KEAMANAN
----------------
App password adalah kredensial SEJATI yang bisa login ke kotak masuk. Karena
itu:
  * TIDAK PERNAH dikembalikan di balasan tool,
  * TIDAK PERNAH di-log,
  * TIDAK dikembalikan ke frontend apa pun,
  * disimpan terenkripsi di `user_vault` via `vault_security` (Fernet).

CATATAN IMPLEMENTASI
--------------------
Task awal meminta `imapclient` + `mailparser`. Di lingkungan ini
`mailparser` TIDAK punya distribusi yang bisa diakses
(`ERROR: Could not find a version that satisfies the requirement mailparser
(from versions: none)`). Daripada memblokir pengerjaan, implementasi memakai
STDLIB Python (`imaplib` + `email`), yang:
  * nol dependency baru (tidak menambah risiko build produksi),
  * parser MIME stdlib sudah menangani multipart, charset, attachment,
  * jauh lebih mudah diuji tanpa jaringan.
"""

from __future__ import annotations

import email
import imaplib
import ssl
from email import policy as _email_policy
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any

# Provider key di `user_vault`.
VAULT_PROVIDER = "gmail_imap"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
DEFAULT_TIMEOUT_S = 30


class GmailImapError(RuntimeError):
    """Kegagalan IMAP yang aman ditampilkan ke user (tanpa bocor password)."""


def normalize_app_password(raw: str) -> str:
    """Bersihkan App Password.

    Google menampilkannya sebagai 16 karakter DENGAN SPASI
    (mis. `abcd efgh ijkl mnop`). IMAP hanya menerima bentuk tanpa spasi.
    Menghapus spasi mencegah error login yang sangat membingungkan.
    """
    return "".join(str(raw or "").split())


def decode_mime_header(value: Any) -> str:
    """Decode header RFC 2047 (`=?utf-8?B?...?=`) menjadi teks biasa."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:  # noqa: BLE001 - header rusak tidak menjatuhkan poll
        return str(value)


def extract_body(msg: Any) -> tuple[str, str]:
    """Kembalikan `(text_plain, text_html)` dari satu pesan.

    Mengambil body dari bagian non-attachment secara rekursif dan menghormati
    `Content-Disposition: attachment` (attachment tidak boleh dianggap body —
    itu penyebab umum "email terbaca tapi isinya kosong").
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: Any) -> None:
        ctype = part.get_content_type()
        disp = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disp:
            return
        if part.is_multipart():
            for sub in part.iter_parts():
                walk(sub)
            return
        if ctype not in ("text/plain", "text/html"):
            return
        try:
            body = part.get_content()
        except Exception:  # noqa: BLE001
            payload = part.get_payload(decode=True)
            if payload is None:
                return
            charset = part.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset, errors="replace")
            except LookupError:
                body = payload.decode("utf-8", errors="replace")
        if not isinstance(body, str):
            return
        (html_parts if ctype == "text/html" else plain_parts).append(body)

    walk(msg)
    return ("\n".join(plain_parts).strip(), "\n".join(html_parts).strip())


def trigger_gmail_imap(
    email_address: str,
    app_password: str,
    subject_filter: str = "",
    max_messages: int = 10,
    unread_only: bool = True,
    *,
    mailbox: str = "INBOX",
    timeout_s: int = DEFAULT_TIMEOUT_S,
    mark_seen: bool = False,
) -> dict:
    """Poll Gmail via IMAP dan kembalikan email baru sebagai dict.

    TIDAK memakai OAuth. Butuh App Password 16 karakter yang dibuat user di
    https://myaccount.google.com/apppasswords.

    `mark_seen=False` (default) menjaga flag UNSEEN tetap utuh supaya trigger
    berikutnya tidak melewati email yang sama. Kalau `unread_only=True` DAN
    `mark_seen=True`, flag UNSEEN sengaja dihapus setelah dibaca
    (pola 'consume-once').

    Mengembalikan dict `{status, count, emails, criteria}`.
    Melempar `GmailImapError` untuk kegagalan yang aman ditampilkan.
    """
    addr = str(email_address or "").strip()
    pw = normalize_app_password(app_password)
    if not addr or "@" not in addr:
        raise GmailImapError("Alamat Gmail tidak valid.")
    if not pw:
        raise GmailImapError("App Password wajib diisi (16 karakter, tanpa spasi).")

    try:
        limit = max(1, min(int(max_messages or 10), 50))
    except Exception:  # noqa: BLE001
        limit = 10

    # Kriteria pencarian IMAP (Gmail Needle syntax). Subjek disisipkan dengan
    # kutip agar spasi tidak merusak query.
    criteria: list[str] = []
    if unread_only:
        criteria.append("UNSEEN")
    subj = str(subject_filter or "").strip()
    if subj:
        safe = subj.replace('"', "")
        criteria.append(f'(SUBJECT "{safe}")')
    if not criteria:
        criteria = ["ALL"]

    try:
        ctx = ssl.create_default_context()
        client = imaplib.IMAP4_SSL(
            IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=timeout_s
        )
    except Exception as exc:  # noqa: BLE001
        raise GmailImapError(f"Tidak bisa terhubung ke {IMAP_HOST}: {exc}") from exc

    try:
        try:
            client.login(addr, pw)
        except imaplib.IMAP4.error as exc:
            # Sengaja tidak menyertakan pesan mentah: bisa memuat username.
            raise GmailImapError(
                "Login IMAP gagal. Pastikan App Password benar dan 2FA aktif "
                "(https://myaccount.google.com/apppasswords)."
            ) from exc

        try:
            client.select(mailbox, readonly=not mark_seen)
        except imaplib.IMAP4.error as exc:
            raise GmailImapError(f"Gagal membuka folder {mailbox}: {exc}") from exc

        typ, data = client.uid("SEARCH", None, *criteria)
        if typ != "OK":
            raise GmailImapError("Pencarian IMAP gagal.")
        uids = _decode_uid_list((typ, data))[-limit:]

        results: list[dict] = []
        for uid in uids:
            # BUG FIX 2026-10-04: UID dari `UID SEARCH` datang sebagai BYTES
            # (`b'12345'`). `imaplib.uid()` butuh string; kalau diberi bytes,
            # imaplib merakit perintah yang rusak dan Gmail membalas
            # `BAD Could not parse command`. Gejalanya: trigger selalu gagal
            # padahal login dan SEARCH sudah berhasil.
            # Bukti: traceback menunjuk baris ini, bukan baris SEARCH.
            uid_s = uid.decode() if isinstance(uid, (bytes, bytearray)) else str(uid)
            typ, payload = client.uid("FETCH", uid_s, "(BODY.PEEK[])")
            if typ != "OK" or not payload:
                continue
            raw = b""
            for part in payload:
                if (isinstance(part, tuple) and len(part) > 1
                        and isinstance(part[1], (bytes, bytearray))):
                    raw = bytes(part[1])
                    break
            if not raw:
                continue
            results.append(parse_message(raw, uid=uid_s))

        return {
            "status": "ok",
            "email": addr,
            "count": len(results),
            "criteria": criteria,
            "emails": results,
        }
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001 - logout gagal tidak relevan
            pass



def _parse_sender(raw: Any) -> dict:
    """Pisahkan header From jadi {"name", "email"} memakai `parseaddr`.

    Menangani:
      - "Nama <surel@example.com>"  -> name dipisah, email diambil
      - "surel@example.com"         -> name kosong, email diambil
      - nama ber-enkode RFC 2047   -> didekode dulu
      - header kosong/rusak        -> dict kosong, TIDAK melempar
    """
    header = decode_mime_header(raw)
    if not header:
        return {"name": "", "email": ""}
    try:
        name, addr = parseaddr(header)
    except Exception:  # noqa: BLE001 - header rusak tidak menjatuhkan poll
        return {"name": "", "email": ""}
    return {"name": str(name or "").strip(), "email": str(addr or "").strip()}


def parse_message(raw_bytes: bytes, uid: str = "") -> dict:
    """Parse satu pesan RFC822 menjadi dict yang stabil (dipakai test juga)."""
    msg = email.message_from_bytes(raw_bytes, policy=_email_policy.default)
    plain, html = extract_body(msg)
    return {
        "id": str(uid or msg.get("Message-ID", "")),
        "subject": decode_mime_header(msg.get("Subject")),
        "from": decode_mime_header(msg.get("From")),
        # BUG FIX 2026-10-04: `sender` terstruktur lewat parseaddr.
        # Sebelumnya tidak ada sama sekali; header From mentah seperti
        # "Jos'n Wahari <andi@contoh.co.id>" sulit dipakai pemanggil (harus
        # memotong string sendiri). Dipisah jadi {"name", "email"}.
        "sender": _parse_sender(msg.get("From")),
        "date": decode_mime_header(msg.get("Date")),
        "to": decode_mime_header(msg.get("To")),
        "body": plain[:20000],
        "body_html": html[:20000],
        "has_body": bool(plain or html),
    }


def _decode_uid_list(resp: Any) -> list:
    """Ambil daftar UID dari respons `SEARCH` IMAP, satu UID per elemen.

    BUG FIX 2026-10-04 - akar masalah trigger selalu gagal.

    imaplib mengembalikan `data` sebagai DAFTAR byte: `[b'3806 3807']`.
    Versi lama menulis `resp[1] if isinstance(resp[1], list) else ...`, jadi
    ketika `resp[1]` berupa list, isinya TIDAK dipecah dan yang dikembalikan
    `[b'3806 3807']` - satu elemen berisi spasi.

    Fel FETCH berikutnya jadi:
        UID FETCH 3806 3807 (BODY.PEEK[])
    yang greet-nya `BAD Could not parse command`.

    Karena itu bug ini HANYA muncul saat ada 2+ email belum dibaca. Dengan satu
    email, isinya kebetulan tanpa spasi sehingga tidak terlihat - itu sebabnya
    tes manual satu-UID selalu lolos.
    """
    if not resp or len(resp) < 2 or not resp[1]:
        return []
    raw = resp[1]
    out: list = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, (bytes, bytearray)):
                out.extend(bytes(item).split())
            elif isinstance(item, str):
                out.extend(item.split())
        return out
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).split()
    return str(raw).split()