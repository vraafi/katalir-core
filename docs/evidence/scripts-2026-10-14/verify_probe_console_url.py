"""Bukti deterministik: console error kini menyimpan URL (celah instrumen B-09).

Temuan 14 Okt 2026 (`docs/final-verdict-v4-2026-10-14.md` §3): B-09 gagal dengan
`error_console=2` (dua 404), tetapi rekaman console TIDAK memuat URL sumbernya —
teksnya hanya
    `Failed to load resource: the server responded with a status of 404 ()`
tanpa menyebut resource mana. Akibatnya penyebab B-09 tidak bisa dipastikan
(regresi tema? pihak ketiga?) tanpa membuka DevTools manual.

Skrip ini menguji `Probe._on_console` / `_on_pageerror` / `err_summary` dengan
objek pesan PALSU — tanpa browser, tanpa jaringan. Yang dikunci:
  1. pesan console error menyimpan `url` + `line` dari `location`;
  2. `err_summary()` menampilkan URL (bisa dibaca langsung di log run);
  3. pesan tanpa `location` TIDAK melempar (pesan bisa sudah terlepas);
  4. `pageerror` menyimpan stack dan tidak crash.

Jalankan: python docs/evidence/scripts-2026-10-14/verify_probe_console_url.py
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _repo_root() -> pathlib.Path:
    for cand in [HERE, *HERE.parents]:
        if (cand / "tests" / "user_test" / "rus_core.py").exists():
            return cand
    raise SystemExit("repo root tidak ditemukan")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "tests" / "user_test"))

from rus_core import Probe  # noqa: E402

FAILURES: list[str] = []
TOTAL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  :: {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


class _FakePage:
    """Halaman palsu: hanya merekam handler `on()`."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def on(self, ev: str, fn) -> None:  # noqa: ANN001
        self.handlers[ev] = fn


class _FakeMsg:
    """ConsoleMessage palsu (Playwright: `.type`, `.text`, `.location`)."""

    def __init__(self, type_: str, text: str, url: str | None = None,
                 line: int | None = None, *, broken_location: bool = False) -> None:
        self.type = type_
        self.text = text
        self._loc = None if broken_location else {
            "url": url or "", "lineNumber": line, "columnNumber": 0}
        self._broken = broken_location

    @property
    def location(self):  # noqa: ANN201
        if self._broken:
            raise RuntimeError("message detached")
        return self._loc


class _FakeErr(Exception):
    def __init__(self, msg: str, stack: str) -> None:
        super().__init__(msg)
        self.stack = stack


print("=== Probe console capture (stub, tanpa browser) ===")

pr = Probe(_FakePage(), "stub")

# 1. console error dengan location -> url + line tersimpan
pr._on_console(_FakeMsg(
    "error",
    "Failed to load resource: the server responded with a status of 404 ()",
    "https://katalir.de5.net/_next/static/chunks/missing.js", 42))
rec0 = pr.console[0]
check("error menyimpan url", rec0.get("url") == "https://katalir.de5.net/_next/static/chunks/missing.js",
      repr(rec0.get("url")))
check("error menyimpan line", rec0.get("line") == 42, repr(rec0.get("line")))
check("error menyimpan text", "404" in rec0.get("text", ""), repr(rec0.get("text"))[:60])

# 2. warning juga terekam (perilaku lama dipertahankan)
pr._on_console(_FakeMsg("warning", "sebuah peringatan", "https://katalir.de5.net/x", 7))
check("warning terekam", len(pr.console) == 2, f"n={len(pr.console)}")

# 3. tipe lain (log/info) DIABAIKAN
pr._on_console(_FakeMsg("log", "bukan error", "https://katalir.de5.net/y", 1))
check("log diabaikan", len(pr.console) == 2, f"n={len(pr.console)}")

# 4. err_summary menampilkan URL -> penyebab terbaca di log
summary = pr.err_summary()
check("err_summary memuat url", "missing.js" in summary, summary[:120])
check("err_summary hanya error (bukan warning)",
      "peringatan" not in summary, summary[:120])

# 5. errs() tetap menyaring error/pageerror
check("errs() menyaring", len(pr.errs()) == 1, f"n={len(pr.errs())}")

# 6. location rusak TIDAK melempar
pr2 = Probe(_FakePage(), "stub2")
try:
    pr2._on_console(_FakeMsg("error", "tanpa location", broken_location=True))
    check("location rusak tidak melempar", True, repr(pr2.console[0]))
except Exception as exc:  # noqa: BLE001
    check("location rusak tidak melempar", False, f"{type(exc).__name__}: {exc}")

# 7. pageerror menyimpan stack
pr2._on_pageerror(_FakeErr("boom", "Error: boom\n    at foo (app.js:1:1)"))
pe = [c for c in pr2.console if c["type"] == "pageerror"]
check("pageerror terekam", len(pe) == 1, f"n={len(pe)}")
check("pageerror menyimpan stack", pe and "app.js" in pe[0].get("stack", ""),
      repr(pe[0].get("stack", ""))[:80])
check("pageerror url kosong (bukan resource)", pe and pe[0].get("url") == "")

# 8. handler benar-benar terpasang oleh __init__ (bukan hanya bisa dipanggil)
pg = _FakePage()
Probe(pg, "stub3")
check("handler console terpasang", "console" in pg.handlers, sorted(pg.handlers))
check("handler pageerror terpasang", "pageerror" in pg.handlers)

print()
if FAILURES:
    print(f"HASIL: GAGAL {len(FAILURES)}/{TOTAL} -> {FAILURES}")
    raise SystemExit(1)
print(f"HASIL: SEMUA PASS ({TOTAL} pemeriksaan)")
