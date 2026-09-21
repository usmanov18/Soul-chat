# Arxitektura

## 1. Umumiy ko'rinish

```
Telegram foydalanuvchi
        │  DM / inline
        ▼
┌───────────────────────┐      ┌────────────────────────────┐
│  Aiogram 3 bot        │─────►│  SoulChatBot (orkestrator) │
│  app/bot/handlers     │      │  app/services/bot_service  │
└───────────────────────┘      └─────────────┬──────────────┘
                                             │
        ┌────────────────────────────────────┼───────────────────────────┐
        ▼                                    ▼                           ▼
┌──────────────┐   ┌───────────────────────────────────┐   ┌────────────────────┐
│ RelayService │   │ TopicService / CloseService /     │   │ ChannelService     │
│ (yozish nazorati)│ InviteService / EventService      │   │ (kanal + galereya) │
└──────┬───────┘   └───────────────────────────────────┘   └─────────┬──────────┘
       │                                                             │
       ▼                                                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          Telegram Bot API                                  │
│   forum supergroup (read-only, topics)        broadcast channel            │
└────────────────────────────────────────────────────────────────────────────┘
       ▲                                                             ▲
       │                                                             │
┌──────┴──────────────────────────────────────────────────────────────┴─────┐
│  FastAPI  (app/main.py)  —  REST API + Swagger + /metrics + /webhook       │
└──────┬───────────────────────┬────────────────────────────┬───────────────┘
       ▼                       ▼                            ▼
┌─────────────┐        ┌──────────────┐            ┌──────────────────┐
│ PostgreSQL  │        │ Redis        │            │ Object storage   │
│ 24 jadval   │        │ cache + rate │            │ (arxiv, media)   │
└─────────────┘        │ limit + queue│            └──────────────────┘
                       └──────┬───────┘
                              ▼
                       ┌──────────────┐    ┌─────────────┐
                       │ Celery worker│    │ Celery beat │
                       │ + beat       │    │ (jadval)    │
                       └──────────────┘    └─────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Next.js admin panel     │── Chart.js, Tailwind, glass UI
                 └─────────────────────────┘
```

## 2. Qatlamlar

| Qatlam | Papka | Vazifa |
|---|---|---|
| Transport | `app/bot/handlers`, `app/api/v1` | Telegram update / HTTP → ichki chaqiruv. **Biznes qoida yo'q.** |
| Orkestrator | `app/services/bot_service.py` | Bot buyruqlari ketma-ketligi, javob matnlari, klaviatura |
| Servislar | `app/services/*` | Barcha biznes qoidalar: kod, lifecycle, relay, moderatsiya, arxiv, analitika |
| Model | `app/models/*` | SQLAlchemy ORM, 24 jadval |
| Yadro | `app/core/*` | Config, DB, cache, security, logging, timeutil |
| Fon vazifalari | `app/tasks.py` | Celery: 96 soat timer, jadval, eslatma, snapshot, backup |

**Qoida:** servislar aiogram'ni import qilmaydi. Ular `TelegramGateway` protokoli
bilan ishlaydi. Shu sababli 137 ta test Telegram'siz, Redis'siz, PostgreSQL'siz
ishlaydi (`FakeGateway` barcha API chaqiruvlarini yozib boradi).

## 3. Asosiy mexanizmlar

### 3.1 Kod tizimi (TZ 7–10)

`TopicCodeGenerator` uch sxemani qo'llaydi:

| Sxema | Misol | Izoh |
|---|---|---|
| `sequential` | `A-0001, B-0002, C-0003` | Bitta hisoblagich, harflar aylanadi |
| `gender` | Erkak `A-M`, ayol `N-Z` | Harf to'plami gender bo'yicha, hisoblagich umumiy |
| `random` | `L-0042, R-1082` | Harf tasodifiy, raqam ketma-ket |

Hisoblagich `code_prefixes` jadvalida saqlanadi va PostgreSQL'da `SELECT … FOR
UPDATE` bilan qulflanadi — kodlar hech qachon takrorlanmaydi. Topic nomi **faqat
kod** (`title == code`), ismlar topic nomida yozilmaydi.

### 3.2 Lifecycle (TZ 17–19)

```
 draft ──► active ──► frozen ──► active
             │            │
             ▼            ▼
         blocked ──► delete_pending ──► archived ──► deleted
             ▲            │
             └────────────┘  (96 soat ichida /restore)
```

Har bir o'tish `TopicStatusFlow.can()` orqali tekshiriladi. Ruxsat etilmagan o'tish
(`deleted → active`) `TopicError` ko'taradi va API 409 qaytaradi.

Yopish ikki tomonlama: `/close` → 6 xonali kod → **ikkalasi ham** `/confirm <kod>`
→ `blocked` → 96 soatlik timer.

### 3.3 Relay (TZ 11–12)

Batafsil: [`01-texnik-tahlil.md`](./01-texnik-tahlil.md).

### 3.4 Xavfsizlik (TZ 26–27)

| Qatlam | Joyi |
|---|---|
| Rate limit | `Cache.hit_window` (Redis yoki xotira), bot va API umumiy |
| Flood control | `SecurityService.register_hit` → throttle → captcha → mute |
| Captcha | `captcha_challenges` jadvali, 3 urinishdan keyin mute |
| Black/white list | `blacklist` jadvali |
| Warn → ban | `max_warns` (default 3) dan keyin avto-ban |
| AI moderatsiya | `AIModerator` — builtin evristika yoki OpenAI-mos endpoint |
| Audit | Har amal `audit_logs` ga: kim, qachon, qayerdan, IP, device, source |

### 3.5 Arxiv (TZ 20)

O'chirishdan oldin topic to'liq eksport qilinadi: **JSON, HTML, TXT, PDF** bitta
ZIP ichida. PDF `app/services/pdf_writer.py` da noldan yozilgan (bog'liqliksiz,
deflate siqilgan, avtomatik sahifalash). Har ikkala ishtirokchiga yuboriladi.

## 4. Konfiguratsiya

Barcha sozlamalar `app/core/config.py` dagi `Settings` sinfida, `.env` orqali
o'zgaradi. Ish vaqtida o'zgaradigan sozlamalar (kod sxemasi, limitlar,
moderatsiya chegaralari) `settings` jadvalida saqlanadi va admin paneldan
tahrirlanadi.

## 5. Monitoring

| Komponent | Nima beradi |
|---|---|
| `/api/v1/metrics` | Prometheus formati: users, topics, messages, media, retention, soatlik faollik |
| Prometheus | 15s intervalda scrape |
| Grafana | Tayyor dashboard (`deploy/grafana/provisioning/dashboards/soulchat.json`) |
| Sentry | `SENTRY_DSN` berilganda avtomatik ulanadi |
| Audit log | Admin paneldagi "Audit log" bo'limi |
