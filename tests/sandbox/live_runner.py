"""live_runner.py — LIVE #1: Trigger -> Telegram (API NYATA).

MODE KREDENSIAL: **Opsi B (pragmatis)**
--------------------------------------
* **Bot token** : `TEST_TELEGRAM_BOT_TOKEN` bila ada; jika tidak, JATUH ke
  `TELEGRAM_BOT_TOKEN` dari `.env` (bot produksi). Ini keputusan eksplisit
  user: bot yang sama, grup yang berbeda.
* **Chat ID**   : WAJIB `TEST_TELEGRAM_CHAT_ID`. Tidak ada fallback ke chat
  produksi — itu diblokir keras oleh `assert_not_production_chat()`.

Jadi: bot produksi boleh dipakai, **tujuan kirim TIDAK boleh** chat produksi.

Alur tetap zero-trust:
    config node -> ${auth.telegram_bot} -> resolve_for_egress -> Telegram API
                -> mask_known_values -> redact_agent_output -> assert_no_leak

FAIL-CLOSED
-----------
Menolak berjalan bila: bot token tidak ada, `TEST_TELEGRAM_CHAT_ID` kosong,
format salah, chat id == chat produksi, atau `live.enabled` belum true.
Nilai kredensial TIDAK PERNAH dicetak.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(__file__).resolve().parent
for _p in (str(ROOT), str(SANDBOX)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_redactor as ar  # noqa: E402
import canary_scan  # noqa: E402
import credential_proxy as cp  # noqa: E402
import sandbox_runner as sr  # noqa: E402
from execution_engine import NodeKind  # noqa: E402

ENV_FILE = ROOT / ".env"
TEST_ENV_FILE = ROOT / ".env.test"
CONFIG_FILE = SANDBOX / "config.yaml"

BOT_TOKEN_RX = re.compile(r"^\d+:[A-Za-z0-9_-]+$")
CHAT_ID_RX = re.compile(r"^-?\d+$")


# ---------------------------------------------------------------------------
# ENV
# ---------------------------------------------------------------------------
def load_env_file(path: Path) -> dict[str, str]:
    """Parser .env minimalis. Nilai tidak pernah di-log."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_all_env() -> dict[str, str]:
    """Muat `.env` (produksi) lalu `.env.test` (menang) ke os.environ."""
    merged: dict[str, str] = {}
    for path in (ENV_FILE, TEST_ENV_FILE):
        for key, value in load_env_file(path).items():
            merged[key] = value
            os.environ.setdefault(key, value)
    return merged


# ---------------------------------------------------------------------------
# KREDENSIAL (Opsi B)
# ---------------------------------------------------------------------------
def get_telegram_bot_token() -> tuple[str, str]:
    """(token, sumber). Prioritas TEST_, lalu bot produksi dari `.env`."""
    token = (os.getenv("TEST_TELEGRAM_BOT_TOKEN") or "").strip()
    if token:
        return token, "TEST"
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if token:
        return token, "PRODUCTION_BOT"
    raise cp.CredentialMissingError("telegram_bot")


def get_telegram_chat_id() -> str:
    """Chat ID TUJUAN — WAJIB TEST_. Tidak ada fallback produksi."""
    chat_id = (os.getenv("TEST_TELEGRAM_CHAT_ID") or "").strip()
    if not chat_id:
        raise cp.CredentialMissingError("telegram_chat")
    return chat_id


def assert_not_production_chat(chat_id: str) -> None:
    """Blokir bila tujuan kirim sama dengan chat produksi."""
    prod_chat = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if prod_chat and str(chat_id).strip() == prod_chat:
        raise ValueError(
            "BLOCKED: TEST_TELEGRAM_CHAT_ID sama dengan production! "
            "Buat grup TEST baru.")


# ---------------------------------------------------------------------------
# LIVE MODE GATE
# ---------------------------------------------------------------------------
def live_enabled() -> bool:
    """Baca `live.enabled` dari config.yaml tanpa PyYAML.

    WAJIB melacak blok: berkas ini punya `canary: enabled: true` LEBIH DULU,
    jadi pencarian "baris enabled pertama" akan keliru mengembalikan True.
    """
    if not CONFIG_FILE.exists():
        return False
    in_live = False
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("live:"):
            in_live = True
            continue
        if in_live and line and not line.startswith(" "):
            in_live = False
        if in_live and line.strip().startswith("enabled:"):
            return line.split(":", 1)[1].strip().lower() == "true"
    return False


def set_live_enabled(value: bool) -> None:
    """Ubah HANYA baris `enabled:` di dalam blok `live:`."""
    lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines()
    out, in_live = [], False
    for line in lines:
        if line.startswith("live:"):
            in_live = True
            out.append(line)
            continue
        if in_live and line and not line.startswith(" "):
            in_live = False
        if in_live and line.strip().startswith("enabled:"):
            out.append(f"  enabled: {'true' if value else 'false'}")
            continue
        out.append(line)
    CONFIG_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# EGRESS NYATA
# ---------------------------------------------------------------------------
class LiveTelegramEgress:
    """Egress NYATA ke Telegram. Satu-satunya tempat nilai asli muncul."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.canary_seen_in_raw = False
        self.canary_stripped = False

    async def __call__(self, orch, node, inp) -> dict:
        cfg = orch._resolve_cfg(node.data.config or {}, where=f"node '{node.id}'")
        op = cfg.pop("op", None)
        if op != "telegram_send":
            raise RuntimeError(f"op live tidak didukung: {op!r}")

        # --- EGRESS: placeholder -> nilai asli (hanya di sini) ---
        egress = cp.resolve_cfg_for_egress(cfg)
        token = str(egress.get("token") or "")
        chat_id = str(egress.get("chat_id") or "")
        text = str(egress.get("text") or "")

        import httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = httpx.post(url, json={"chat_id": chat_id, "text": text},
                           timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            # HANYA nama kelas — URL memuat token, jangan pernah dikutip.
            raise RuntimeError(
                f"Telegram tidak terjangkau ({type(exc).__name__}).") from None

        raw = r.json() if r.text else {}
        self.sent.append({"http": r.status_code,
                          "ok": (raw or {}).get("ok")})
        if r.status_code >= 400:
            raise RuntimeError(f"Telegram menolak permintaan (HTTP {r.status_code}).")

        # --- BAGIAN 4b: canary HARUS terlihat di hasil mentah ---
        raw_blob = json.dumps(raw, default=str)
        self.canary_seen_in_raw = ar.scan_canary(raw_blob)

        # --- jalur pulang: mask nilai -> redact pola -> gerbang terakhir ---
        masked = cp.mask_known_values(raw)
        safe = ar.redact_agent_output(masked, raise_on_canary=False)
        safe_blob = json.dumps(safe, default=str)
        self.canary_stripped = not ar.scan_canary(safe_blob)
        cp.assert_no_leak(safe, where=f"output node '{node.id}'")
        return safe


def build_live_graph(text: str):
    """Sama seperti TEST #1 mode mock, tetapi egress-nya Telegram NYATA."""
    g = sr.make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("tg", {"kind": "mcp", "label": "telegram-live", "config": {
             "op": "telegram_send",
             "token": "${auth.telegram_bot}",
             "chat_id": "${auth.telegram_chat}",
             "text": text}}),
         ],
        [("t", "tg")])
    return g, {"text": "LIVE #1"}


def main() -> int:
    ap = argparse.ArgumentParser(description="LIVE #1 Trigger -> Telegram (real)")
    ap.add_argument("--enable-live", action="store_true",
                    help="set config.yaml live.enabled=true lalu jalankan")
    args = ap.parse_args()

    print("=" * 74)
    print("BAGIAN 3 — LIVE #1: Trigger -> Telegram (API NYATA, Opsi B)")
    print("=" * 74)

    load_all_env()

    # --- 1a/3a: .env.test + chat id ---
    print(f"\n[1a] .env.test ada: {TEST_ENV_FILE.exists()}")
    try:
        chat_id = get_telegram_chat_id()
    except cp.CredentialMissingError as exc:
        print(f"\n[1a] BLOCKED: {exc}")
        print("     Buat grup TEST, lalu tulis TEST_TELEGRAM_CHAT_ID ke .env.test")
        return 2

    # --- 3b: bot token ---
    try:
        token, source = get_telegram_bot_token()
    except cp.CredentialMissingError as exc:
        print(f"\n[3b] BLOCKED: bot token tidak ada ({exc})")
        return 2
    print(f"[3b] bot token sumber : {source}")
    print(f"     format token     : "
          f"{'OK' if BOT_TOKEN_RX.match(token) else 'SALAH'}")
    print(f"     chat id format   : "
          f"{'OK' if CHAT_ID_RX.match(chat_id) else 'SALAH'}")
    if not BOT_TOKEN_RX.match(token) or not CHAT_ID_RX.match(chat_id):
        print("\nBLOCKED: format kredensial tidak sesuai.")
        return 2

    # --- 3c/3d: SAFEGUARD chat produksi ---
    try:
        assert_not_production_chat(chat_id)
    except ValueError as exc:
        print(f"\n[3c] {exc}")
        return 2
    print("[3c/3d] SAFEGUARD OK — chat tujuan BUKAN chat produksi")

    # --- 3e: live mode ---
    if args.enable_live:
        set_live_enabled(True)
    if not live_enabled():
        print("\n[3e] live.enabled masih false — jalankan dengan --enable-live")
        return 3
    print("[3e] live.enabled = true")

    # --- 4a: canary ---
    canary = cp.generate_canary()
    print(f"[4a] canary dibuat : {canary}")

    cp.clear_store()
    cp.put_test_credential("telegram_bot", token, canary=False)
    cp.put_test_credential("telegram_chat", chat_id, canary=False)

    import datetime
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"Katalir Live Test #1 — {stamp} — {canary}"

    graph, trigger_input = build_live_graph(message)
    orch = sr.build_orch(graph, trigger_input)
    egress = LiveTelegramEgress()
    orch.EXECUTORS[NodeKind.MCP] = egress

    print(f"\n[3f] kirim pesan (len={len(message)}) ke grup TEST...")
    error = None
    try:
        asyncio.run(orch.run())
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    finally:
        # 3i + LARANGAN: live mode TIDAK boleh tetap aktif setelah test.
        set_live_enabled(False)
        print("[3i] live.enabled -> false (kembali ke safe mode)")

    states = dict(orch.states)
    print(f"     states        : {states}")
    print(f"     hasil egress  : {json.dumps(egress.sent)}")
    print(f"     error         : {error}")

    # --- 4b-4e: canary ---
    print("\n[4b] canary terlihat di hasil mentah : "
          f"{egress.canary_seen_in_raw}")
    print(f"     canary dibersihkan dari output  : {egress.canary_stripped}")

    print("\n[4c] scan berkas lokal...")
    local = canary_scan.scan_local()
    print(f"     sandbox hits : {local['sandbox_hits']} (harus [])")

    print("[4d/4e] scan execution_logs + chat_messages...")
    dbres = canary_scan.scan_db()
    db_hits: list = []
    for key in ("execution_logs", "chat_messages"):
        entry = dbres.get(key) or {}
        db_hits.extend(entry.get("hits") or [])
    print(f"     DB hits      : {db_hits} (harus [])")

    ok = (states.get("tg") == "completed" and error is None
          and egress.canary_seen_in_raw and egress.canary_stripped
          and not local["sandbox_hits"] and not db_hits
          and any(s.get("http") == 200 for s in egress.sent))
    print("\n" + "-" * 74)
    print(f"VERDICT LIVE #1: {'PASS' if ok else 'FAIL'}")
    print("-" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
