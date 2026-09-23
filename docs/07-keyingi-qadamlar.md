# 07 — Keyingi qadamlar: tavsiyalar va g'oyalar

Bu hujjat taxmin emas, o'lchov. Har bir band uchun kod bazasidan olingan aniq
dalil keltirilgan.

---

## A. Ishga tushirishdan oldin majburiy (bloklovchi)

### A1. Ikkita commit `main` ga kirmagan

`main` (`8c31e56`) da hali ham `passlib[bcrypt]>=1.7` turibdi — ya'ni **login
ishlamaydi**. Tuzatish `89716f9` va `9bba43e` da, ular esa faqat lokalda.
Yangi sessiyada push qilish kerak. Bu ro'yxatdagi eng arzon va eng muhim qadam.

### A2. Arxivda media fayllari yo'q (TZ 20 buzilishi)

`archive_service.py` ZIP'ga faqat **matn** formatlarini yozadi:

```python
payloads: dict[str, bytes] = {
    "json": ..., "txt": ..., "html": ..., "pdf": ...,
}
```

`media_count` hisoblanadi (`sum(1 for row in rows if row.has_media)`), lekin
fayllarning o'zi arxivga kirmaydi — kod bazasida `get_file` /
`download_file` / `file_path` bo'yicha **bitta ham chaqiruv yo'q** (grep bo'sh).

Natijada: 96 soatdan keyin topic o'chsa, foydalanuvchi o'z rasmlari, ovozli
xabarlari va videolarini **butunlay yo'qotadi**. TZ 20 esa "photo/video/voice/
document" ni arxivlashni talab qiladi.

**Yechim yo'li:**
1. `TelegramGateway.get_file(file_id) -> bytes` qo'shish (Bot API `getFile` →
   `https://api.telegram.org/file/bot<token>/<path>`).
2. Har bir media uchun `media/` papkasiga yozish: `{id}_{kind}.{ext}`.
3. Katta arxivlar uchun cheklov: `archive_max_bytes` (masalan 50 MB) va
   Telegram'ning 50 MB bot yuklama chegarasini hisobga olish.
4. Cheklovdan oshsa — ZIP'ni bo'laklarga bo'lish yoki fayllarni alohida yuborish.
5. `FakeGateway` ga `files: dict[str, bytes]` qo'shib, test yozish.

Bu **eng katta funksional bo'shliq** va uni foydalanuvchi sezadi.

### A3. PostgreSQL'da hech narsa sinovdan o'tmagan

Barcha 223 test SQLite'da ishlaydi. PG'ga xos uchta yo'l `# pragma: no cover`
ostida va hech qachon bajarilmagan:

- `func.extract("hour", …)` (`analytics_service.hour_expression`)
- `select(...).with_for_update()` (`invite_service.accept`) — race himoyasining
  asl maqsadi aynan shu yerda
- `ix_message_source` partial unique index'ning `postgresql_where` qismi

**Tavsiya:** CI'ga `services: postgres:16` qo'shib, ikkinchi test matrix'ini
ishga tushirish. Bu bitta qatorlik o'zgarish emas, lekin race himoyasi
tekshirilmaguncha u bor deb hisoblab bo'lmaydi.

---

## B. Arxitektura va texnik qarz

### B1. Admin panel — bitta 522 qatorli fayl

```
frontend/src/app/layout.tsx
frontend/src/app/page.tsx     ← 522 qator, hamma narsa shu yerda
```

Backend'da 37 ta endpoint 7 ta router'ga bo'lingan, panel esa login + dashboard +
topics + users + audit + settings + search'ni bitta komponentda ushlaydi.

**Tavsiya:** App Router'ga mos bo'lish:

```
app/(auth)/login/page.tsx
app/(panel)/layout.tsx          ← sidebar + auth guard
app/(panel)/dashboard/page.tsx
app/(panel)/topics/page.tsx
app/(panel)/topics/[code]/page.tsx   ← bitta topic + xabarlar + arxiv
app/(panel)/users/page.tsx
app/(panel)/users/[tgId]/page.tsx
app/(panel)/moderation/page.tsx      ← audit + spam + warns
app/(panel)/settings/page.tsx        ← SETTINGS_META ni ko'rsatadi
app/(panel)/gallery/page.tsx
```

Buning qo'shimcha foydasi: har sahifa alohida test qilinadi (hozir 36 test
faqat `api.ts` va `cards.tsx` uchun).

### B2. `SETTINGS_META` panel'da ko'rsatilmaydi

Backend `enforcement` darajasini (`enforced` / `reactive` / `advisory`)
qaytaradi, lekin panel buni iste'mol qilmaydi. `topic.copy_enabled` hali ham
oddiy toggle sifatida ko'rinadi — ya'ni operator uni haqiqiy kafolat deb
o'ylashi mumkin. B1 bilan birga qilinsa arzon.

### B3. Uch servis testsiz

| Servis | Qator | Test |
|---|---|---|
| `backup_service.py` | 115 | 0 |
| `notification.py` | 62 | 0 |
| `storage.py` | 45 | 0 |

`backup_service` eng xavflisi: u **ma'lumotni saqlaydigan** yagona mexanizm va
muvaffaqiyatsiz ishlasa hech kim bilmaydi. Kamida uchta test: muvaffaqiyatli
backup, fayl yozib bo'lmaganda `status="failed"` va audit yozuvi, hamda
checksum'ning to'g'riligi.

### B4. Rate limit ko'p worker'li rejimda noto'g'ri ishlaydi

`security_service` `cache.hit_window` / `cache.incr` ishlatadi. `cache` Redis
bo'lsa hammasi to'g'ri, lekin Redis yo'q bo'lsa **MemoryStore**ga tushadi —
ya'ni har worker o'z hisoblagichini yuritadi va `rate_limit_per_minute=20`
aslida `20 × worker_soni` bo'ladi. `docker-compose.yml` da `workers` sozlamasi
ko'rinmadi (grep bo'sh), shuning uchun hozir bu yashirin.

**Tavsiya:** Redis talab qilinadigan rejimda ishga tushirishda MemoryStore'ni
ogohlantirish bilan birga log'lash (`logger.warning` allaqachon `cache.py` da
bor, lekin operator'ga ko'rinmaydi), yoki startup'da `REDIS_ENABLED=true` va
`workers > 1` bo'lsa qat'iy xato berish.

---

## C. Masshtab

### C1. Qidiruv to'liq skaner qiladi

`analytics_service` da qidiruv:

```python
Message.text.ilike(f"%{query}%") | Message.caption.ilike(f"%{query}%")
```

Boshidagi `%` hech qanday indeksga tushmaydi — har bir qidiruv `messages`
jadvalini to'liq o'qiydi. 1 mln xabarda bu soniyalar.

**Tavsiya (PostgreSQL):** `pg_trgm` kengaytmasi + GIN indeks:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_messages_text_trgm ON messages USING gin (text gin_trgm_ops);
```

Yoki to'liq matnli qidiruv: `to_tsvector('russian', text)` — rus va o'zbek
matnlari uchun `simple` konfiguratsiyasi ham yetarli. SQLite uchun FTS5
jadvali. Ikkalasi ham `hour_expression` kabi dialect'ga qarab tanlanadi.

### C2. Relay o'tkazuvchanligi o'lchanmagan

Relay — platformaning yuragi va u har xabar uchun: ruxsat tekshiruvi →
moderatsiya → rate limit → DB yozuvi → Telegram API chaqiruvi. Bitta
foydalanuvchi uchun yetarli, lekin 1000 ta faol juftlikda Telegram'ning
`30 xabar/soniya` global va `1 xabar/soniya/guruh` chegarasiga uriladi.

**Tavsiya:** `locust` yoki oddiy `asyncio` yuklama testi bilan o'lchash; navbat
(Celery) orqali topic'ga yozishni tekislash va `429 retry_after` ni hurmat
qilish. Hozir `retry_after` qayta ishlанishi tekshirilmagan.

### C3. `/metrics` da relay metrikalari yo'q

Hozir faqat `COUNT(*)` agregatlari. Eng kerakli ko'rsatkichlar yo'q:

- `soulchat_relay_total{result="ok|duplicate|denied_…"}` — counter
- `soulchat_relay_duration_seconds` — histogram
- `soulchat_telegram_errors_total{method="…"}` — counter
- `soulchat_archive_duration_seconds`

Bular `relay_private` ichida bir necha qator bilan qo'shiladi va Grafana
dashboard'ini (`deploy/grafana/.../soulchat.json`) mazmunli qiladi.

---

## D. Mahsulot g'oyalari

| # | G'oya | Nega |
|---|---|---|
| D1 | **Xabarni yo'q qilish taymeri** — foydalanuvchi `/timer 24h` bilan bitta xabarni belgilaydi | Anonimlik va'dasini kuchaytiradi; relay arxitekturada bu juda oson, chunki bot xabarni o'zi yozadi |
| D2 | **Ovozli xabarlarni transkripsiya** — arxivga matn sifatida qo'shish | Hozir arxivda ovozli xabar shunchaki "voice" deb turadi; Whisper API bilan hal qilinadi |
| D3 | **AI xulosa va vaqt shkalasi** | `ai_service` da interfeys bor, lekin `/summary` buyrug'i yo'q — 1000 xabarli suhbatni qisqacha ko'rish |
| D4 | **Gallery sahifasi** | `render_gallery_caption` va `channel_posts` allaqachon bor, lekin panelda alohida galereya ko'rinishi yo'q |
| D5 | **Apellyatsiya oqimi** — ban/mute uchun foydalanuvchi murojaat qiladi | `RestoreRequest` jadvali mavjud, lekin ban uchun shunga o'xshash mexanizm yo'q |
| D6 | **QR taklif** — `/invite` QR kod qaytaradi | Havolani ulashishdan ko'ra qulay; `qrcode` kutubxonasi bilan ~20 qator |
| D7 | **Ochiq statistika sahifasi** — bugungi faol suhbatlar soni | Kanal postlariga ijtimoiy isbot qo'shadi; ismsiz, faqat raqamlar |
| D8 | **Sherik almashtirish** — hozir sherik ketlsa yangi taklif kerak | `leave` bor, lekin "sherigni almashtirish" oqimi aniq emas |

---

## E. Allaqachon yaxshi qilingan (tegmang)

Bularni tekshirdim va ular to'g'ri:

- **API kalitlari** — `key_hash` (maxfiy), `unique`, `scopes`, `expires_at`,
  `last_used_at`. Bu to'g'ri dizayn, o'zgartirish kerak emas.
- **Bot webhook xavfsizligi** — `set_webhook(secret_token=…)` va
  `SimpleRequestHandler(secret_token=…)` ishlatilgan, ya'ni Telegram update'lari
  imzo bilan tekshiriladi. (API'dagi `/webhook` — bu boshqa, tashqi tizimlar
  uchun endpoint.)
- **Celery beat** — `tasks.py` da `beat_schedule` to'liq: sweep har 300s,
  scheduler tick `scheduler_tick_seconds` bo'yicha, reminder har 120s,
  snapshot 00:05, backup 02:00, subscription sweep har 15 daqiqada.
- **Relay izolyatsiyasi** — `SoulChatBot` aiogram'ni import qilmaydi
  (`BotReply`), shuning uchun butun bot mantiqi testsiz aiogram'siz ishlaydi.
  Bu 223 testning sababi.
- **Partial unique index** — `WHERE source_message_id IS NOT NULL` ikkala
  dialect'da ham to'g'ri generatsiya qilinadi va test bilan qoplangan.
- **Xato javoblari** — `ApiError` endi backend `detail` ini yoki HTTP reason
  phrase'ni qaytaradi, `{}` emas.

---

## F. Tavsiya etilgan tartib

```
1-hafta   A1 (push) → A3 (PG CI) → A2 (media arxiv)
2-hafta   B3 (backup testlari) → C3 (relay metrikalari) → B4 (rate limit)
3-hafta   B1 (panel bo'lish) + B2 (meta ko'rsatish)
4-hafta   C1 (pg_trgm qidiruv) → C2 (yuklama testi)
keyin     D ro'yxatidan mahsulot g'oyalari
```

A2 ni uchinchi o'ringa qo'ydim, chunki A1 bajarilmasa hech narsa foydalanuvchiga
yetib bormaydi, A3 bajarilmasa esa race himoyasi bor deb hisoblab bo'lmaydi —
lekin **foydalanuvchi nuqtai nazaridan eng og'riqlisi A2**.

---

# Bajarilishi (2026-09-21)

Yuqoridagi ro'yxatdan quyidagilari amalga oshirildi. Har biri test bilan.

| Band | Holat | Nima qilindi |
|---|---|---|
| **A2** media arxivda | ✅ | `TelegramGateway.get_file()`, `media/` papkasi ZIP'da, 20 MB va 50 MB chegaralari, `skipped_reasons`. 8 test |
| **A3** PostgreSQL | ✅ (qisman) | `sql_hour` dialect'ga xos kompilyatsiya; CI'ga `postgres:16` job; `conftest` endi `DATABASE_URL` ni hurmat qiladi. 5 test |
| **B3** uch servis testi | ✅ | `backup`, `notification`, `storage` — 18 test |
| **C3** relay metrikalari | ✅ | `app/core/metrics.py` + 5 ta seriya, `/api/v1/metrics` da. 17 test |
| **B4** rate limit | ✅ (ogohlantirish) | Redis tushib qolsa prod'da `logger.warning` |

## Yo'l davomida topilgan va tuzatilgan yangi xatolar

1. **`hour_expression` PostgreSQL uchun `strftime` generatsiya qilardi.**
   Funksiya dialektni `settings.is_sqlite` dan olardi, lekin ifoda bazaga
   bog'lanishidan **oldin** quriladi. Ya'ni `DATABASE_URL` ni o'zgartirgan har
   qanday narsa (test, ikki bazaga ulanadigan CLI) noto'g'ri SQL berardi —
   PG'da `strftime` yo'q, `/metrics` va dashboard to'liq ishdan chiqardi.
   Endi `sql_hour` — `FunctionElement` + `@compiles`, qaror kompilyatsiya
   qilayotgan dialektdan olinadi.

2. **`conftest.py` SQLite'ni hardcode qilgandi.** CI'ga PG job qo'shish
   faydasiz bo'lardi — `pytest` qadami ham SQLite'da ishlab, hech narsani
   tekshirmas edi. Endi `DATABASE_URL` sqlite bo'lmasa haqiqiy server ishlatiladi.

3. **Backup va arxiv fayl nomlari to'qnashardi.** Ikkalasi ham
   `%Y%m%d-%H%M%S` (soniyagacha) ishlatardi. Bir soniyada ikki backup bir xil
   nom olar va ikkinchisi birinchisini **jim o'chirardi** — ya'ni aynan zaxira
   nusxasi yo'qolardi. Endi mikrosekund qo'shilgan.

4. **Arxiv byudjeti `media.file_size` ga tayangan edi**, lekin u ko'pincha `0`
   (hech kim yozishni majbur qilmaydi). Shuning uchun limit umuman ishlamasdi.
   Endi yuklab olingan haqiqiy hajmga qarshi tekshiriladi.

5. **`system.py` da nom to'qnashuvi** — `metrics` route funksiyasi `metrics`
   modulini soyalar edi (`AttributeError: 'function' object has no attribute
   'render'`). `app_metrics` alias bilan hal qilindi.

## Hali ham ochiq

- **A1 push** — sessiya yopilgan, tarmoq yo'q. Uch commit (`fd4434b`, `51dfd35`,
  `218ac61`, `c4f2c9d`) lokalda; `main` da hali passlib bug'i turibdi.
- **PG job lokalda sinovdan o'tmagan** — sandbox'da postgres ham, docker ham yo'q.
  SQL dialekt kompilyatsiyasi tekshirildi, lekin haqiqiy server'da bajarilishi
  faqat CI'da ko'rinadi.
- **B1 panel'ni bo'lish**, **C1 qidiruv indeksi**, **C2 yuklama testi** — qolgan.

---

# Ikkinchi davra (2026-09-22)

Qolgan bandlar ham bajarildi. Ro'yxat endi to'liq yopilgan — **A1 (push)**
bundan mustasno, u sessiya yopilgani va tarmoq yo'qligi sababli bloklangan.

| Band | Holat | Nima qilindi |
|---|---|---|
| **C1** qidiruv indeksi | ✅ | `0003_search_indexes`: `pg_trgm` + 5 ta GIN trigram indeks. Dialect bilan himoyalangan (SQLite'da no-op) |
| **B1** panel bo'lish | ✅ | 522 qatorli `page.tsx` → 7 marshrut (`/login`, `/panel/*`), `AuthGate`, `Nav` |
| **B2** meta ko'rsatish | ✅ | `EnforcementBadge` (Kafolatlangan / Keyin bekor qilinadi / Faqat ma'lumot) + label/note |
| **C2** yuklama + 429 | ✅ | `retry_after` hurmati, `RetryAfterError`, o'lchov: 130 xabar/s |

## Yo'l davomida topilgan yangi xatolar

6. **Telegram 429 hech qayerda qayta ishlanmasdi.** `_send` istisnoni yuqoriga
   tashlardi — ko'p topic'da bir vaqtda yozilganda foydalanuvchi xabari jim
   yo'qolardi. Endi `retry_after` hurmat qilinadi (`telegram_max_retries=3`).

7. **`User.last_name` qidirilardi, lekin indeksi yo'q edi** — buni kontrakt testi
   topdi: qidiruvdagi har bir `ilike` ustuni indekslanganini tekshiradi, shuning
   uchun yangi qidiruv maydoni qo'shilsa test darhol ogohlantiradi.

8. **Panel'da `code.pad` kabi meta'siz sozlamalar** — meta bo'lmasa ham qator
   ko'rsatilishi kerak (eski API javoblari bilan ham ishlashi uchun).

## O'lchovlar

| Ko'rsatkich | Qiymat |
|---|---|
| Relay tezligi (in-memory SQLite) | **7.71 ms/xabar = 130 xabar/s** |
| Backend testlar | 292 |
| Frontend testlar | 46 |
| Panel marshrutlari | 7 (`/panel` 71.7 kB, qolganlari 1.5–2.4 kB) |

Eslatma: relay o'lchovi in-memory SQLite'da olingan. Haqiqiy PostgreSQL'da har
bir round trip tarmoq kechikishini qo'shadi — relay yo'lida ~6 ta DB amali bor,
shuning uchun PG'da xabar narxi sezilarli oshishi mumkin. Buni haqiqiy
server'da o'lchash kerak (bu yerda PostgreSQL yo'q).

---

# Uchinchi davra (2026-09-22) — foydalanuvchi darajasidagi bug

## 9-xato: yopilgan suhbat foydalanuvchi uchun "yo'q" bo'lib qolardi

**Eng jiddiy topilma.** `RelayService.current_topic()` topic'ni **holat bo'yicha
filtrardi** (`_usable`: faqat `ACTIVE` va yopilmagan). Natijada muzlatilgan,
yopilgan yoki 96 soatlik o'chirish navbatidagi topic `None` qaytarardi.

Bot shundan keyin har bir buyruqda bitta xabarni berardi:

> "Sizda faol suhbat yo'q. Yangi suhbat uchun `/new` ni bosing."

O'lchab ko'rilgan natija (tuzatishdan oldin):

```
>>> FROZEN:  reason='no_topic' reply="Sizda faol suhbat yo'q. Yangi suhbat uchun /new ni bosing."
>>> BLOCKED: reason='no_topic' reply="Sizda faol suhbat yo'q. Yangi suhbat uchun /new ni bosing."
```

### Nega bu jiddiy

| Buyruq | Oqibat |
|---|---|
| `/archive` | **ishlamasdi** — TZ 20 bo'yicha foydalanuvchi aynan o'sha 96 soat ichida arxivni olib qolishi kerak |
| `/close`, `/confirm` | **ishlamasdi** — TZ 17 yopish marosimi aynan suhbat yozib bo'lmaydigan holatda bajariladi |
| `/status` | hech narsa ko'rsatmasdi |
| Xabarning o'zi | foydalanuvchini **yangi topic yaratishga** undardi — ya'ni hali tiklanishi mumkin bo'lgan suhbatni tashlab ketishga |

### Sabab

Holat — bu **ruxsat** masalasi, lekin u **qidiruv** bosqichida hal qilinardi.
`permission_for()` allaqachon aniq sababni qaytaradi (`FROZEN`, `BLOCKED`,
`DELETE_PENDING`), ammo u hech qachon chaqirilmardi, chunki topic topilmasdi.

Mavjud test ham xatoni **tasdiqlab qo'ygan** edi — `test_relay.py:124`
muzlatilgan topic uchun `NO_TOPIC` ni assert qilar, izohda *"the topic is no
longer current"* deb yozilgan. Ya'ni noto'g'ri xatti-harakat hujjatlashtirilgan
edi.

### Yechim — ikkiga ajratish

```python
current_topic(tg_id)    # holatidan qat'i nazar — o'qish va qutqarish uchun
writable_topic(tg_id)   # faqat ACTIVE — o'zgartirish uchun
```

| Buyruq | Metod | Nega |
|---|---|---|
| `/invite`, `/event`, `/schedule` | `writable_topic` | topic'ni o'zgartiradi |
| `/close`, `/confirm`, `/archive`, `/status` | `current_topic` | o'qiydi yoki qutqaradi |
| `/restore` | `_find_closed_topic` | allaqachon to'g'ri edi |

### Tekshirish usuli

Testlar shunchaki "o'tdi" deb hisoblanmadi — **tuzatish vaqtincha qaytarilib**,
testlar qulashi isbotlandi:

| Holat | Natija |
|---|---|
| Tuzatishsiz | **9 test qulaydi** |
| Tuzatish bilan | **12/12 o'tadi** |

Demak testlar haqiqiy bug'ni ushlaydi.

## Holat

| Ko'rsatkich | Qiymat |
|---|---|
| Backend testlar | **304** |
| Frontend testlar | 46 |
| ruff | toza |

---

# To'rtinchi davra (2026-09-22) — muzlatish bir tomonlama edi

## 10-xato: moderator topic'ni muzlatadi-yu, qayta ocholmaydi

`freeze` barcha qatlamlarda bor edi, `unfreeze` esa **hech qayerda yo'q**:

| Joy | freeze | unfreeze (oldin) |
|---|---|---|
| REST API | `POST /topics/{code}/freeze` | yo'q |
| Admin panel | ❄️ tugmasi | yo'q |
| Bot | `moderate(action="freeze")` | yo'q |

**Aniqlashtirish (bu muhim):** `TopicStatusFlow` `FROZEN -> ACTIVE` ga ruxsat
berardi va `POST /topics/{code}/restore` bu o'tishni bajara olardi — demak admin
panel orqali ochish *texnik jihatdan* mumkin edi. Haqiqiy bo'shliq **bot**
tomonida edi va o'lchab tasdiqlandi:

```
>>> foydalanuvchi /restore (frozen): 'Tiklanadigan suhbat topilmadi.'  → holat: frozen
>>> moderator restore (frozen):      "Noma'lum amal: restore"          → holat: frozen
```

Ikkalasi ham `_find_closed_topic()` orqali boradi, u esa faqat
`BLOCKED / DELETE_PENDING / ARCHIVED` holatlarini qidiradi.

Ikkinchi muammo — **asimmetriya**: `freeze` o'z route'i va audit amaliga ega,
muzlatishni bekor qilish esa `restore` dan qarz olishi kerak edi. `restore()`
esa `is_closed` va `delete_at` ni ham tozalaydi (freeze ularni hech qachon
o'rnatmagan) va auditga noto'g'ri amal yozadi.

### Yechim

```python
TopicService.unfreeze(topic, actor, reason)   # FROZEN -> ACTIVE, o'z auditi
POST /api/v1/topics/{code}/unfreeze           # 409 agar muzlatilmagan bo'lsa
bot: moderate(action="unfreeze")              # ☀️ javob
bot: moderate(action="restore")               # muzlatilgan bo'lsa endi ochadi
admin panel: ☀️ tugmasi
AuditAction.TOPIC_UNFREEZE = "topic.unfreeze"
```

`transition()` bir xil holatni **jim o'tkazadi** (`if current is target: return`),
shuning uchun `unfreeze` holatni o'zi tekshiradi — aks holda muzlatilmagan
topic'da 200 qaytib, auditga chalg'ituvchi yozuv tushardi. Bu test yozish
jarayonida aniqlandi (kutilgan 409 o'rniga 200 qaytdi).

### Xavfsizlik

`_find_closed_topic()` ga `include_frozen` parametri qo'shildi va u **faqat
staff** yo'lida yoqiladi:

```python
bot.restore(tg_id)                    # include_frozen=False  — foydalanuvchi
bot.moderate(..., "restore"/"unfreeze") # include_frozen=True   — moderator
```

Aks holda muzlatilgan foydalanuvchi o'z topic'ini `/restore` bilan o'zi ochib
olardi va moderatsiya vositasi ma'nosiz qolardi. Bu alohida test bilan
mahkamlangan (`test_a_frozen_user_cannot_unfreeze_themselves`).

### Tekshirish

| Buyruq | Natija |
|---|---|
| `pytest -q` (backend) | **316 passed** |
| `pytest tests/test_unfreeze.py -q` | 12 passed |
| `ruff check …` | toza |
| frontend `vitest` | **47 passed** |
| frontend `npm run build` | ✓ 10 sahifa |

## Holat

| | Qiymat |
|---|---|
| Backend testlar | **316** |
| Frontend testlar | **47** |

---

# Beshinchi davra (2026-09-22) — TZ 15 va o'lik almashtirgichlar

## TZ 15 bajarildi: Event Gallery overlay

Avval `publish_gallery` rasmni HTML karta bilan **yonma-yon** yuborardi.
TZ 15 esa "overlay'li media postlari" deydi — karta rasmning ustida bo'lishi
kerak, chunki aynan shu uni *galereya* qiladi.

`app/services/image_card.py` — Pillow bilan pastki qismga gradient + shishasimon
karta (kod, sana, joy). Qoidalar:

| Qoida | Nega |
|---|---|
| Hech qachon istisno bermaydi | Kanal posti bezak; u hech qachon foydalanuvchi xabariga xarajat bo'lmasligi kerak |
| Emoji chizilmaydi | DejaVu'da emoji glifi yo'q — bo'sh kvadrat chiqardi. Emoji HTML kaptiyonda qoladi |
| Hamma o'lcham rasmdan nisbiy | 320px miniatura va 2560px foto bir xil ko'rinishi kerak |
| 240px dan kichik rasm → `None` | Karta o'qilmaydi, oddiy foto yaxshiroq |
| Ismlar faqat `show_names` bilan | TZ 10 — kanal ochiq |

O'lchangan natija: **900×1200 JPEG, 35% piksel o'zgargan, yuqori qism
tegilmagan**; kichik va buzilgan fayllar `None` qaytaradi.

`Pillow` `requirements.txt` da izoh qilib qo'yilgan edi — yoqildi.

## 11-xato: sweep bir mavzuda butun partiyani to'xtatardi

`sweep_delete_pending` da per-topic xato himoyasi yo'q edi. Arxiv yoki
o'chirishdagi bitta istisno butun siklni uzardi. Vazifa har 5 daqiqada qayta
ishlagani uchun **birinchi nosoz mavzu sweep'ni abadiy to'xtatardi** va boshqa
barcha foydalanuvchining ma'lumoti 96 soatdan keyin ham `delete_pending` da
osilib qolardi.

Endi per-topic `try/except` va natijada `failed` xaritasi. Arxiv
muvaffaqiyatsiz bo'lsa `hard_delete` hech qachon chaqirilmaydi (TZ 20).
Tuzatish vaqtincha qaytarilib tekshirildi: **2 test qulaydi**.

## 12-xato: admin panel almashtirgichlari hech narsa qilmasdi

**Bu TZ 10 anonimligini buzardi.** `DEFAULTS` dagi har bir kalit panel'da toggle
sifatida chiqadi, lekin **hech bir servis DB qatorini o'qimasdi** — hammasi
`app.core.config` dan kelardi:

```
$ grep -rn "await self.settings.get" app/    → (bo'sh)
```

Ya'ni operator `channel.show_names` ni o'chirib, saqlanganini ko'rib, kanal
baribir haqiqiy ismlarni chop etaverardi. `SETTINGS_META` esa uni **"enforced"**
deb belgilagandi — da'vo yolg'on edi.

Yechim: `SettingsService.get_bool(key, env_default)` — ustunlik
**DB qatori → DEFAULTS → env**. `ChannelService` uchala kalitni shu orqali
o'qiydi.

Ikkita nozik joy:

1. **Kesh instans-ichida edi**, instanslar esa har so'rovda yangi — demak
   uzoq yashovchi servis panel yozgan o'zgarishni ko'rmasdi. Modul darajasidagi
   `_generation` hisoblagichi bilan hal qilindi.
2. **Kesh kalitda `env_default` ni saqlamardi** — bitta kalitga ikki xil default
   berilsa eskirgan qiymat qaytardi (buni test ochdi). Endi faqat `DEFAULTS` da
   bor kalitlar keshlanadi.

Himoya: `test_metadata_never_claims_enforcement_for_an_unread_setting` —
"enforced" deb belgilangan har bir kanal kaliti runtime'da haqiqatan o'qilishini
tekshiradi. Asl bug'ni ikkinchi tomondan ushlaydi.

## Holat

| | Qiymat |
|---|---|
| Backend testlar | **353** |
| Frontend testlar | 47 |
| ruff | toza |