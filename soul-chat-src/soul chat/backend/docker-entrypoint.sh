#!/bin/sh
set -e

echo "[entrypoint] waiting for postgres..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -U "${POSTGRES_USER:-soulchat}"; do
  sleep 1
done

echo "[entrypoint] running migrations..."
alembic upgrade head

echo "[entrypoint] seeding defaults..."
python manage.py seed

exec "$@"