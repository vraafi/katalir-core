# ============================================================
#  Dockerfile - Backend API (uvicorn) para deploy Docker (VPS/Cloud)
#  Railway usa Nixpacks (railway.json) por defecto; este Dockerfile
#  está disponible para plataformas Docker-first.
# ============================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias del sistema (mínimas)
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements primero (cache eficiente en builds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código backend
COPY api_server.py database.py tools.py agent_engine.py tool_schemas.py auth_gateway.py ./
RUN mkdir -p /app/data

# Puerto dinámico: plataformas inyectan $PORT.
EXPOSE 8000

# Entrypoint: backend API FastAPI (uvicorn), port dinámico $PORT (default 8000).
CMD ["sh", "-c", "uvicorn api_server:app --host 0.0.0.0 --port ${PORT:-8000}"]