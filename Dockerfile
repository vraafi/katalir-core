# ============================================================
#  TAHAP 1 - Dockerfile untuk Backend Python (AI Agent Otonom)
#  Base image: Python 3.11 slim (ringan & aman untuk VPS)
# ============================================================
FROM python:3.11-slim

# Hindari cache bytecode & buffer output (log langsung muncul di docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Working directory di dalam container
WORKDIR /app

# -- Tahap install dependency sistem yang dibutuhkan modul Python --
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Salin requirements dan install library Python terlebih dahulu
# (dipisah agar cache layer BuildKit efisien saat requirements berubah)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode backend
COPY . .

# Pastikan direktori data tersedia untuk state runtime
RUN mkdir -p /app/data

# Port yang diekspos (harus sama dengan mapping port di docker-compose.yml)
EXPOSE 8000

# Entrypoint: jalankan Streamlit UI (app_frontend.py)
# --server.address=0.0.0.0 => bisa diakses dari luar container
CMD ["streamlit", "run", "app_frontend.py", "--server.port=8000", "--server.address=0.0.0.0", "--server.headless=true"]