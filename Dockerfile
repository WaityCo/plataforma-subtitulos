# Imagen de la plataforma: API FastAPI, motor de subtítulos y frontend estático en un solo proceso.
FROM python:3.12-slim

# ffmpeg de Debian trae libass, que el filtro ass necesita para quemar los subtítulos.
# libass usa fontconfig para resolver fuentes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios. Solo escribe en /app/data y en la caché de modelos.
RUN useradd --create-home --uid 1000 app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r requirements.txt -r backend/requirements.txt

# Precarga del modelo de Whisper en la imagen. Con --build-arg PRELOAD_WHISPER=0 no se descarga nada.
# WHISPER_MODEL no lo lee la app: solo elige el modelo que se precarga. Cada job sigue usando el
# model_size de su formulario (por defecto small).
ARG WHISPER_MODEL=small
ARG PRELOAD_WHISPER=1
RUN mkdir -p "$HF_HOME" \
    && if [ "$PRELOAD_WHISPER" = "1" ]; then \
         python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8')"; \
       fi \
    && chown -R app:app "$HF_HOME"

COPY engine/ ./engine/
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY presets/ ./presets/
COPY assets/ ./assets/

# Jobs, base SQLite y salidas. Con un volumen de host, ./data debe ser escribible por el uid 1000.
RUN mkdir -p /app/data && chown app:app /app/data
VOLUME /app/data

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/presets', timeout=4)"]

# Un solo proceso: el worker de la cola SQLite vive dentro del proceso. No añadas --workers.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
