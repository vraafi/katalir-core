#!/usr/bin/env python3
"""
test_massal.py - Mass Testing Arsitektur MCP (Bypass UI -> _agentic_run).
========================================================================
Menembak langsung fungsi agen / tool dispatcher BUKAN lewat Streamlit.

Dua lapis pengujian:
  1) INTERSEPSI DETERMINISTIK: panggil tools.execute_tool tiap provider tanpa
     kredensial -> harus melempar CredentialMissingError(provider) yang sesuai.
  2) AGENTIC LOOP (Opsional): jika API key tersedia, panggil _agentic_run dengan
     prompt uji -> AI memilih tool -> tangkap CredentialMissingError dari provider.

Jalankan:
    python test_massal.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# force fallback lokal bila Supabase belum dikonfigurasi penuh
import database as db
import tools

TEST_EMAIL = "test_massal@local.app"

# --------------------------------------------------------------------------
# Daftar uji: (tool_name, args, expected_provider)
# --------------------------------------------------------------------------
TOOL_TESTS = [
    ("baca_google_sheets",
     {"spreadsheet_id": "123", "range_data": "Sheet1!A1:C10"},
     "google_sheets"),
    ("kirim_email_gmail",
     {"tujuan": "bos@kantor.com", "subjek": "Laporan", "isi": "Halo"},
     "gmail"),
    ("tambah_agenda_calendar",
     {"nama_acara": "Meeting", "waktu": "2026-09-06 09:00"},
     "google_calendar"),
    ("send_whatsapp_message",
     {"pesan": "Halo", "nomor_tujuan": "+628123"},
     "whatsapp"),
]

# Prompt uji untuk lapis AGENTIC (opsional, butuh API key)
AGENTIC_PROMPTS = [
    "Tolong bacakan data dari spreadsheet ID 123",
    "Kirim email ke bos@kantor.com berisi laporan",
    "Buat jadwal meeting besok pagi",
]


def run_interception_layer():
    """Lapis 1: uji intersepsi kredensial deterministik per-tool."""
    print("=" * 64)
    print("LAPIS 1: INTERSEPSI KREDENSIAL (deterministik)")
    print("=" * 64)
    results = []
    for name, args, expected_provider in TOOL_TESTS:
        try:
            tools.execute_tool(name, args, TEST_EMAIL)
            results.append((name, False, "TIDAK melempar error (kredensial ada?)"))
        except tools.CredentialMissingError as e:
            got = e.provider_name
            ok = got == expected_provider
            msg = (f"LULUS INTERSEPSI -> {got}"
                   if ok else f"SALAH PROVIDER: {got} (harus {expected_provider})")
            results.append((name, ok, msg))
            print(f"[{name}] {msg}")
        except Exception as e:
            results.append((name, False, f"GAGAL: {type(e).__name__}: {e}"))
            print(f"[{name}] GAGAL: {type(e).__name__}: {e}")
    return results


def run_agentic_layer():
    """Lapis 2 (opsional): panggil _agentic_run langsung (bypass UI)."""
    print("\n" + "=" * 64)
    print("LAPIS 2: AGENTIC LOOP (_agentic_run) - bypas UI")
    print("=" * 64)
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY_1")
    if not api_key:
        print("  [SKIP] API key tidak ditemukan. Lewati lapis agentic.")
        return

    # import app_frontend; perlu mock st.rerun di lingkungan non-UI
    import streamlit as st
    if not hasattr(st, "_massal"):
        orig = st.rerun
        def _noop_rerun():
            pass
        st.rerun = _noop_rerun
    import app_frontend as fa

    for prompt in AGENTIC_PROMPTS:
        print(f"\n  Prompt: {prompt!r}")
        try:
            fa._agentic_run(prompt, TEST_EMAIL)
            # Tak lempar -> folder berhasil (mungkin kredensial ter-set sebelumnya)
            print("  [INFO] Tidak melempar CredentialMissing - agen menyelesaikan.")
        except tools.CredentialMissingError as e:
            print(f"  [OK] Interupsi kredensial -> {e.provider_name}")
        except Exception as e:
            print(f"  [INFO] {type(e).__name__}: {e}")


def main():
    results = run_interception_layer()
    run_agentic_layer()

    # ------------------- SUMMARY -------------------
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 64)
    print("LAPORAN AKHIR - Sistem Brankas Kredensial (BYOK)")
    print("=" * 64)
    for name, ok, _ in results:
        mark = "✅" if ok else "❌"
        print(f"  {mark} {name:28} terhubung{' ' if ok else ' / GAGAL'}")
    print("-" * 64)
    print(f"  TOTAL  : {passed} lulus, {failed} gagal (dari {len(results)} alat)")
    print("  STATUS : " + ("SEMUA ALAT TERHUBUNG DENGAN RAMPAS ✅"
                           if failed == 0 else "ADA ALAT YANG GAGAL ❌"))
    print("=" * 64)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())