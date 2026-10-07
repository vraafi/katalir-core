"""live_runner.py — LIVE #1: Trigger -> Telegram (API NYATA).

Bedanya dengan `sandbox_runner.py` (mode mock): titik egress di sini menembak
`https://api.telegram.org/bot<token>/sendMessage` yang sesungguhnya, memakai
kredensial **TEST** (`TEST_TELEGRAM_*`), bukan kredensial produksi.

Alur tetap sama (zero-trust):
    config node -> ${auth.telegram_bot} -> resolve_for_egress -> Telegram API
                -> mask_known_values -> redact_agent_output -> assert_no_leak

FAIL-CLOSED
-----------
Skrip ini MENOLAK berjalan bila:
  * `.env.test` tidak ada / variabel kosong / format salah,
  * `config.yaml: live.enabled` belum `true`,
  * nama variabel bukan `TEST_*` (dipaksa oleh `credential_proxy`).

Nilai kredensial TIDAK PERNAH dicetak — hanya status dan bentuknya.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(__file__).resolve().parent
for _p in (str(ROOT), str(SANDBOX)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_redactor as ar  # noqa: E402
import credential_proxy as cp  # noqa: E402
import sandbox_runner as sr  # noqa: E402
from execution_engine import NodeKind  # noqa: E402

TEST_ENV_FILE = ROOT / ".env.test"
CONFIG_FILE = SANDBOX / "config.yaml"

#: Format yang diminta brief.
BOT_TOKEN_RX = re.compile(r"^\d+:[A-Za-z0-9_-]+$")
CHAT_ID_RX = re.compile(r"^-?\d+$")


def load_env_test(path: Path = TEST_ENV_FILE) -> dict[str, str]:
    """Parser .env minimalis (tanpa dependensi). Nilai tidak pernah di-log."""
    if not path.exists():
        raise SystemExit(f"[FAIL] {path} tidak ada.")
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def validate(env: dict[str, str]) -> list[str]:
    """Kembalikan daftar masalah (kosong = valid). Tidak menyentuh nilai."""
    problems: list[str] = []
    token = env.get("TEST_TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TEST_TELEGRAM_CHAT_ID", "")
    if not token:
        problems.append("TEST_TELEGRAM_BOT_TOKEN kosong")
    elif not BOT_TOKEN_RX.match(token):
        problems.append("TEST_TELEGRAM_BOT_TOKEN format salah "
                        "(harus \\d+:[A-Za-z0-9_-]+)")
    if not chat:
        problems.append("TEST_TELEGRAM_CHAT_ID kosong")
    elif not CHAT_ID_RX.match(chat):
        problems.append("TEST_TELEGRAM_CHAT_ID format salah (harus -?\\d+)")
    return problems


def live_enabled() -> bool:
    """Baca `live.enabled` dari config.yaml tanpa PyYAML.

    WAJIB melacak blok: berkas ini punya `canary: enabled: true` LEBIH DULU,
    jadi pencarian "baris enabled pertama" akan keliru mengembalikan True dan
    diam-diam mengaktifkan live mode.
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


class LiveTelegramEgress:
    """Egress NYATA ke Telegram. Satu-satunya tempat nilai asli muncul."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

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

        self.sent.append({"http": r.status_code,
                          "ok": (r.json() or {}).get("ok") if r.text else None})
        if r.status_code >= 400:
            raise RuntimeError(f"Telegram menolak permintaan (HTTP {r.status_code}).")

        raw = r.json() or {}
        safe = ar.redact_agent_output(cp.mask_known_values(raw))
        cp.assert_no_leak(safe, where=f"output node '{node.id}'")
        return safe


def build_live_graph():
    """Sama seperti TEST #1 mode mock, tetapi egress-nya Telegram NYATA."""
    g = sr.make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("tg", {"kind": "mcp", "label": "telegram-live", "config": {
             "op": "telegram_send",
             "token": "${auth.telegram_bot}",
             "chat_id": "${auth.telegram_chat}",
             "text": "Katalir LIVE test — pesan ini dikirim oleh egress nyata "
                     "ke grup TEST. {{t.context.text}}"}}),
         ],
        [("t", "tg")])
    return g, {"text": "jika Anda melihat ini, LIVE #1 PASS."}


def main() -> int:
    ap = argparse.ArgumentParser(description="LIVE #1 Trigger -> Telegram (real)")
    ap.add_argument("--enable-live", action="store_true",
                    help="set config.yaml live.enabled=true lalu jalankan")
    args = ap.parse_args()

    print("=" * 74)
    print("BAGIAN 1 — LIVE #1: Trigger -> Telegram (API NYATA)")
    print("=" * 74)

    # 1a. .env.test
    env = load_env_test()
    print(f"\n[1a] {TEST_ENV_FILE.name} ditemukan, "
          f"{len(env)} variabel terbaca")
    print(f"     kunci: {sorted(env.keys())}")

    # 1b. validasi format
    problems = validate(env)
    if problems:
        print("\n[1b] FORMAT/ISIAN BERMASALAH:")
        for p in problems:
            print(f"     - {p}")
        print("\nFAIL-CLOSED: tidak menjalankan live test.")
        return 2
    print("[1b] format OK: bot token cocok \\d+:[A-Za-z0-9_-]+, "
          "chat id cocok -?\\d+")

    # 1c. live mode
    if args.enable_live:
        set_live_enabled(True)
        print("[1c] config.yaml live.enabled -> true")
    if not live_enabled():
        print("\n[1c] live.enabled masih false. Jalankan dengan --enable-live "
              "setelah user mengonfirmasi.")
        return 3
    print("[1c] live.enabled = true")

    # daftarkan kredensial TEST (menolak nama non-TEST_)
    cp.clear_store()
    cp.put_test_credential("telegram_bot", env["TEST_TELEGRAM_BOT_TOKEN"],
                           canary=True)
    cp.put_test_credential("telegram_chat", env["TEST_TELEGRAM_CHAT_ID"],
                           canary=True)
    canary = cp.get_canary("telegram_bot")
    print(f"[1c] kredensial TEST terdaftar: {cp.store_keys()}")
    print(f"     canary aktif: {canary}")

    # 1d. jalankan LIVE #1
    graph, trigger_input = build_live_graph()
    orch = sr.build_orch(graph, trigger_input)
    egress = LiveTelegramEgress()
    orch.EXECUTORS[NodeKind.MCP] = egress

    print("\n[1d] menjalankan workflow (egress = api.telegram.org)...")
    error = None
    try:
        asyncio.run(orch.run())
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    states = dict(orch.states)
    print(f"     states   : {states}")
    print(f"     egress   : {json.dumps(egress.sent)}")
    if error:
        print(f"     error    : {error}")
    else:
        print(f"     output   : {json.dumps(orch.outputs, default=str)[:280]}")

    # 1f. canary scan
    blob = json.dumps(orch.outputs, default=str)
    canary_hit = ar.scan_canary(blob)
    leaks = cp.leaking_keys(blob)
    print(f"\n[1f] canary di output : {canary_hit} (harus False)")
    print(f"     nilai kredensial bocor: {leaks} (harus [])")

    ok = (states.get("tg") == "completed" and error is None
          and not canary_hit and not leaks
          and any(s.get("http") == 200 for s in egress.sent))
    print("\n" + "-" * 74)
    print(f"VERDICT LIVE #1: {'PASS' if ok else 'FAIL'}")
    print("-" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
