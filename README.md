# SoulChat AI — Telegram Private Topic Manager

Bitta Telegram super guruh ichida **ikki kishilik shaxsiy suhbatlar**: har bir
suhbat alohida Topic, faqat kod bilan yuritiladi (`A-0001`, `M-1002`), hamma o'qiy
oladi — yoza faqat egasi va sherigi. Butun boshqaruv bitta bot orqali.

```
✨ Yangi suhbat boshlandi          🌸
🔖 A-0028                          A-041
👤 Akbar                           Akbar ❤️ Salima
👤 Salima                          Bugun ilk uchrashuv
🕒 18:32                           📍 Toshkent
                                   🕒 19:00
```

## Nima uchun bu loyiha oddiy forum bot emas

Telegram Bot API'da **topic-miqyosidagi ruxsat yo'q**: `ChatPermissions` guruh
miqyosida ishlaydi, yopiq topicda esa faqat adminlar yoza oladi. Ya'ni "topic
A-001 da faqat X va Y yoza oladi" deb aytishning to'g'ridan-to'g'ri usuli yo'q.

Shu sababli platforma **Relay arxitekturasi**da qurilgan: guruh to'liq read-only
qilinadi, egasi va sherigi xabarni botga yozadi, bot uni tekshirib topicga
uzatadi. Tafsilot va MTProto nega rad etilgani:
**[`docs/01-texnik-tahlil.md`](docs/01-texnik-tahlil.md)**.

## Imkoniyatlar

- **Topic kodlari** — sequential / gender / random sxema, admin panel o'zgartiradi
- **Sherik taklifi** — bir martalik havola, maksimal 2 yozuvchi
- **Relay chat** — text, photo, video, voice, document, audio, sticker, location
- **Event tizimi** — date, reminder, checklist, deadline, location
- **Kanal sinxron** — har yangi topic va har media estetik post bilan kanalga
- **Ikki tomonlama yopish** — 6 xonali kod, ikkalasi ham tasdiqlashi kerak
- **96 soatlik oyna** — `delete_pending` → `/restore` yoki avtomatik o'chirish
- **Arxiv** — JSON + HTML + TXT + PDF bitta ZIP'da, ikkala ishtirokchiga
- **Jadval** — "har kuni 20:00–22:00 da ochilsin"
- **Xavfsizlik** — rate limit, flood control, captcha, blacklist, warn → ban
- **AI moderatsiya** — spam, haqorat, toxic, 18+, risk score, summary, emotion
- **Analitika** — 20+ metrika, kunlik/haftalik/oylik, top users, soatlik faollik
- **Admin panel** — Next.js + Tailwind + Chart.js, glass UI, dark mode, 10 sahifa
  (dashboard, suhbatlar, foydalanuvchilar, media, eventlar, galereya, obunalar,
  audit log, zaxira, sozlamalar)
- **Operator amallari** — panelda warn/mute/ban/unban, backup verify+download,
  CSV/JSON export, light/dark mavzu
- **AI buyruqlari** — `/summary`, `/timeline`, `/suggest`, `/remember`/`/memory`
- **Xavfsizlik** — REST API rate limit (per-IP), fake-account skor, birthday sweep
- **Mahsulot g'oyalari (D-block)** — `/timer` o'z-o'zini yo'q qilish, ovoz transkripsiyasi arxivda,
  `/appeal` apellyatsiya oqimi (panel qarori bilan), QR taklif, ochiq statistika `/stats/public`,
  sherik almashtirish oqimi
- **Monitoring** — Prometheus `/metrics`, Grafana dashboard, Sentry, audit log
- **Testlar** — backend 396 (pytest, SQLite + PostgreSQL), admin panel 67 (vitest)

## Texnologiyalar

| Qatlam | Texnologiya |
|---|---|
| Backend | Python 3.13, FastAPI, Aiogram 3, SQLAlchemy 2 (async), Alembic |
| Ma'lumot | PostgreSQL 16, Redis 7 |
| Fon | Celery (worker + beat) |
| Frontend | Next.js 15, React 19, TailwindCSS, Chart.js |
| Monitoring | Prometheus, Grafana, Sentry |
| Deploy | Docker Compose, Nginx, GitHub Actions |

## Tez boshlash

```bash
cp backend/.env.example backend/.env   # token va ID larni to'ldiring
docker compose up -d --build
docker compose exec backend python manage.py superadmin <telegram_id>
docker compose exec backend python manage.py lockdown
```

Batafsil: **[`docs/04-deploy.md`](docs/04-deploy.md)**.

Docker'siz mahalliy ishlab chiqish (SQLite + xotira cache):

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py initdb && python manage.py seed
uvicorn app.main:app --reload --port 8000   # /docs
pytest -q                                   # 396 test
```

## Bot buyruqlari

| Buyruq | Vazifa |
|---|---|
| `/new` | Yangi suhbat yaratish |
| `/invite` | Sherik taklif qilish |
| `/status` | Suhbat holati |
| `/close` | Yopish (kod chiqaradi) |
| `/confirm <kod>` | Yopishni tasdiqlash |
| `/restore` | 96 soat ichida tiklash |
| `/archive` | Arxivni yuklab olish |
| `/event <nom> \| <sana> \| <joy>` | Hodisa yaratish |
| `/schedule 1,3,5 20:00 22:00` | Yozish oynasi |
| `/stats`, `/search`, `/moderate`, `/settings` | Moderator+ |

Xabar yozish uchun buyruq kerak emas — shunchaki botga yozing.

## Loyiha tuzilishi

```
backend/
  app/
    core/          config, db, cache, security, logging, timeutil
    models/        24 ORM jadval
    services/      biznes qoidalar (relay, topic, close, invite, event,
                   channel, archive, ai, security, analytics, backup, settings)
    bot/           aiogram adapteri + middlewares
    api/v1/        REST endpointlari
    tasks.py       celery vazifalari
  tests/           396 test (Telegram/Redis/Postgres'siz)
frontend/          Next.js admin panel
deploy/            nginx, prometheus, grafana provisioning
docs/              texnik tahlil, arxitektura, DB, deploy, API
```

## Hujjatlar

1. [`docs/01-texnik-tahlil.md`](docs/01-texnik-tahlil.md) — "faqat ikki kishi yoza
   oladi" talabi, Bot API cheklovlari, relay vs MTProto qarori
2. [`docs/02-arxitektura.md`](docs/02-arxitektura.md) — qatlamlar va mexanizmlar
3. [`docs/03-database.md`](docs/03-database.md) — 24 jadval tavsifi
4. [`docs/04-deploy.md`](docs/04-deploy.md) — Telegram sozlash, Docker, backup
5. [`docs/05-api.md`](docs/05-api.md) — REST API referens

## Testlar

```
396 passed
```

Testlar haqiqiy servis qatlamini ishga tushiradi: kod generatsiyasi, relay ruxsat
matritsasi, lifecycle holat mashinasi, ikki tomonlama yopish, sherik taklifi,
obuna darvozasi, AI moderatsiya, flood control, event/jadval, arxiv eksporti,
analitika, REST API va butun bot dialogi. Telegram o'rniga `FakeGateway` barcha
API chaqiruvlarini yozib boradi.

## Litsenziya

Hozircha litsenziya fayli qo'shilmagan — mualliflik huquqi muallifga tegishli.