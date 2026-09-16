# security.py - Autentikasi JWT Supabase (server-side)
# PENTING: tidak bisa spoof — pemotongan user TARGET dari JWT signature
# bukan dari query param / body / header non-authenticated.
#
# STRATEGI VERIFIKASI (2026-09): DUA JALUR, LOKAL DIUTAMAKAN.
#
#   Masalah produksi yang pernah terjadi: `client.auth.get_user(token)` adalah
#   panggilan JARINGAN ke `<ref>.supabase.co`. Ketika DNS/TCP host itu tidak
#   responsif (mis. resolver ISP bermasalah — gejalanya ConnectTimeout, BUKAN
#   NameResolutionError), SETIAP endpoint ber-JWT menjawab 401 walau token
#   browser sepenuhnya sah. Di UI user melihat "Ada masalah, coba lagi." dan
#   riwayat chat seolah hilang — padahal token & DB sehat, hanya verifikasinya
#   yang bergantung jaringan.
#
#   Jalur 1 (utama): verifikasi signature secara LOKAL memakai public key dari
#   JWKS (`<url>/auth/v1/.well-known/jwks.json`) yang di-cache ke disk. Setelah
#   cache terisi, verifikasi TIDAK butuh jaringan -> tahan outage DNS maupun
#   downtime Supabase Auth.
#   Jalur 2 (cadangan): `auth.get_user()` seperti sebelumnya, dipakai hanya bila
#   JWKS belum pernah ter-cache dan tidak bisa diunduh (kompatibilitas dev).
#
#   PENGUATAN (2026-09) — setelah ditemukan bukti 401
#   `{"detail":"Token invalid: ConnectTimeout"}` pada /models & /chat:
#     1. Cache JWKS dihangatkan saat startup (`warm_jwks()`), bukan lazily di
#        request user pertama (yang dulu membayar cold fetch ~3.5s di dalam lock).
#     2. Unduhan memakai RETRY (default 3x) + timeout per percobaan 15s.
#     3. Bisa di-seed dari env `SUPABASE_JWKS` atau file `.jwks_cache.json`
#        sehingga verifikasi tetap jalan saat jaringan keluar bermasalah.
#     4. Percobaan unduhan yang gagal masuk COOLDOWN agar tidak setiap request
#        tertahan sampai timeout.

import json
import os
import threading
import time

import httpx
import jwt
from fastapi import HTTPException
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
# anon key cukup untuk auth.get_user (verify JWT + nacti leta user profil).
# Service role key BIASA bikin get_user bypass — pakai anon untuk verify proper.
SUPABASE_ANON = (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()
# Opsional: proyek Supabase LAMA memakai HS256 (shared secret) untuk access token.
SUPABASE_JWT_SECRET = (os.getenv("SUPABASE_JWT_SECRET") or "").strip()

_JWKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".jwks_cache.json")
_JWKS_TTL_SEC = 6 * 3600        # refresh cache tiap 6 jam
# Timeout PER PERCOBAAN. Dinaikkan dari 6s: pengukuran nyata menunjukkan
# cold fetch (DNS+TLS) ~3.5s di jaringan sehat, sehingga 6s + satu percobaan
# mudah terlampaui di jaringan flaky -> seluruh endpoint ber-JWT jadi 401.
_JWKS_TIMEOUT_SEC = float(os.getenv("SUPABASE_JWKS_TIMEOUT_SEC") or 15.0)
_JWKS_ATTEMPTS = max(1, int(float(os.getenv("SUPABASE_JWKS_ATTEMPTS") or 3)))
_JWKS_BACKOFF_SEC = 0.5
# Cooldown setelah percobaan unduh GAGAL. Tanpa ini, unduhan dilakukan SINKRON
# di dalam lock pada SETIAP request selama cache kosong -> tiap request user
# tertahan sampai timeout.
_JWKS_RETRY_COOLDOWN_SEC = float(os.getenv("SUPABASE_JWKS_COOLDOWN_SEC") or 30.0)
_AUDIENCE = "authenticated"     # aud standar access token Supabase

_auth_client = None
_lock = threading.Lock()
_jwks_cache = None
_jwks_fetched_at = 0.0
_jwks_last_error = ""
_jwks_last_fail_at = 0.0
_warm_started = False


def _get_auth_client():
    global _auth_client
    if _auth_client is None:
        from supabase import create_client
        if not (SUPABASE_URL and SUPABASE_ANON):
            raise HTTPException(500, "Supabase belum dikonfigurasi.")
        _auth_client = create_client(SUPABASE_URL, SUPABASE_ANON)
    return _auth_client


# ---------------------------------------------------------------------------
# JWKS: unduh sekali, cache ke disk -> verifikasi berikutnya offline
# ---------------------------------------------------------------------------
def _read_disk_cache():
    try:
        with open(_JWKS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data.get("keys"), list) and data["keys"]:
            return data
    except Exception:  # noqa: BLE001 - cache rusak/absen -> anggap kosong
        pass
    return None


def _write_disk_cache(doc):
    try:
        with open(_JWKS_PATH, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    except Exception:  # noqa: BLE001 - gagal cache bukan error fatal
        pass


def _seed_jwks():
    """Isi cache TANPA jaringan: dari `SUPABASE_JWKS` (env, JSON) lalu file cache.

    Dipakai agar deployment yang jaringan keluarnya bermasalah (gejala nyata:
    DNS/connect ke `<ref>.supabase.co` timeout) tetap bisa memverifikasi token
    secara offline. Public key bersifat publik, jadi aman ditanam lewat env.
    """
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache:
        return _jwks_cache
    raw = (os.getenv("SUPABASE_JWKS") or "").strip()
    if raw:
        try:
            doc = json.loads(raw)
            if isinstance(doc, dict) and doc.get("keys"):
                _jwks_cache = doc
                _jwks_fetched_at = time.time()
                return doc
        except Exception:  # noqa: BLE001 - env rusak -> lanjut ke disk cache
            pass
    disk = _read_disk_cache()
    if disk:
        _jwks_cache = disk
        _jwks_fetched_at = time.time()
        return disk
    return None


def _fetch_jwks():
    """Unduh JWKS dengan RETRY. `None` bila SEMUA percobaan gagal.

    Kenapa retry (bukan sekali coba): JWKS diambil lazily pada request pertama.
    Cold fetch terukur ~3.5s (DNS+TLS) di jaringan sehat, sehingga satu
    percobaan dengan timeout ketat mudah meleset di jaringan flaky. Gejala
    lamanya: `/models` dan `/chat` menjawab 401
    `{"detail":"Token invalid: ConnectTimeout"}` walau token browser sah.
    """
    global _jwks_last_error, _jwks_last_fail_at
    if not SUPABASE_URL:
        _jwks_last_error = "SUPABASE_URL kosong"
        _jwks_last_fail_at = time.time()
        return None
    url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    last = "unknown"
    for attempt in range(_JWKS_ATTEMPTS):
        try:
            resp = httpx.get(url, timeout=_JWKS_TIMEOUT_SEC)
            if resp.status_code == 200:
                doc = resp.json()
                if doc.get("keys"):
                    _jwks_last_error = ""
                    return doc
                last = "JWKS kosong"
            else:
                last = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001 - DNS/timeout/TLS
            last = exc.__class__.__name__
        if attempt + 1 < _JWKS_ATTEMPTS:
            time.sleep(_JWKS_BACKOFF_SEC * (attempt + 1))
    _jwks_last_error = last
    _jwks_last_fail_at = time.time()
    return None


def warm_jwks():
    """Prefetch JWKS saat startup (non-blocking, idempotent).

    Sebelum ini, request user PERTAMA yang membayar cold fetch di dalam lock —
    kalau timeout, ia jadi 401 yang menyesatkan. Dengan warm-up, cache (dan
    file `.jwks_cache.json`) sudah terisi sebelum user pertama datang.
    """
    global _warm_started
    with _lock:
        if _warm_started:
            return
        _warm_started = True
        _seed_jwks()

    def _bg():
        try:
            _get_jwks(force=True)
        except Exception:  # noqa: BLE001 - warm-up tidak boleh mematikan app
            pass

    threading.Thread(target=_bg, name="jwks-warm", daemon=True).start()


def _get_jwks(force=False):
    global _jwks_cache, _jwks_fetched_at
    with _lock:
        fresh = _jwks_cache and (time.time() - _jwks_fetched_at) < _JWKS_TTL_SEC
        if fresh and not force:
            return _jwks_cache
        # Cooldown: unduhan baru saja GAGAL -> jangan ulangi unduhan sinkron
        # untuk setiap request (dulu: tiap request tertahan sampai timeout,
        # dan semua request saling mengantre di lock ini).
        cooling = (not force) and (time.time() - _jwks_last_fail_at) < _JWKS_RETRY_COOLDOWN_SEC
        if cooling:
            if _jwks_cache:
                return _jwks_cache
            disk = _read_disk_cache()
            if disk:
                _jwks_cache = disk
                _jwks_fetched_at = time.time()
            return disk
        fetched = _fetch_jwks()
        if fetched:
            _jwks_cache = fetched
            _jwks_fetched_at = time.time()
            _write_disk_cache(fetched)
            return fetched
        # Jaringan gagal -> pakai cache (memori lalu disk) apa pun umurnya.
        if _jwks_cache:
            return _jwks_cache
        disk = _read_disk_cache()
        if disk:
            _jwks_cache = disk
            _jwks_fetched_at = time.time()
            return disk
        return None


def _key_for(header):
    """Pilih public key dari JWKS berdasarkan header `kid`.

    Kebijakan `kid` (dikunci oleh test_security_jwt.py):
      - `kid` ABSEN  -> fallback ke satu-satunya kunci. Diperlukan untuk token
        lama/klien yang tidak mengirim `kid`; bila JWKS berisi >1 kunci, pilihan
        dianggap ambigu dan DITOLAK (tidak menebak).
      - `kid` ADA tapi tidak ada di JWKS -> JANGAN menebak kunci lain. Token
        menyebut kunci yang tidak kita percayai, jadi verifikasi ditolak.
        Sebelumnya fallback `keys[0]` juga berlaku di kasus ini, sehingga `kid`
        palsu tetap diterima selama signature-nya kebetulan cocok dengan kunci
        tunggal tersebut — `kid` jadi tidak bermakna.

    Rotasi kunci: bila `kid` tidak ditemukan dan cache TIDAK fresh, satu
    percobaan refresh diizinkan (via `_get_jwks(force=True)`) supaya token yang
    ditandatangani kunci baru tidak ditolak selama TTL. Refresh hanya dicoba
    bila tidak sedang dalam cooldown pasca-kegagalan, agar token ber-`kid`
    palsu tidak bisa memaksa unduhan JWKS berulang (amplifikasi ke Supabase).
    """
    if header.get("alg") == "HS256":
        return SUPABASE_JWT_SECRET or None
    jwks = _get_jwks()
    if not jwks:
        return None
    keys = jwks.get("keys") or []
    kid = header.get("kid")
    cand = None
    if kid:
        cand = next((k for k in keys if k.get("kid") == kid), None)
        if cand is None:
            fresh = (time.time() - _jwks_fetched_at) < _JWKS_TTL_SEC
            cooling = (time.time() - _jwks_last_fail_at) < _JWKS_RETRY_COOLDOWN_SEC
            if not fresh and not cooling:
                jwks = _get_jwks(force=True) or jwks
                keys = jwks.get("keys") or []
                cand = next((k for k in keys if k.get("kid") == kid), None)
            if cand is None:
                return None
    elif len(keys) == 1:
        cand = keys[0]
    if cand is None:
        return None
    kty = cand.get("kty")
    jwk_json = json.dumps(cand)
    if kty == "EC":
        return ECAlgorithm.from_jwk(jwk_json)
    if kty == "RSA":
        return RSAAlgorithm.from_jwk(jwk_json)
    return None


class _KeyUnavailableError(Exception):
    """Kunci verifikasi TIDAK BISA dipegang -> hasil verifikasi DISKONKLUSIF.

    Dibedakan dari `jwt.InvalidKeyError` biasa supaya `get_current_user` dapat
    memisahkan dua hal yang sebelumnya tercampur dan menghasilkan pesan
    menyesatkan:

      - kunci tidak bisa dipegang (JWKS belum ter-cache & unduhan gagal, atau
        `SUPABASE_JWT_SECRET` belum dikonfigurasi) -> kita TIDAK TAHU tokennya
        sah atau tidak -> laporkan infra (503 "coba lagi").
      - kunci ADA dan signature/klaim dinilai lalu GAGAL -> token memang tidak
        sah -> 401.

    Bukti nyata (2026-09-16): token E2E yang `exp`-nya disunting tanpa tanda
    tangan baru (`_e2e_extend.py`) ditolak `InvalidSignatureError` secara lokal
    - keputusan yang final - tetapi responsnya 503 berpesan "Token TIDAK dinilai
    tidak sah". Pesan itu menyembunyikan sebab sebenarnya dan membuat
    investigasi mengarah ke jaringan.
    """


def _decode_local(token):
    """Verifikasi signature + expiry secara LOKAL. Raise jwt.* bila gagal.

    Klaim `aud` ditangani berbasis KEBERADAAN klaim, bukan jenis exception:
    PyJWT melempar `MissingRequiredClaimError` — SAUDARA, bukan subclass, dari
    `InvalidAudienceError` — saat klaim `aud` absen. Karena jalur ini dulu hanya
    menangkap `InvalidAudienceError`, verifikasi LOKAL jadi LEBIH KETAT daripada
    jalur jaringan `auth.get_user()`: token lama tanpa `aud` ditolak lokal lalu
    diterima jaringan, sehingga hasil verifikasi bergantung ada-tidaknya jaringan
    (dikunci oleh test_security_jwt.py). Aturannya kini eksplisit:
      - `aud` ABSEN -> signature tetap WAJIB sah, pemeriksaan aud dilewati.
      - `aud` ADA   -> wajib cocok `authenticated` (token aud lain ditolak).
    """
    header = jwt.get_unverified_header(token)
    alg = header.get("alg") or ""
    if alg == "HS256":
        # Proyek Supabase lama: signature memakai shared secret. Secret yang
        # belum dikonfigurasi = kunci TIDAK BISA dipegang (DISKONKLUSIF), bukan
        # bukti token palsu -> lihat `_KeyUnavailableError`.
        if not SUPABASE_JWT_SECRET:
            raise _KeyUnavailableError("SUPABASE_JWT_SECRET belum dikonfigurasi")
        key = SUPABASE_JWT_SECRET
    else:
        # PENTING: pisahkan "JWKS tidak bisa dipegang" dari "kid tidak dipercaya".
        #   - JWKS absen    -> DISKONKLUSIF: kita belum pernah melihat kuncinya,
        #     jadi tidak berhak mengklaim token tidak sah (masalah infra -> 503).
        #   - kid tak ada / pilihan ambigu -> KONKLUSIF: token menyebut kunci
        #     yang tidak kita percayai, jadi penolakan adalah keputusan final
        #     (401, lihat kebijakan `kid` di `_key_for`).
        if not _get_jwks():
            raise _KeyUnavailableError(
                "JWKS tidak tersedia (belum ter-cache dan unduhan gagal)"
            )
        key = _key_for(header)
        if key is None:
            raise jwt.InvalidKeyError("public key tidak tersedia untuk kid pada token")
    algs = [alg] if alg else ["ES256", "RS256"]
    claims = jwt.decode(token, options={"verify_signature": False}) or {}
    # `aud` ADA -> wajib cocok `authenticated`; `aud` ABSEN -> dilewati (signature
    # tetap wajib sah). `options={"verify_aud": False}` pada cabang "absen" juga
    # menutup bug cabang HS256: PyJWT melempar InvalidAudienceError ("Invalid
    # audience") saat payload BER-aud tapi decode dipanggil TANPA `audience` —
    # padahal SEMUA access token Supabase membawa `aud: "authenticated"`, sehingga
    # proyek HS256 lama selalu gagal verifikasi lokal (lalu 401 saat jaringan mati).
    audit = {"audience": _AUDIENCE} if "aud" in claims else {"options": {"verify_aud": False}}
    if alg == "HS256":
        return jwt.decode(token, key, algorithms=["HS256"], **audit)
    return jwt.decode(token, key, algorithms=algs, **audit)


def get_current_user(authorization: str | None = None):
    """Pemotong user dari JWT Supabase. JANGAN pernah pakai email param/body.

    Verifikasi lokal (JWKS cache) didahulukan supaya outage DNS Supabase tidak
    lagi mematikan seluruh endpoint. `auth.get_user()` hanya dipakai bila JWKS
    belum pernah ter-cache dan tidak bisa diunduh.

    Returns:
        dict {id, email} verified dari token.
    Raises:
        HTTPException 401 jika token kosong / invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token wajib (Authorization: Bearer <jwt>).")
    token = authorization.replace("Bearer ", "", 1).strip()
    if not token:
        raise HTTPException(401, "Token kosong.")

    # --- Jalur 1: verifikasi lokal (tanpa jaringan) ------------------------
    # `local_verdict` memisahkan hasil lokal yang DISKONKLUSIF (kunci tidak bisa
    # dipegang -> jangan mengklaim token tidak sah) dari yang KONKLUSIF (kunci
    # ada, signature/klaim dinilai, lalu gagal -> token memang tidak sah).
    local_verdict = None
    try:
        claims = _decode_local(token)
        sub = str(claims.get("sub") or "")
        email = (claims.get("email") or "").lower().strip()
        if sub:
            return {"id": sub, "email": email}
        local_err = "klaim sub kosong"
        local_verdict = "invalid"   # kunci sah, klaim sub tidak ada -> final
    except _KeyUnavailableError as exc:
        local_err = f"{exc.__class__.__name__}: {exc}"
        local_verdict = "key_unavailable"
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token kedaluwarsa. Silakan login ulang.")
    except Exception as exc:  # noqa: BLE001 - signature/klaim/kid invalid
        local_err = exc.__class__.__name__
        local_verdict = "invalid"

    # --- Jalur 2: cadangan jaringan ----------------------------------------
    try:
        client = _get_auth_client()
        resp = client.auth.get_user(token)
        user = resp.user
        if not user or not getattr(user, "id", None):
            raise HTTPException(401, "User tidak ditemukan dalam token.")
        return {
            "id": str(user.id),
            "email": (getattr(user, "email", None) or "").lower().strip(),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - token invalid / network
        detail = exc.__class__.__name__
        # BEDAKAN INFRA vs TOKEN (bukti E2E 2026-09: respons nyata
        # `{"detail":"Token invalid: ConnectTimeout"}` — 42 byte — muncul di
        # /models & /chat walau header `Authorization: Bearer <jwt>` SUDAH
        # terkirim dan token browser sah).
        #
        # Saat host `<ref>.supabase.co` tidak responsif, DUA hal gagal
        # bersamaan: (1) JWKS tidak bisa diunduh -> kunci lokal absen, dan
        # (2) `auth.get_user()` timeout. Kode lama melaporkannya sebagai
        # "Token invalid" -> user melihat "Ada masalah, coba lagi." dan
        # mengira sesinya mati, padahal ini murni gangguan jaringan.
        #
        # Kontrak: 503 = tidak bisa memverifikasi SEKARANG (infra);
        # 401 = token MEMANG tidak sah.
        #
        # BUG YANG DIPERBAIKI (2026-09-16, dibuktikan `_e_bug503_probe.py`):
        # syarat `or _jwks_last_error` membuat flag LENGKET dari kegagalan
        # unduhan masa lalu membajak kasus yang sudah KONKLUSIF. Token dengan
        # signature palsu (kid cocok, kunci berbeda) ditolak `InvalidSignatureError`
        # secara lokal — keputusan final — tetapi dilaporkan 503 berpesan
        # "Token TIDAK dinilai tidak sah". Pesan itu menyembunyikan sebab nyata
        # dan mengarahkan investigasi ke jaringan. Sekarang verifikasi lokal
        # yang KONKLUSIF menang.
        if local_verdict == "invalid":
            raise HTTPException(
                401,
                f"Token invalid: {detail}; verifikasi lokal: {local_err}.",
            )
        _INFRA_ERRORS = (
            "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
            "ReadError", "WriteError", "PoolTimeout", "TransportError",
            "NetworkError", "RemoteProtocolError", "ProxyError",
        )
        if detail in _INFRA_ERRORS or _jwks_last_error:
            raise HTTPException(
                503,
                "Verifikasi token sementara tidak tersedia (gangguan jaringan "
                f"ke penyedia identitas): {detail}"
                + (f"; JWKS: {_jwks_last_error}" if _jwks_last_error else "")
                + ". Token TIDAK dinilai tidak sah — silakan coba lagi.",
            )
        raise HTTPException(401, f"Token invalid: {detail}; lokal: {local_err}")


# Seed cache saat import (murah, TANPA jaringan) supaya proses yang di-restart
# bisa langsung verifikasi offline dari `.jwks_cache.json` atau `SUPABASE_JWKS`,
# tanpa menunggu cold fetch. Unduhan sesungguhnya dilakukan `warm_jwks()`.
_seed_jwks()