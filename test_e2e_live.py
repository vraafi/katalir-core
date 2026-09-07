"""
test_e2e_live.py — Pengujian Otonom Penuh (E2E Live Test)
================================================================
Tujuan: Memvalidasi bahwa API Key asli dari file `.env` benar-benar
        divalidasi sukses oleh server Google (bukan sekadar mengecek
        keberadaan file). Memakai streamlit.testing.v1.AppTest untuk
        mensimulasikan interaksi user di UI nyata.

Menjalankan:
    pytest test_e2e_live.py -v -s
        (flag -s agar print jawaban asli AI terlihat di terminal)
"""
import os

# 1) Muat .env secara paksa ke memori OS sebelum apa pun.
from dotenv import load_dotenv
load_dotenv()


def _chat_bubbles(at) -> list:
    """Gelembung chat native (st.chat_message): user + assistant."""
    return list(at.chat_message)


def test_live_agent_response():
    # 2) Load aplikasi Streamlit sebagai sesi uji.
    at = AppTestWrapper.run()

    # 3) Baseline: jumlah gelembung chat awal (sapaan agen).
    baseline = len(_chat_bubbles(at))
    print(f"[BASELINE] Gelembung chat awal: {baseline}")

    # 4) Simulasikan user mengetik prompt native st.chat_input.
    chat = at.chat_input
    assert len(chat) >= 1, "Komponen st.chat_input tidak ditemukan di UI!"
    chat[0].set_value("Uji sistem: katakan kata 'Sistem Aktif'").run()

    # 6a) Tidak boleh ada elemen error (=> tidak ada 401 UNAUTHENTICATED/network).
    assert len(at.error) == 0, f"Terdapat error di UI: {[e.value for e in at.error]}"

    # 6b) Riwayat chat harus bertambah (ada balasan sukses dari agen).
    bubbles_after = _chat_bubbles(at)
    print(f"[AFTER] Gelembung chat setelah input: {len(bubbles_after)} (baseline {baseline})")
    assert len(bubbles_after) > baseline, "Riwayat chat tidak bertambah -> agen tidak membalas!"

    # 7) Print respons (jawaban asli dari AI) - gelembung chat terakhir.
    print("\n" + "=" * 70)
    print("Jawaban asli dari AGEN (respons AI):")
    print("=" * 70)
    # Filter: skip CSS/header/footer/branding/status noise, show user+assistant bubbles.
    skip_prefixes = ("<style", "<div", "Paket:", "API:", "Connector:")
    for markdown in at.markdown:
        v = (markdown.value or "").strip()
        if not v or v.startswith(skip_prefixes):
            continue
        if v == "Halo! Saya Nexus Agent. Tuliskan tugas Anda, dan saya eksekusi otomatis.":
            continue
        print(v)
    print("=" * 70)


# ---------------------------------------------------------------------------
# Bungkus AppTest agar import dari streamlit.testing.v1 ter-clear di scope test
# (diimpor di dalam fungsi agar AppTest memuat app dengan state rapi).
# ---------------------------------------------------------------------------
class AppTestWrapper:
    @staticmethod
    def run():
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app_frontend.py", default_timeout=30)
        at.run()

        # TAHAP 6: aplikasi kini belter login (Supabase OAuth / demo fallback).
        # Di AppTest tidak dapat selesaikan OAuth Google (butuh browser),
        # jadi simulasikan user sudah login dengan seed session diirect.
        try:
            at.session_state["user_email"] = "demo@local.app"
        except Exception:
            getattr(at, "session_state")["user_email"] = "demo@local.app"
        at.run()
        if at.sidebar.radio:
            options = list(at.sidebar.radio[0].options)
            target = next((o for o in options if "Chat" in str(o)), options[0])
            at.sidebar.radio[0].set_value(target).run()
        return at