#!/bin/bash
# =============================================================================
#  TAHAP 3 - deploy_vps.sh
#  Skrip Bootstrap untuk VPS Ubuntu 24.04 LTS
#  (Hetzner / DigitalOcean / VPS lain berbasis Ubuntu 24.04)
#
#  Yang dilakukan:
#    1. Update & upgrade sistem
#    2. Install utilitas dasar (curl, git, software-properties-common)
#    3. Install Docker Engine (resmi dari repo Docker / apt.docker.com)
#    4. Install Docker Compose Plugin (versi resmi)
#    5. Start + enable service Docker
#    6. Siapkan direktori project /opt/ai_agent_saas
#
#  Cara pakai:  sudo bash deploy_vps.sh
#  (atau: chmod +x deploy_vps.sh && ./deploy_vps.sh)
# =============================================================================

# Hentikan eksekusi langsung jika ada satu perintah yang gagal
set -e

# -----------------------------------------------------------------------------
# Helper: watermark teks pembuka
# -----------------------------------------------------------------------------
print_banner() {
    echo "================================================================"
    echo "  🚀 Nexus Agent SaaS — VPS Deployment Bootstrap"
    echo "  Target : Ubuntu 24.04 LTS (x86_64)"
    echo "================================================================"
}

print_banner

# -----------------------------------------------------------------------------
# [1/5] Update & upgrade sistem operasi
# -----------------------------------------------------------------------------
echo ""
echo "[1/5] Mengupdate & meng-upgrade Ubuntu..."
sudo apt-get update
sudo apt-get upgrade -y

# -----------------------------------------------------------------------------
# [2/5] Install utilitas dasar
# -----------------------------------------------------------------------------
echo ""
echo "[2/5] Menginstall utilitas dasar (curl, git, software-properties-common)..."
sudo apt-get install -y curl git software-properties-common ca-certificates

# -----------------------------------------------------------------------------
# [3/5] Install Docker Engine (resmi dari repositori Docker)
#   Bukan versi APT bawaan Ubuntu (sering usang).
#   Memakai konfigurasi resmi dari https://get.docker.com
# -----------------------------------------------------------------------------
echo ""
echo "[3/5] Menginstall Docker Engine (dari repositori resmi Docker)..."
if command -v docker >/dev/null 2>&1; then
    echo "  ✔ Docker sudah terpasang: $(docker --version)"
else
    # Skrip resmi: menambah repo, install docker-ce, docker-ce-cli, containerd,
    # docker-buildx-plugin, dan docker-compose-plugin.
    curl -fsSL https://get.docker.com | sudo sh
    echo "  ✔ Docker Engine berhasil diinstall."
fi

# -----------------------------------------------------------------------------
# [4/5] Install Docker Compose Plugin (resmi, via repo Docker)
# -----------------------------------------------------------------------------
echo ""
echo "[4/5] Memastikan Docker Compose Plugin (resmi) telah terpasang..."
if command -v docker compose >/dev/null 2>&1; then
    echo "  ✔ Docker Compose sudah tersedia: $(docker compose version)"
else
    sudo apt-get update
    sudo apt-get install -y docker-compose-plugin
    echo "  ✔ Docker Compose Plugin berhasil diinstall."
fi

# -----------------------------------------------------------------------------
# Start & enable service Docker
# -----------------------------------------------------------------------------
echo ""
echo "  ➜ Mengaktifkan & menjalankan service Docker..."
sudo systemctl enable docker
sudo systemctl start docker
sleep 2
sudo systemctl status docker --no-pager | head -n 5

# (Opsional) Jika pengguna non-root ingin memakai docker tanpa sudo
if [ -n "${SUDO_USER:-}" ]; then
    echo ""
    echo "  ➜ Menambahkan user '${SUDO_USER}' ke grup 'docker'..."
    sudo usermod -aG docker "${SUDO_USER}"
    echo "  ℹ️  Logout & login ulang agar keanggotaan grup docker berlaku."
fi

# -----------------------------------------------------------------------------
# [5/5] Siapkan direktori project
# -----------------------------------------------------------------------------
echo ""
echo "[5/5] Membuat direktori project /opt/ai_agent_saas..."
sudo mkdir -p /opt/ai_agent_saas
sudo chown -R "${USER:-$(whoami)}" /opt/ai_agent_saas

echo ""
echo "================================================================"
echo "  ✅ Bootstrap VPS SELESAI !"
echo "================================================================"

# -----------------------------------------------------------------------------
# Instruksi lanjutan untuk user
# -----------------------------------------------------------------------------
cat <<'INSTRUCTION'

BAGIAN SELANJUTNYA - MENJALANKAN APLIKASI
-----------------------------------------
1. Clone repository project Anda ke direktori yang sudah disiapkan:

       cd /opt/ai_agent_saas
       git clone <URL_REPOSITORY_ANDA> .

2. Pastikan file .env sudah ada di folder project
   (berisi GEMINI_KEY_1, OPEN_CONNECTOR_*, dsb).

3. Build & jalankan seluruh stack (2 service: backend-agent + open-connector):

       sudo docker compose up -d --build

4. Cek status container:

       sudo docker compose ps

5. Akses aplikasi:
   - Streamlit UI (backend-agent):  http://<IP_VPS>:8000
   - OpenConnector API gateway :    http://<IP_VPS>:3000

6. Melihat log (opsional / debugging):

       sudo docker compose logs -f backend-agent

CATATAN KEAMANAN
----------------
- Pastikan port 8000 & 3000 diizinkan di firewall VPS (ufw / security group cloud).
- Jangan pernah commit file .env yang berisi secret ke repository publik.
INSTRUCTION

echo ""
echo "Skrip selesai dijalankan. Selamat deploy! 🚀"