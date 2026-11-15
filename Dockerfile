FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Base de l'application : téléchargée pendant la construction de l'image, depuis une
# « release » GitHub du dépôt (le fichier n'est pas dans Git : 180 Mo environ).
# Pour publier une nouvelle version des données : nouvelle release (data-v2, ...) puis
# changer FIREFORCE_DB_URL ici ou dans les réglages de l'hébergeur.
# Cette étape est placée avant le code : modifier le code ne retélécharge pas la base.
ARG FIREFORCE_DB_URL=https://github.com/BEYOND-LIMIT-TEAM/fire-force/releases/download/data-v1/fireforce.duckdb
COPY deploy/fetch_db.py /tmp/fetch_db.py
RUN python /tmp/fetch_db.py "$FIREFORCE_DB_URL" /data/fireforce.duckdb

COPY backend/app ./backend/app
COPY frontend ./frontend
ENV FIREFORCE_DB=/data/fireforce.duckdb FIREFORCE_FRONT=/app/frontend PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/api/health')"
# L'hébergeur (Render, etc.) fournit le port dans $PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
