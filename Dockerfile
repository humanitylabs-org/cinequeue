FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CINEQUEUE_DATA=/data CINEQUEUE_BASE_PATH="" CINEQUEUE_HOST=0.0.0.0 CINEQUEUE_PORT=8765 CINEQUEUE_ADMIT=disabled CINEQUEUE_WATCH_REGION="" CINEQUEUE_TIMEZONE=UTC
WORKDIR /app
COPY cinequeue/__init__.py cinequeue/__main__.py cinequeue/core.py cinequeue/server.py cinequeue/mcp_api.py cinequeue/watch_providers.py cinequeue/enrich.py cinequeue/imdb_ratings.py ./cinequeue/
COPY web/index.html web/app.js web/styles.css web/pwa-install.js web/manifest.json web/icon.svg web/icon-512.png web/apple-touch-icon.png ./web/
COPY start.py openapi.json LICENSE ./
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=2)"
CMD ["python", "/app/start.py"]
