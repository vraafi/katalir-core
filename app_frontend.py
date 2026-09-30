# app_frontend.py - TAHAP 6 (The Real SaaS)
# =============================================================
# Integrasi: Supabase Auth (OAuth Google) + Multi-Chat (New Chat)
#            + Riwayat & Billing persisten per-akun + E2E Playwright.
#
# Jalankan:
#   streamlit run app_frontend.py --server.port 8501 --server.headless true
#
# Kebutuhan .env: SUPABASE_URL, SUPABASE_KEY, dan (opsional) GEMINI keys.
# Bila SUPABASE belum dikonfigurasi, aplikasi otomatis memakai mode
# "Demo Local" (fallback) dan tombol OAuth masuk sebagai user demo.

from __future__ import annotations

import importlib
import os
import uuid

import streamlit as st
from dotenv_loader import load_repo_env

load_repo_env()

import database as db
import tools  # Tool Registry + CredentialMissingError
from google import genai
from google.genai import types

st.set_page_config(
    page_title="Nexus Agent - SaaS AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
html, body, .stApp {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
    "Inter", Roboto, system-ui, sans-serif;
}
.stApp { background-color: #f9f9fa; }
.block-container { padding-top: 2rem; }
[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #ececf0; }
[data-testid="stChatMessage"] { background: transparent; padding-bottom: 0.5rem; }
[class*="stChatInput"] { background: transparent; border-radius: 18px; }
[class*="stChatInput"] textarea {
  border-radius: 18px; border: 1px solid #e5e5ea;
  background-color: #ffffff; font-family: inherit;
}
[data-testid="stChatMessageAvatarUser"] { background: linear-gradient(135deg, #6C63FF, #3B82F6); border-radius: 50%; }
[data-testid="stChatMessageAvatarAssistant"] { background: #ececf3; border-radius: 50%; }
.brand-header { display: flex; align-items: center; gap: 12px; margin: 4px 0 8px; }
.brand-logo {
  width: 44px; height: 44px; border-radius: 14px;
  background: linear-gradient(135deg, #6C63FF, #3B82F6);
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; color: #fff; box-shadow: 0 8px 20px rgba(108,99,255,.35);
}
.brand-title { font-size: 22px; font-weight: 700; color: #1d1d1f; margin: 0; letter-spacing: -.2px; }
.brand-sub { font-size: 13px; color: #86868b; margin: 2px 0 0; }
.metric-card { background: #fff; border: 1px solid #E6E9F4; border-radius: 14px; padding: 14px 16px; }
.metric-label { font-size: 12px; color: #86868b; }
.metric-value { font-size: 22px; font-weight: 800; color: #1d1d1f; }
.decoy-note { text-align: center; font-size: 12.5px; color: #86868b; margin-top: 22px; }
.footer { text-align: center; color: #86868b; font-size: 12px; margin-top: 30px; }
.landing { text-align: center; padding: 20px 30px; border-radius: 24px; }
.landing-title { font-size: 38px; font-weight: 800; color: #1d1d1f; letter-spacing: -.5px; }
.landing-sub { font-size: 17px; color: #86868b; margin: 12px 0 30px; }
.landing-card {
  background: #ffffff;
  border: 1px solid #e6e8ee;
  border-radius: 26px;
  box-shadow: 0 12px 32px rgba(15,23,42,.08);
  padding: 40px 36px;
  text-align: center;
}
.landing-logo {
  width: 76px; height: 76px; border-radius: 22px;
  background: linear-gradient(135deg, #6C63FF, #3B82F6);
  display: flex; align-items: center; justify-content: center;
  font-size: 40px; color: #fff; margin: 0 auto 18px;
  box-shadow: 0 10px 26px rgba(108,99,255,.4);
}
.landing-h { font-size: 30px; font-weight: 760; color: #1d1d1f; letter-spacing: -.4px; margin: 6px 0; }
.landing-p { font-size: 15.5px; color: #86868b; line-height: 1.6; margin: 10px 0 26px; }
.landing-foot { font-size: 12.5px; color: #b5b5bb; margin-top: 14px; }
.google-btn {
  display: inline-flex !important; align-items: center; justify-content: center; gap: 10px;
  width: 100%;
  background: #ffffff; border: 1px solid #e0e0e0; border-radius: 14px;
  padding: 14px 24px; font-size: 16px; font-weight: 600; color: #1d1d1f;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", Roboto, system-ui, sans-serif;
  box-shadow: 0 4px 16px rgba(15,23,42,.05);
  text-decoration: none; cursor: pointer; transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
}
.google-btn:hover {
  background: #f8f9fa; box-shadow: 0 8px 24px rgba(15,23,42,.12); transform: translateY(-1px);
}
.google-btn:active { transform: translateY(0); }

/* Sidebar minimalis ala ChatGPT 2026 - tombol transparan, borderless, rata kiri */
[data-testid="stSidebar"] {
  background: #f7f7f8;
  border-right: none;
  padding: 6px 0;
}
[data-testid="stSidebar"] .stButton button[kind="secondary"],
[data-testid="stSidebar"] .stButton button[kind="primary"],
[data-testid="stSidebar"] .stButton button {
  background: transparent;
  border: none !important;
  border-radius: 8px;
  text-align: left;
  justify-content: flex-start;
  color: #1d1d1f;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", Roboto, sans-serif;
  font-weight: 500;
  padding: 8px 12px;
  box-shadow: none !important;
  transition: background .12s ease, color .12s ease;
}
[data-testid="stSidebar"] .stButton button:hover {
  background: #ececf0;
  color: #1d1d1f;
}
[data-testid="stSidebar"] .stButton button:active {
  background: #e2e2e8;
}

/* Kartu integrasi (Apple minimal) */
.integ-card {
  background: #ffffff;
  border: 1px solid #e6e8ee;
  border-radius: 18px;
  padding: 20px 22px;
  margin-bottom: 14px;
  box-shadow: 0 2px 10px rgba(15,23,42,.04);
  transition: box-shadow .12s ease, transform .12s ease;
}
.integ-card:hover { box-shadow: 0 8px 22px rgba(15,23,42,.08); transform: translateY(-1px); }
.integ-head { display: flex; align-items: center; gap: 12px; }
.integ-icon {
  width: 44px; height: 44px; border-radius: 12px;
  background: linear-gradient(135deg, #ececf3, #f5f5f7);
  display: flex; align-items: center; justify-content: center; font-size: 22px;
}
.integ-title { font-size: 16px; font-weight: 700; color: #1d1d1f; }
.integ-sub { font-size: 13px; color: #86868b; }
.integ-status-ok { color: #15803D; font-size: 13px; font-weight: 600; }
.integ-status-no { color: #b45309; font-size: 13px; }

/* Form Kredensial Kontekstual di dalam chat (Contextual Secret Injection) */
.cred-container {
  background: #ffffff;
  border: 1px solid #e6e8ee;
  border-left: 4px solid #6C63FF;
  border-radius: 16px;
  padding: 16px 18px;
  margin: 8px 0;
  box-shadow: 0 4px 16px rgba(108,99,255,.10);
}
.cred-title { font-size: 14px; font-weight: 700; color: #1d1d1f; margin-bottom: 2px; }
.cred-sub { font-size: 12.5px; color: #86868b; margin-bottom: 12px; }

/* Empty State - Layar Sambutan Chat Baru */
.welcome-wrap { text-align: center; padding: 60px 20px 20px; }
.welcome-logo {
  font-size: 64px;
  margin-bottom: 14px;
  filter: drop-shadow(0 10px 20px rgba(108,99,255,.25));
}
.welcome-title { font-size: 30px; font-weight: 760; color: #1d1d1f; letter-spacing: -.4px; }
.welcome-sub { font-size: 15px; color: #86868b; margin: 10px 0 28px; }
.welcome-suggest { margin-top: 18px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
# ---------------------------------------------------------------------------
# AUTH - Supabase AuthSession (Google) + fallback lokal
# ---------------------------------------------------------------------------
def sb_client():
    try:
        return db._get_client()
    except Exception:
        return None


def is_logged_in() -> bool:
    return bool(st.session_state.get("user_email"))


def current_email() -> str:
    return st.session_state.get("user_email", "demo@local.app")


def build_oauth_url() -> str:
    """Buat URL otorisasi Google via Supabase (tanpa memicu redirect otomatis)."""
    client = sb_client()
    if client is None:
        return ""
    try:
        res = client.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": "http://localhost:8501"},
        })
        url = getattr(res, "url", None)
        if not url and isinstance(res, dict):
            url = res.get("url") or res.get("provider_url")
        return url or ""
    except Exception as exc:
        st.warning("Gagal memuat URL OAuth. Cek SUPABASE_URL/KEY. (" + str(exc) + ")")
        return ""


def get():
    """Login via tombol 'Masuk dengan Google' (Supabase OAuth)."""
    client = sb_client()
    if client is not None:
        url = build_oauth_url()
        if url:
            st.session_state["pending_oauth_url"] = url
            st.rerun()
            return
        st.warning("Belum dapat URL otorisasi dari Supabase.")
        return
    # Fallback demo bila Supabase belum dikonfigurasi
    st.session_state["user_email"] = "demo@local.app"
    st.rerun()


def handle_auth_redirect():
    """PENANGKAP TIKET AUTH: tangkap ?code=... dari redirect Google.

    Supabase OAuth me-redirect ke localhost:8501/?code=...&next=...
    Di sini kita tukar 'code' menjadi session, simpan email, lalu
    bersihkan query param agar tak infinite-loop.
    """
    params = st.query_params
    code = params.get("code")
    if not code:
        return False

    client = sb_client()
    if client is None:
        # Tanpa Supabase tidak bisa tukar code; fallback demo.
        st.session_state["user_email"] = "demo@local.app"
    else:
        try:
            from supabase._sync.auth_client import CodeExchangeParams

            res = client.auth.exchange_code_for_session(
                CodeExchangeParams(auth_code=code)
            )
            user = res.user
            email = (user.email if user else None) or ""
            if not email:
                try:
                    email = (client.auth.get_user().user or None).email or ""
                except Exception:
                    email = ""
            st.session_state["user_email"] = email or "user@local.app"
            st.session_state["sb_session"] = True
            st.success("Login berhasil! Selamat datang, " + (email or "user") + ".")
        except Exception as exc:
            st.warning("Gagal menukar kode otorisasi. (" + str(exc) + ")")
            st.session_state["user_email"] = "demo@local.app"

    # Bersihkan query param (& code) agar tidak infinite-loop, lalu rerun
    st.query_params.clear()
    st.rerun()
    return True


def logout():
    st.session_state["user_email"] = None
    st.rerun()


def tier_label() -> str:
    user = db.get_or_create_user(current_email(), "User")
    return user.get("tier", "free")


# ---------------------------------------------------------------------------
# RUNNER AGEN (agent_engine) + fallback
# ---------------------------------------------------------------------------
# Runner Agen (Agentic Loop / Tool Calling) + fallback
# ---------------------------------------------------------------------------
def _agentic_run(prompt: str, email: str) -> str:
    """Jantung Agen: jalankan Gemini dengan tools, eksekusi alat, loop.

    Apabila alat melempar CredentialMissingError, set st.session_state
    ["missing_credential"] = error.provider_name lalu rerun -> memunculkan
    UI form kredensial kontekstual. Token TIDAK pernah dilanjutkan ke LLM.
    """
    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )
    if not api_key:
        return "API key tidak ditemukan. Periksa konfigurasi .env."
    model_id = os.getenv("AGENT_MODEL", "gemma-4-31b-it")

    SYSTEM = (
        "Anda adalah Nexus Autonomous Agent. Rencanakan & lakukan tindakan dengan "
        "alat yang tersedia. Setelah eksekusi alat, rangkum hasil untuk user secara "
        "ringkas dalam Bahasa Indonesia."
    )

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=0.1,
        system_instruction=SYSTEM,
        tools=tools.TOOL_DECLARATIONS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    chat = client.chats.create(model=model_id, config=config)

    response = chat.send_message(prompt)
    max_retries = 3
    retry = 0

    while response.function_calls:
        if retry >= max_retries:
            return "Maaf, agen gagal menyelesaikan operasi setelah beberapa percobaan."

        for call in response.function_calls:
            name = call.name
            args = dict(call.args) if call.args else {}
            print(f"[TOOL REQUEST] {name}({args})")

            # KUNCI UX: tangkap kredensial hilang -> picu form via rerun, hentikan loop.
            try:
                tool_result = tools.execute_tool(name, args, email)
                print(f"[TOOL OK] {tool_result}")
            except tools.CredentialMissingError as cred_err:
                st.session_state["missing_credential"] = cred_err.provider_name
                print(f"[CREDENTIAL MISSING] {cred_err.provider_name}")
                # loop berhenti; di Streamlit st.rerun() mengaborsi utk tampilkan form.
                # safeguard utk non-UI/Test: hentikan eksekusi di sini (hindari infinite loop).
                st.rerun()
                return f"Kredensial untuk {cred_err.provider_name} belum tersedia."
            except Exception as exc:  # noqa: BLE001
                retry += 1
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=name,
                        response={"status": "error", "message": str(exc)},
                    )
                )
                continue

            # Sukses -> beri hasil kembali ke Gemini untuk dirangkum
            response = chat.send_message(
                types.Part.from_function_response(
                    name=name,
                    response={"status": "success", "result": tool_result},
                )
            )

    return response.text.strip() if response.text else "Tugas selesai dieksekusi."


def run_agent(prompt):
    """Eksekusi agentic loop; fallback ke agent_engine bila modul lain tersedia."""
    email = current_email()
    try:
        # 1) Jalur utama: Agentic Loop (tools + credential intercept)
        content = _agentic_run(prompt, email)
        return {"content": content, "mode": "agentic"}
    except Exception as exc:  # noqa: BLE001
        # 2) Fallback: delegasi ke agent_engine bila config genai tak tersedia
        try:
            m = importlib.import_module("agent_engine")
            runner = getattr(m, "run_autonomous_agent", None)
            if callable(runner):
                result = runner(user_id=email, user_prompt=prompt)
                if st.session_state.get("missing_credential"):
                    return {"content": str(result), "mode": "agentic"}
                return {"content": str(result), "mode": "live"}
        except Exception as exc2:  # noqa: BLE001
            return {"content": "Error: " + str(exc2), "mode": "error"}
        return {"content": f"Agentic loop gagal: {exc}", "mode": "error"}
# ---------------------------------------------------------------------------
# HALAMAN LANDING (user belum login)
# ---------------------------------------------------------------------------
def render_landing():
    # Bila OAuth dibuka, redirect same-tab ke provider (Google) via meta-refresh.
    pending = st.session_state.get("pending_oauth_url")
    if pending:
        st.markdown(
            f'<meta http-equiv="refresh" content="0;url={pending}">',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="landing"><p style="color:#86868b;margin-top:40px;">Nge-redirect ke Google '
            'untuk otorisasi... klik <a href="' + pending + '">continue</a> bila rasa lama.</p></div>',
            unsafe_allow_html=True,
        )
        return

    # Bangun URL OAuth (cache agar tak hit network tiap render)
    if "oauth_url" not in st.session_state:
        st.session_state["oauth_url"] = build_oauth_url()
    oauth_url = st.session_state.get("oauth_url", "")

    # SVG logo Google resmi (berwarna)
    google_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 48 48">'
        '<path fill="#FFC107" d="M43.611 20.083H42V20H24v8h11.303C33.396 33.815 29.171 37 24 37c-7.18 0-13-5.82-13-13s5.82-13 13-13c3.318 0 6.348 1.243 8.631 3.28l5.657-5.657C35.246 5.453 30.0 3 24 3 12.956 3 4 11.956 4 23s8.956 20 20 20c11.044 0 20-8.956 20-20 0-1.007-.085-1.993-.247-2.93z"/>'
        '<path fill="#FF3D00" d="M6.306 14.691l6.571 4.819C13.99 16.177 18.196 13 24 13c3.318 0 6.348 1.243 8.631 3.28l5.657-5.657C35.246 5.453 30.0 3 24 3 17.117 3 11.028 6.126 6.306 14.691z"/>'
        '<path fill="#4CAF50" d="M24 43c5.817 0 10.977-2.046 15.031-5.412l-6.933-5.867C30.513 33.696 27.588 35 24 35c-5.021 0-9.397-3.126-11.064-7.58l-6.427 4.95C10.914 39.76 16.933 43 24 43z"/>'
        '<path fill="#1976D2" d="M43.611 20.083H42V20H24v8h11.303c-.503 1.564-1.264 2.991-2.253 4.193l6.505 5.504C40.978 33.5 44 30.031 44 24c0-1.007-.085-1.993-.247-2.93z"/>'
        '</svg>'
    )

    # Layout terpusat: sidebar kosong + kolom tengah lebar untuk login.
    _, mid, _ = st.columns([1, 1.5, 1])
    with mid:
        st.markdown(
            """
            <div class="landing-card">
              <div class="landing-logo">🤖</div>
              <div class="landing-h">Welcome to Nexus Agent</div>
              <p class="landing-p">
                Autonomous AI Agent untuk bisnis Anda — eksekusi tugas, riset, dan
                integrasi SaaS secara otomatis. Masuk dengan akun Google untuk mulai.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if oauth_url:
            # Tombol premium: <a> membungkus URL OAuth, berisi SVG Google + teks.
            st.markdown(
                '<a class="google-btn" href="' + oauth_url + '">'
                + google_svg + '<span>Continue with Google</span></a>',
                unsafe_allow_html=True,
            )
        else:
            # fallback: tombol st.button bila Supabase belum siap (mode demo)
            if st.button("Masuk dengan Google", type="primary", use_container_width=True):
                get()
        st.markdown(
            '<div class="landing-foot">Masuk = Anda menyetujui <a href="#">Term</a> &amp; '
            '<a href="#">Privacy</a>. — Nexus Agent</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# HALAMAN CHAT (multi-session, persisten via db)
# ---------------------------------------------------------------------------
# Nama tampilan provider untuk Contextual Secret Injection
INTEGRATION_NAMES = {
    "whatsapp": "WhatsApp Cloud API",
    "google_sheets": "Google Sheets",
    "gmail": "Gmail / Email Monitor",
    "nvidia": "NVIDIA API",
}


SUGGESTIONS = [
    "Kirim pesan WA",
    "Rangkum dokumen",
    "Analisis data",
]


def _send_prompt(email, session_id, text):
    """Proses satu prompt user: rename sesi baru, simpan, jalankan agen.

    Bila agentic loop butuh kredensial, set missing_credential lalu return
    False (render_chat_page yang menampilkan form + rerun).
    """
    if st.session_state.get("new_session", False):
        db.rename_session(email, session_id, text[:20])
        st.session_state["chat_title"] = text[:20]
        st.session_state["new_session"] = False

    db.add_message(email, session_id, "user", text)
    with st.chat_message("user"):
        st.write(text)
    with st.spinner("Berpikir..."):
        result = run_agent(text)

    if st.session_state.get("missing_credential"):
        return False

    db.add_message(email, session_id, "assistant", result["content"])
    with st.chat_message("assistant"):
        st.write(result["content"])
    return True


def render_chat_page():
    email = current_email()

    # Sidebar: tombol "Chat Baru" + daftar riwayat session
    with st.sidebar:
        st.markdown("### 🤖 Nexus Agent")
        if st.button("➕ Chat Baru", key="new_chat", type="primary", use_container_width=True):
            s = db.create_session(email, "Chat Baru")
            st.session_state["current_session_id"] = s["id"]
            st.session_state["chat_title"] = s["title"]
            st.session_state["new_session"] = True
            st.rerun()

        sessions = db.list_sessions(email)
        if sessions:
            st.markdown("**Riwayat Chat**")
            for s in sessions:
                label = s.get("title", "Chat")[:24]
                sid = str(s["id"])
                curr = st.session_state.get("current_session_id") == sid
                # Baris: kolom [nama-chat, popover-edit]
                c_name, c_edit = st.columns([5, 1])
                with c_name:
                    if st.button(label, key="ses_" + sid, use_container_width=True,
                                 type="secondary"):
                        st.session_state["current_session_id"] = sid
                        st.session_state["chat_title"] = label
                        st.session_state["new_session"] = False
                        st.rerun()
                with c_edit:
                    # Popover edit nama riwayat (Fit")
                    with st.popover("⚙️", help="Edit nama chat"):
                        new_name = st.text_input("Nama baru", value=label,
                                                 key="rename_in_" + sid,
                                                 label_visibility="collapsed")
                        if st.button("Simpan Nama", key="rename_btn_" + sid,
                                     use_container_width=True):
                            if new_name.strip():
                                db.rename_session(email, sid, new_name.strip())
                                if sid == st.session_state.get("current_session_id"):
                                    st.session_state["chat_title"] = new_name.strip()
                                st.rerun()
        st.divider()
        st.markdown("User: **" + email + "**")
        if st.button("Logout", key="logout"):
            logout()

    # Pilih / buat session aktif (key tunggal: current_session_id)
    if "current_session_id" not in st.session_state:
        s = db.create_session(email, "Chat Baru")
        st.session_state["current_session_id"] = s["id"]
        st.session_state["chat_title"] = s["title"]
        st.session_state["new_session"] = True
    session_id = st.session_state["current_session_id"]

    # Render riwayat pesan dari db
    messages = db.get_messages(email, session_id)

    if not messages:
        # EMPTY STATE: Layar Sambutan Chat Baru (vertikal tengah)
        st.container()
        st.markdown(
            """
            <div class="welcome-wrap">
              <div class="welcome-logo">✨</div>
              <div class="welcome-title">Halo, ada yang bisa saya bantu hari ini?</div>
              <div class="welcome-sub">Tanyakan apa saja atau pilih salah satu saran berikut:</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("💬 " + SUGGESTIONS[0], key="su0", use_container_width=True):
                st.session_state["pending_prompt"] = SUGGESTIONS[0]
                st.rerun()
        with c2:
            if st.button("📄 " + SUGGESTIONS[1], key="su1", use_container_width=True):
                st.session_state["pending_prompt"] = SUGGESTIONS[1]
                st.rerun()
        with c3:
            if st.button("📊 " + SUGGESTIONS[2], key="su2", use_container_width=True):
                st.session_state["pending_prompt"] = SUGGESTIONS[2]
                st.rerun()
        st.markdown('<div class="welcome-suggest"></div>', unsafe_allow_html=True)
    else:
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

    # --- Contextual Secret Injection: form kredensial muncul di chat bila ada pemicu ---
    missing = st.session_state.get("missing_credential")
    if missing:
        provider_key = str(missing)
        display_name = INTEGRATION_NAMES.get(provider_key, provider_key.replace("_", " ").title())

        # Hidden anchor agar dapat muncul seolah "di bawah pesan terakhir AI"
        st.container()

        st.markdown(
            f"""
            <div class="cred-container">
              <div class="cred-title">🔐 Akses Dibutuhkan: {display_name}</div>
              <div class="cred-sub">
                Agen butuh kredensial untuk melanjutkan tugas. Token hanya akan disimpan
                diamankan untuk akun Anda dan TIDAK pernah dibagikan ke dialog LLM.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form(key="cred_form_" + provider_key, clear_on_submit=True):
            token = st.text_input(
                "API Token " + display_name,
                key="cred_input_" + provider_key,
                type="password",
                placeholder="Masukkan token / app password Anda...",
            )
            submitted = st.form_submit_button("Simpan Kredensial", use_container_width=True)

        if submitted and token.strip():
            # Simpan langsung ke Supabase (BYOK) — token tak pernah masuk riwayat LLM
            db.save_integration(email, provider_key, token.strip())
            st.session_state.pop("missing_credential", None)
            st.success(f"Kredensial {display_name} disimpan. Agen melanjutkan tugasnya...")
            st.rerun()
        elif submitted:
            st.error("Token tidak boleh kosong.")

    # Tombol sugesti (dari empty state) maupun chat_input sama-sama memicu prompt
    trigger = st.session_state.pop("pending_prompt", None)
    prompt = st.chat_input("Ketik pesan ke Nexus Agent...")
    if prompt:
        _send_prompt(email, session_id, prompt)
    elif trigger:
        _send_prompt(email, session_id, trigger)
# ---------------------------------------------------------------------------
# HALAMAN LANGANGGANAN / BILLING
# ---------------------------------------------------------------------------
PLANS = [
    {"key": "free", "name": "FREE", "price": "Rp0", "desc": "50 tugas / bulan",
     "features": ["50 tugas / bulan", "1 agen aktif", "Riwayat chat 3 hari"], "pro": False},
    {"key": "pro", "name": "PRO", "price": "Rp199rb", "desc": "Akses penuh + rekomendasi AI",
     "features": ["Tugas tanpa batas", "Semua agen & tools", "Rekomendasi cerdas", "Riwayat tanpa batas"], "pro": True},
    {"key": "ultra", "name": "ULTRA", "price": "Rp999rb", "desc": "Prioritas & custom integrasi",
     "features": ["Semua fitur Pro", "Prioritas eksekusi", "Custom integrasi (API)", "SLA 99.9%"], "pro": False},
]


def render_billing_page():
    st.subheader("Langganan & Billing")
    current = tier_label()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### FREE\n**Rp0**/bulan\n- 50 tugas/bln\n- 1 agen\n- Chat 3 hari")
        if st.button("Mulai Gratis", disabled=(current == "free"), use_container_width=True):
            db.update_tier(current_email(), "free")
            st.rerun()
    with col2:
        st.markdown("### PRO\n**Rp199rb**/bulan\n\n_satu yang paling populer_\n\n- Tugas tanpa batas\n- Semua tools\n- Rekomendasi AI")
        if st.button("Upgrade ke Pro", disabled=(current == "pro"), use_container_width=True):
            db.update_tier(current_email(), "pro")
            st.rerun()
    with col3:
        st.markdown("### ULTRA\n**Rp999rb**/bulan\n\n- Semua fitur Pro\n- Prioritas\n- Custom integrasi API")
        if st.button("Upgrade ke Ultra", disabled=(current == "ultra"), use_container_width=True):
            db.update_tier(current_email(), "ultra")
            st.rerun()

    cola, colb, colc = st.columns(3)
    cola.metric("Paket Aktif", current.upper())
    cola.metric("Kuota Dronge", "Unlimited" if current != "free" else "50")
    st.caption("Tier disimpan permanen per-akun di Supabase.")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# HALAMAN INTEGRASI & API (Bring Your Own Key)
# ---------------------------------------------------------------------------
# Daftar layanan pihak ketiga yang didukung BYOK
SUPPORTED_INTEGRATIONS = [
    {"key": "whatsapp", "name": "WhatsApp Cloud API", "icon": "💬",
     "desc": "Token permanent WhatsApp Business untuk kirim pesan otomatis."},
    {"key": "google_sheets", "name": "Google Sheets", "icon": "📊",
     "desc": "API key untuk membaca & menulis data spreadsheet secara otomatis."},
    {"key": "gmail", "name": "Gmail / Email Monitor", "icon": "📧",
     "desc": "App password / API key untuk memantau & membalas email."},
    {"key": "nvidia", "name": "NVIDIA API", "icon": "🖥️",
     "desc": "API key NVIDIA untuk inferensi model & GPU cloud."},
]


def render_integrations_page():
    st.subheader("Manajemen Integrasi Pihak Ketiga")
    st.caption("Simpan API Key pribadi Anda di sini. Token disimpan aman & "
               "hanya dipakai untuk akun Anda (Bring Your Own Key).")

    email = current_email()

    # --- Kartu per layanan ---
    for integ in SUPPORTED_INTEGRATIONS:
        key = integ["key"]
        saved = db.get_integration(email, key)
        has = bool(saved and saved.get("api_token"))

        with st.container():
            status = ('<span class="integ-status-ok">● Terhubung</span>' if has
                      else '<span class="integ-status-no">● Belum terhubung</span>')
            st.markdown(
                f"""
                <div class="integ-card">
                  <div class="integ-head">
                    <div class="integ-icon">{integ['icon']}</div>
                    <div>
                      <div class="integ-title">{integ['name']}</div>
                      <div class="integ-sub">{integ['desc']}</div>
                    </div>
                  </div>
                  <div style="margin-top:10px;">{status}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Form input token (password) + simpan
            c1, c2 = st.columns([4, 1])
            with c1:
                token_val = st.text_input(
                    "API Token",
                    key="tok_" + key,
                    type="password",
                    placeholder="Paste API token / app password Anda...",
                    label_visibility="collapsed",
                    value=saved.get("api_token", "") if has else "",
                )
            with c2:
                if st.button("Simpan", key="save_" + key, use_container_width=True):
                    if token_val.strip():
                        db.save_integration(email, key, token_val.strip())
                        st.success(f"Token untuk {integ['name']} disimpan.")
                        st.rerun()
                    else:
                        st.error("Token tidak boleh kosong.")
            if has:
                if st.button("Hapus Token", key="del_" + key):
                    db.delete_integration(email, key)
                    st.info(f"Token {integ['name']} dihapus.")
                    st.rerun()
# MAIN
# ---------------------------------------------------------------------------
def main():
    # Penangkap tiket auth: tangkap ?code=... dari redirect Google OAuth.
    # Wajib di paling awal sebelum cek login, untuk menukar code -> session.
    handle_auth_redirect()

    if not is_logged_in():
        render_landing()
        return

    st.sidebar.markdown("Navigasi")
    page = st.sidebar.radio("Menu",
        ["💬 Chat AI", "🔌 Integrasi & API", "Langganan & Billing"],
        label_visibility="collapsed")
    if "Chat" in page:
        render_chat_page()
    elif "Integrasi" in page:
        render_integrations_page()
    else:
        render_billing_page()

    st.markdown('<div class="footer">Nexus Agent - SaaS 2026</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()