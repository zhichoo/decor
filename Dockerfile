FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    HOST=0.0.0.0 \
    PORT=4189 \
    STATIC_ROOT=/app/web \
    TRANSCRIPT_SETTINGS_PATH=/app/.runtime/transcription-settings.local.json \
    FFMPEG_BINARY=/usr/bin/ffmpeg

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r backend/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg xvfb xauth tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 decor \
    && mkdir -p /app/.runtime /app/backend/.browser-profile \
    && chown -R decor:decor /app /opt/playwright

COPY --chown=decor:decor backend/*.py /app/backend/
COPY --chown=decor:decor scripts/init_db.py scripts/migrate_transcript_jobs.py scripts/migrate_claim_context.py scripts/setup_local_asr.py /app/scripts/
COPY --chown=decor:decor db/schema.sql /app/db/schema.sql
COPY --chown=decor:decor web/ /app/web/
COPY --chown=decor:decor docker/entrypoint.py /app/docker/entrypoint.py

USER decor
EXPOSE 4189
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4189/api/health', timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/app/docker/entrypoint.py"]
