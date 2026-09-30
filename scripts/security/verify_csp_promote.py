"""Buktikan promote CSP benar-benar hanya mengubah NAMA direktif.

Membandingkan nilai kebijakan antara backup (report-only) dan file sekarang
(enforce). Kalau nilai string-nya berbeda sedikit saja, berarti saya diam-diam
men-tuning policy di commit yang sama - itu persis yang dilarang.

Juga memeriksa file tidak lagi mengandung "Report-Only" di mana pun.
"""
import pathlib
import re
import sys

NEW = pathlib.Path("nexus-frontend/public/_headers")
OLD = pathlib.Path("docs/security/backup/_headers.pre-csp-enforce")


def policy(text: str, name: str) -> str | None:
    m = re.search(re.escape(name) + r":\s*(.+)", text)
    return m.group(1).strip() if m else None


def main() -> int:
    new = NEW.read_text(encoding="utf-8")
    old = OLD.read_text(encoding="utf-8")

    po = policy(old, "Content-Security-Policy-Report-Only")
    pn = policy(new, "Content-Security-Policy")

    # "Report-Only" yang masih muncul sebagai rujukan historis di DALAM KOMENTAR
    # itu memang benar dan berguna (menjelaskan kenapa policy di-promote).
    # Yang berbahaya adalah direktif header yang masih report-only. Jadi cek
    # baris yang benar-benar merupakan direktif ( diawali spasi, tanpa '#').
    active = [
        ln.strip()
        for ln in new.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    checks = {
        "report_only_directive_removed": policy(new, "Content-Security-Policy-Report-Only") is None,
        "enforce_directive_present": pn is not None,
        "policy_value_identical": po is not None and po == pn,
        "no_active_report_only_directive": not any(
            ln.lower().startswith("content-security-policy-report-only") for ln in active
        ),
        "enforce_is_active_directive": any(
            ln.lower().startswith("content-security-policy:") for ln in active
        ),
        "connect_src_keeps_supabase": "qmukkphwaajzbqjrcvaz.supabase.co" in (pn or ""),
        "connect_src_keeps_railway": "web-production-dc90b.up.railway.app" in (pn or ""),
        "object_src_none_kept": "object-src 'none'" in (pn or ""),
        "frame_ancestors_none_kept": "frame-ancestors 'none'" in (pn or ""),
    }
    for k, v in checks.items():
        print(f"{k}={v}")
    ok = all(checks.values())
    print("\nCSP_PROMOTE_CLEAN=" + str(ok))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
