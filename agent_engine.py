import os
import logging
from typing import Optional

# Paksa muat file .env yang ada di folder proyek ke memori OS
# (agar API key dari GEMINI_KEY_1/GEMINI_API_KEY/GOOGLE_API_KEY terbaca)
from dotenv_loader import load_repo_env
load_repo_env()

from google import genai
from google.genai import types

# Impor Modul 1 & 2 yang telah dibuat sebelumnya
from auth_gateway import OpenConnectorGateway, UserSessionError, GatewayConnectionError
from tool_schemas import validate_tool_payload

# Konfigurasi Logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("AgentEngine")

# ---------------------------------------------------------
# KONFIGURASI GATEWAY & MODEL
# ---------------------------------------------------------
GATEWAY_URL = os.getenv("OPEN_CONNECTOR_URL", "https://api.open-connector.local")
GATEWAY_ADMIN_TOKEN = os.getenv("OPEN_CONNECTOR_ADMIN_TOKEN", "INTERNAL_MASTER_KEY")
MODEL_ID = "gemma-4-31b-it"  # Menggunakan target model instruksi

# Inisialisasi Gateway Client
gateway = OpenConnectorGateway(base_url=GATEWAY_URL, admin_token=GATEWAY_ADMIN_TOKEN)

# ---------------------------------------------------------
# DEKLARASI TOOL (SCHEMA UNTUK GEMMA)
# ---------------------------------------------------------
# Deklarasi fungsi append_row agar model memahami kapabilitas alat
append_row_declaration = types.FunctionDeclaration(
    name="append_row",
    description="Menambahkan satu baris data baru ke Google Sheets.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "spreadsheet_id": types.Schema(
                type=types.Type.STRING,
                description="ID unik spreadsheet dari URL Google Sheets."
            ),
            "sheet_name": types.Schema(
                type=types.Type.STRING,
                description="Nama tab lembar kerja. Default: 'Sheet1'."
            ),
            "row_values": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Daftar nilai elemen untuk baris baru (contoh: ['Barang A', '100', 'Lunas'])."
            ),
        },
        required=["spreadsheet_id", "row_values"]
    )
)

# BUG FIX 2026-10-03 (create_spreadsheet): hanya `append_row` yang dideklarasikan,
# dan `append_row` WAJIB punya `spreadsheet_id`. Akibatnya model tidak pernah bisa
# membuat spreadsheet sendiri - satu-satunya jalan adalah meminta user membuat
# manual lalu menyalin ID. Tool ini menutup jalur itu.
create_spreadsheet_declaration = types.FunctionDeclaration(
    name="create_spreadsheet",
    description=(
        "Membuat Google Spreadsheet BARU. Gunakan tool ini saat user meminta "
        "dibuatkan spreadsheet/lembar kerja/tab baru dan belum ada "
        "`spreadsheet_id`. Jangan pernah meminta user membuat spreadsheet manual."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(
                type=types.Type.STRING,
                description="Judul spreadsheet baru, misal 'Laporan Verdi'.",
            ),
            "sheet_name": types.Schema(
                type=types.Type.STRING,
                description="Nama tab pertama. Default 'Sheet1'.",
            ),
            "sheet_names": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Nama tab tambahan (opsional), misal ['inventory'].",
            ),
        },
        required=["title"],
    )
)

AGENT_TOOLS = [
    types.Tool(function_declarations=[
        create_spreadsheet_declaration,
        append_row_declaration,
    ])
]

SYSTEM_INSTRUCTION = """
Anda adalah Autonomous Multi-SaaS Agent Engine tingkat lanjut.
Tugas Anda: Memproses instruksi pengguna, merencanakan tindakan, dan mengeksekusi tool yang relevan secara akurat.
Aturan:
1. Patuhi tipe data dan parameter wajib secara ketat saat memanggil fungsi.
2. Jika menerima feedback kesalahan dari fungsi/sistem validasi, analisa akar permasalahannya, perbaiki nilai parameter, dan panggil kembali fungsi tersebut.
3. Selalu berikan respon akhir yang jelas dan ringkas setelah tugas berhasil diselesaikan.
4. KAMU BISA membuat Google Spreadsheet baru. Gunakan tool `create_spreadsheet`
   dengan parameter `title` (dan opsional `sheet_name` / `sheet_names`) saat
   user meminta spreadsheet, lembar kerja, atau tab baru. JANGAN pernah meminta
   user membuat spreadsheet manual atau mencari `spreadsheet_id` sendiri.
5. Gunakan `append_row` HANYA setelah spreadsheet sudah ada (butuh
   `spreadsheet_id`).
"""

def run_autonomous_agent(user_id: str, user_prompt: str) -> str:
    """
    Eksekusi loop otonom terisolasi per-user dengan mekanisme retry & self-correction.
    """
    print(f"\n{'='*60}\n[MEMULAI MISI AGEN] User: {user_id} | Prompt: '{user_prompt}'\n{'='*60}")
    
    # Inisialisasi Client SDK resmi Google GenAI
    # Deteksi API Key secara cerdas dari beberapa kemungkinan nama variabel
    # environment yang ada di sistem / file .env.
    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )

    if not api_key:
        raise ValueError(
            "API Key Google AI Studio tidak ditemukan di environment variables (.env)!"
        )

    client = genai.Client(api_key=api_key)
    
    # Konfigurasi Chat Session
    config = types.GenerateContentConfig(
        temperature=0.1,  # Strict / Zero-Hallucination
        system_instruction=SYSTEM_INSTRUCTION,
        tools=AGENT_TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)  # Manual loop control
    )
    
    chat = client.chats.create(model=MODEL_ID, config=config)
    
    print("[AGEN BERPIKIR] Memproses instruksi awal...")
    response = chat.send_message(user_prompt)
    
    max_retries = 3
    retry_count = 0
    
    # Autonomous Execution & Self-Correction Loop
    while response.function_calls:
        if retry_count >= max_retries:
            print(f"[BATAS RETRY TERCAPAI] Gagal menyelesaikan tugas setelah {max_retries} perbaikan.")
            return f"Maaf, agen gagal mengeksekusi operasi setelah {max_retries} kali percobaan perbaikan mandiri."

        for call in response.function_calls:
            action_name = call.name
            raw_args = dict(call.args) if call.args else {}
            print(f"\n[TOOL REQUEST DITERIMA] Memanggil: '{action_name}' dengan parameter: {raw_args}")
            
            # -------------------------------------------------------------
            # FASE 1: VALIDASI PYDANTIC SCHEMA
            # -------------------------------------------------------------
            try:
                validated_payload = validate_tool_payload(action_name, raw_args)
                print("[VALIDASI LOLOS] Payload tervalidasi terhadap skema Pydantic.")
            except ValueError as val_err:
                retry_count += 1
                error_msg = str(val_err)
                print(f"[VALIDASI GAGAL - RETRYING {retry_count}/{max_retries}]")
                print(f"Detail: {error_msg}")
                
                # Feedback error ke AI untuk koreksi mandiri
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=action_name,
                        response={"status": "error", "message": error_msg}
                    )
                )
                continue  # Ulangi loop dengan respons baru dari model
            
            # -------------------------------------------------------------
            # FASE 2 & 3: EKSEKUSI GATEWAY & ERROR HANDLING
            # -------------------------------------------------------------
            try:
                print(f"[EKSEKUSI GATEWAY] Mengirim aksi ke open-connector untuk user '{user_id}'...")
                
                # Eksekusi aksi melalui OpenConnector (target: google_sheets)
                result = gateway.execute_action(
                    user_id=user_id,
                    app_name="google_sheets",
                    action_name=action_name,
                    payload=validated_payload
                )
                
                print(f"[EKSEKUSI SUKSES] Hasil gateway: {result}")
                
                # Kembalikan hasil sukses ke AI
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=action_name,
                        response={"status": "success", "result": result}
                    )
                )
                # Reset counter retry jika berhasil
                retry_count = 0
                
            except UserSessionError as session_err:
                # Kesalahan otorisasi kritis: token expired / belum login. Loop dihentikan seketika.
                print(f"[SESI KRITIS] {session_err}")
                return (
                    f"Akses ditolak: Sesi otorisasi aplikasi Anda telah kedaluwarsa atau belum terhubung. "
                    f"Silakan lakukan login ulang melalui portal Open-Connector."
                )
                
            except GatewayConnectionError as gw_err:
                retry_count += 1
                error_feedback = f"Gateway execution failed: {str(gw_err)}. Periksa parameter Anda."
                print(f"[GATEWAY ERROR - RETRYING {retry_count}/{max_retries}]: {gw_err}")
                
                # Umpan balik error jaringan/API eksternal ke model
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=action_name,
                        response={"status": "error", "message": error_feedback}
                    )
                )
    
    print("\n[AGEN SELESAI] Tugas selesai dieksekusi.")
    return response.text if response.text else "Tugas selesai dieksekusi tanpa pesan teks tambahan."

# ---------------------------------------------------------
# ENTRY POINT SIMULASI
# ---------------------------------------------------------
if __name__ == "__main__":
    # Setup mock user environment
    TEST_USER_ID = "usr_prod_9921"
    TEST_PROMPT = (
        "Tolong tambahkan data penjualan ini ke Google Sheet dengan ID 'sheet_xyz123': "
        "Produk: 'Laptop Pro', Harga: '15000000', Status: 'Lunas'."
    )
    
    try:
        final_output = run_autonomous_agent(user_id=TEST_USER_ID, user_prompt=TEST_PROMPT)
        print("\n=== RESPON AKHIR AGEN ===")
        print(final_output)
    except Exception as e:
        logger.exception(f"Fatal unhandled exception: {e}")