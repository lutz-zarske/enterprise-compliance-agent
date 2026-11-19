# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Enterprise Compliance Agent - Backend (FastAPI)
# Schlankes Single-Stage-Image auf Basis von python:3.12-slim, Non-Root, Healthcheck.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

# Abhängigkeiten zuerst -> maximale Layer-Cache-Ausnutzung.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Unprivilegierter Benutzer; data/ wird als Volume gemountet.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /srv/app/data/uploads \
    && chown -R appuser:appuser /srv/app
USER appuser

# Container spricht per Default den Ollama-Dienst auf dem Host an.
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    DATABASE_URL=sqlite:///data/agent.db \
    UPLOAD_DIR=data/uploads \
    RUNNING_IN_CONTAINER=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json,urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4); d=json.loads(r.read().decode()); sys.exit(0 if r.status == 200 and d.get('database', {}).get('status') == 'ok' else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
