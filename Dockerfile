FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=False DATABASE_PATH=/data/db.sqlite3 MEDIA_ROOT=/data/media CACHE_DIR=/data/cache BACKUP_DIR=/backups

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build CONFIG_ENCRYPTION_KEY=build python manage.py collectstatic --no-input \
    && useradd --uid 1000 --create-home app && mkdir -p /data /backups && chown app /data /backups
USER app

VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --no-input && gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 2 --threads 2 --access-logfile -"]
