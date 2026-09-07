import httpx
import logging
from typing import Any, Dict, Optional

# Konfigurasi Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuthGateway")

class GatewayConnectionError(Exception):
    """Exception khusus untuk kegagalan koneksi ke Open-Connector gateway."""
    pass

class UserSessionError(Exception):
    """Exception khusus untuk sesi user yang tidak valid atau expired."""
    pass

class OpenConnectorGateway:
    """
    Gateway Bridge untuk berinteraksi dengan oomol-lab/open-connector.
    Bertugas mengelola otorisasi terdesentralisasi per-pengguna.
    """

    def __init__(self, base_url: str, admin_token: str):
        """
        Args:
            base_url: URL endpoint dari server open-connector.
            admin_token: Master token untuk otorisasi akses internal gateway.
        """
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"
        }

    def get_user_connection(self, user_id: str, app_name: str) -> Dict[str, Any]:
        """
        Memverifikasi apakah user memiliki koneksi aktif ke aplikasi tertentu.
        
        Args:
            user_id: ID unik pengguna di sistem kita.
            app_name: Nama SaaS (contoh: 'google-sheets', 'slack').
            
        Returns:
            Dict berisi metadata koneksi (tanpa mengekspos raw OAuth token).
        """
        endpoint = f"{self.base_url}/connections/{user_id}/{app_name}"
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(endpoint, headers=self.headers)
                
                if response.status_code == 404:
                    raise UserSessionError(f"Koneksi {app_name} untuk user {user_id} tidak ditemukan.")
                
                response.raise_for_status()
                data = response.json()
                
                # Validasi status koneksi dari payload gateway
                if not data.get("is_active", False):
                    raise UserSessionError(f"Sesi OAuth untuk {app_name} telah kedaluwarsa. Perlu re-autentikasi.")
                
                logger.info(f"Koneksi diverifikasi untuk User: {user_id} -> App: {app_name}")
                return data

        except httpx.HTTPError as exc:
            logger.error(f"HTTP error saat verifikasi koneksi: {exc}")
            raise GatewayConnectionError(f"Gagal menghubungi Open-Connector: {str(exc)}")

    def execute_action(self, user_id: str, app_name: str, action_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mengirimkan perintah eksekusi ke SaaS melalui gateway menggunakan konteks user.
        
        Args:
            user_id: ID unik pengguna.
            app_name: Nama aplikasi target.
            action_name: Nama fungsi/action yang dipanggil (misal: 'append_row').
            payload: Argumen fungsi yang dihasilkan oleh AI (telah divalidasi Pydantic).
            
        Returns:
            Respons hasil eksekusi dari API pihak ketiga.
        """
        endpoint = f"{self.base_url}/execute/{app_name}/{action_name}"
        
        # Injeksi user_id ke dalam header untuk identifikasi konteks token di sisi gateway
        execution_headers = {
            **self.headers,
            "X-User-ID": user_id
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                logger.info(f"Mengeksekusi {action_name} pada {app_name} untuk user {user_id}")
                
                response = client.post(
                    endpoint, 
                    headers=execution_headers, 
                    json=payload
                )
                
                # Jika 401/403, berarti token user di gateway sudah tidak valid
                if response.status_code in [401, 403]:
                    raise UserSessionError(f"Otorisasi {app_name} gagal. Token kemungkinan dicabut atau expired.")
                
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.json().get("detail", str(exc))
            logger.error(f"Execution Error [{app_name}]: {error_detail}")
            raise GatewayConnectionError(f"SaaS API Error: {error_detail}")
            
        except httpx.RequestError as exc:
            logger.error(f"Network Error: {exc}")
            raise GatewayConnectionError("Gagal terhubung ke infrastruktur gateway.")

# Contoh penggunaan (Mocking)
if __name__ == "__main__":
    # Inisialisasi gateway (URL & Token harus dari environment variable di produksi)
    gateway = OpenConnectorGateway(
        base_url="https://api.open-connector.local", 
        admin_token="INTERNAL_MASTER_KEY"
    )
    
    # Contoh pemanggilan (akan error karena URL mock tidak aktif)
    try:
        status = gateway.get_user_connection("user_123", "google_sheets")
        print(status)
    except Exception as e:
        print(f"Handled Error: {e}")