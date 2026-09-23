# Deploy

## 1. Telegram tomonini tayyorlash

1. **Bot yarating** — [@BotFather](https://t.me/BotFather) → `/newbot`. Token'ni
   `BOT_TOKEN` ga yozing.
2. **Forum super guruh** yarating → Group → Edit → **Topics: ON**.
   Guruh ID'sini oling (masalan [@RawDataBot](https://t.me/RawDataBot) yordamida,
   `-100…` bilan boshlanadi) → `FORUM_CHAT_ID`.
3. **Kanal** yarating → `CHANNEL_ID`.
4. Botni **ikkalasiga ham admin** qilib qo'shing. Kerakli huquqlar:
   - Guruhda: `Manage Topics`, `Delete Messages`, `Restrict Members`,
     `Invite Users`, `Pin Messages`, `Manage Chat`
   - Kanalda: `Post Messages`, `Delete Messages`
5. Guruhga kirish uchun havola va kanal havolasini foydalanuvchilarga bering
   (obuna majburiy — TZ 5).

## 2. Server (Ubuntu 22.04+)

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
git clone https://github.com/usmanov18/Soul-chat.git && cd Soul-chat

cp backend/.env.example backend/.env
nano backend/.env            # SECRET_KEY, BOT_TOKEN, FORUM_CHAT_ID, CHANNEL_ID
```

`SECRET_KEY` ni generatsiya qilish:

```bash
openssl rand -hex 32
```

## 3. Ishga tushirish

```bash
docker compose up -d --build
docker compose ps
```

Xizmatlar:

| Konteyner | Vazifa |
|---|---|
| `postgres` | PostgreSQL 16 |
| `redis` | cache, rate limit, celery broker |
| `backend` | FastAPI (nginx orqali 80-portda) |
| `bot` | aiogram polling |
| `worker` | celery worker |
| `beat` | celery beat (96 soat timer, jadval, snapshot, backup) |
| `frontend` | Next.js admin panel |
| `nginx` | reverse proxy (`/api` → backend, `/` → panel) |
| `prometheus` / `grafana` | monitoring (`:9090` / `:3001`) |

## 4. Birinchi super admin

Botga `/start` bosgan foydalanuvchini super admin qilish:

```bash
docker compose exec backend python manage.py superadmin 123456789
```

Admin panel logini: `username` = Telegram username, parol = `<username>:<SECRET_KEY>`.
(Production'da bu bootstrap parolini o'zgartiring yoki `app/api/v1/auth.py` dagi
`_bootstrap_hash` ni haqiqiy credential store bilan almashtiring.)

## 5. Guruhni qulflash

Relay ishlashi uchun guruh read-only bo'lishi kerak:

```bash
docker compose exec backend python manage.py lockdown
```

Bu `setChatPermissions` orqali barcha yozish huquqlarini o'chiradi. Yangi a'zolar
kelganda bot ularni ham avtomatik cheklaydi.

## 6. Webhook (ixtiyoriy)

Polling o'rniga webhook ishlatish uchun:

```ini
BOT_USE_POLLING=false
BOT_WEBHOOK_URL=https://example.com
BOT_WEBHOOK_SECRET=<openssl rand -hex 24>
```

va `bot` konteynerining buyrug'ini o'zgartiring:

```yaml
command: ["python", "-c", "import asyncio; from app.bot.setup import run_webhook; asyncio.run(run_webhook())"]
```

## 7. TLS

Production uchun nginx oldiga Let's Encrypt qo'shing:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com -d admin.example.com
```

## 8. Zaxira nusxa

```bash
docker compose exec backend python manage.py backup     # hozir
```

Har kuni soat 02:00 UTC da `daily_backup` celery vazifasi avtomatik ishlaydi.
`BACKUP_TARGET=s3` yoki `gdrive` bo'lsa, `app/services/storage.py` adapterlari
ishlatiladi (`S3_BUCKET`, `GDRIVE_TOKEN` muhit o'zgaruvchilari).

## 9. Foydali buyruqlar

```bash
docker compose logs -f bot                     # bot loglari
docker compose exec backend python manage.py schema      # jadvallar
docker compose exec backend python manage.py snapshot    # analitika snapshot
docker compose exec backend alembic upgrade head         # migratsiya
docker compose exec backend pytest -q                    # testlar
docker compose exec postgres psql -U soulchat -c '\dt'   # jadvallar ro'yxati
```

## 10. Mahalliy ishlab chiqish (Docker'siz)

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py initdb && python manage.py seed
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/docs
pytest -q

cd ../frontend && npm install && npm run dev     # http://localhost:3000
```

SQLite va Redis'siz (xotira cache) ishlaydi — `DATABASE_URL` va
`REDIS_ENABLED=false` buni avtomatik ta'minlaydi.