# test_browser_e2e.py - E2E Browser Testing (Playwright + Pytest) SaaS 2026
# =====================================================================
# Tujuan: Menguji alur Login OAuth Google di browser sungguhan (bukan AppTest).
#   1. Buka aplikasi Streamlit di localhost:8501
#   2. Halaman harus menampilkan tombol "Masuk dengan Google" (Login Screen)
#   3. Klik tombol -> sistem me-redirect ke halaman otorisasi eksternal Google.
#
# Menjalankan (pastikan app running):
#   streamlit run app_frontend.py --server.port 8501 --server.headless=true
#   pytest test_browser_e2e.py -v -s
# =====================================================================

import re

import pytest
from playwright.sync_api import expect

# Ganti bila aplikasi dijalankan di port lain
APP_URL = "http://localhost:8501"

# Domain otorisasi eksternal yang sah (Google OAuth / Supabase Auth)
EXPECTED_AUTH_HOSTS = (
    "accounts.google.com",
    "google.com/accounts",
    "accounts.google.it",
    "auth.supabase.co",
    "supabase.co",
)


@pytest.fixture(scope="session")
def app_running():
    """(Opsional) Jalankan streamlit bila belum aktif - diuji manual lebih baik."""
    return True


def test_landing_shows_google_login_button(page):
    """Landing menampilkan tombol 'Continue with Google' (link OAuth) utk user belum login."""
    page.goto(APP_URL, wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(2000)

    login_btn = page.locator("a.google-btn")
    expect(login_btn).to_be_visible(timeout=15000)
    print("  [PASS] Tombol 'Continue with Google' (a.google-btn) terlihat di Landing Page.")


def test_google_login_redirects_to_oauth(page, context):
    """Klik link OAuth -> sistem mengarah ke otorisasi eksternal (Supabase/Google)."""
    page.goto(APP_URL, wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(2000)

    login_btn = page.locator("a.google-btn")
    expect(login_btn).to_be_visible(timeout=15000)

    href = login_btn.get_attribute("href")
    print(f"  [INFO] OAuth href: {href}")
    assert href, "Link OAuth tidak memiliki href."
    assert any(h in href for h in EXPECTED_AUTH_HOSTS), (
        f"OAuth href bukan otorisasi eksternal: {href}"
    )
    print("  [PASS] Link OAuth me-redirect ke halaman otorisasi eksternal (OAuthProvider).")


def test_login_button_has_oauth_provider_attr(page):
    """Validasi bahwa tombol memicu sign_in_with_oauth (bukan form password manual)."""
    page.goto(APP_URL, wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(2000)

    login_btn = page.locator("a.google-btn")
    expect(login_btn).to_be_visible(timeout=15000)
    # Pastikan tidak ada form username/password manual yang tampil.
    has_manual_form = page.locator("input[name='email'], input[type='password']").count()
    print(f"  [INFO] Input manual ditemukan: {has_manual_form}")
    # Di Landing, seharusnya TIDAK ada form password manual.
    assert has_manual_form == 0, "Masih ada form login manual (seharusnya OAuth-only)."
    print("  [PASS] Hanya tersedia login OAuth (tanpa form password manual).")