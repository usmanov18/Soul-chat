# 06 — Kod auditi va mustahkamlash

PR #1 merge qilinishidan oldin kod bazasi auditdan o'tkazildi. Quyida topilgan
10 ta kamchilik, ularning sababi va qanday tuzatilgani yozilgan. Har bir band
test bilan qoplangan.

---

## 1. Relay idempotent emas edi (P0)

**Muammo.** Telegram tarmoq xatosida update'ni qayta yuboradi. `relay_private`
har chaqirilganda xabarni topic'ga qayta yozardi — foydalanuvchi bitta xabar
yozsa, topic'da ikkita paydo bo'lardi.

**Yechim.** `messages.source_message_id` ustuni qo'shildi: relay qilingan xabar
o'zi kelgan DM xabarining id'sini saqlaydi. `relay_private` yozishdan oldin
shu juftlikni (`topic_id`, `sender_id`, `source_message_id`) qidiradi va topilsa
`DenyReason.DUPLICATE` qaytaradi — javob xabarsiz, chunki foydalanuvchiga allaqachon
javob berilgan.

Qo'shimcha kafolat: `ix_message_source` **qisman** (partial) unique index.
`WHERE source_message_id IS NOT NULL` sharti muhim — guruhdan kelgan xabarlarda
bu ustun `NULL`, shartsiz unique index ikkita guruh xabarini bir-biri bilan
to'qnashtirardi.

```
CREATE UNIQUE INDEX ix_message_source
  ON messages (topic_id, sender_id, source_message_id)
  WHERE source_message_id IS NOT NULL
```

**Testlar:** `test_retried_update_is_not_relayed_twice`,
`test_distinct_messages_are_both_relayed`.

---

## 2. Sherik slotida race condition (P0)

**Muammo.** `invite_service.accept()` da `if topic.partner_id: raise` tekshiruvi
bor edi, lekin qator qulflanmasdi. Ikkita foydalanuvchi bir havolani bir vaqtda
ochsa, ikkalasi ham tekshiruvdan o'tib, bitta slot'ni egallashi mumkin edi.

**Yechim.** Ikki qatlamli himoya:

- PostgreSQL'da `select(...).with_for_update()` — invite va topic qatorlari
  qulflanadi.
- SQLite'da `FOR UPDATE` no-op, shuning uchun `asyncio.Lock` (`_slot_guard`)
  check-then-set'ni atomik qiladi.

**Test:** `test_concurrent_claims_leave_exactly_one_partner` — `asyncio.gather`
bilan ikkita parallel qabul, natijada faqat bittasi `ok`.

---

## 3. Bir foydalanuvchi cheksiz sherik bo'la olardi (P0)

**Muammo.** TZ bo'yicha sherik bitta bo'lishi kerak, lekin bir akkaunt o'nlab
topic'da sherik bo'lib turishi mumkin edi — bu anonimlik va resurs modelini buzadi.

**Yechim.** `topic.max_partner_topics` sozlamasi (default `1`) va
`_active_partner_slots()` tekshiruvi: faol (`active` / `frozen` / `delete_pending`)
topic'lardagi band slotlar soni limitdan oshsa, taklif rad etiladi. Topic'dan
chiqish (`leave`) slot'ni bo'shatadi.

**Testlar:** `test_user_cannot_hold_two_partner_slots`,
`test_partner_slot_limit_is_configurable`, `test_leaving_frees_the_slot`.

---

## 4. `/metrics` har scrape'da og'ir hisob-kitob qilardi (P1)

**Muammo.** `system.py::metrics` har so'rovda `AnalyticsService.dashboard()` ni
chaqirardi — top users, retention, o'rtacha uzunlik. Prometheus 15 soniyada bir
marta so'raydi, ya'ni og'ir analytics doimiy yuklama ostida edi.

**Yechim.** `/metrics` faqat arzon `COUNT(*)` va `GROUP BY` agregatlarini
qaytaradi; natija `METRICS_CACHE_SECONDS` (30s) davomida cache'lanadi. Og'ir
metrikalar `dashboard()` endpoint'i va `stats_daily` snapshot'ida qoldi.

---

## 5. Soatlik agregat Python'da hisoblanardi (P1)

**Muammo.** `_top_hours()` `select(Message.created_at)` ni **limit'siz** yuklab,
har bir qatorni Python'da sanardi. 1 mln xabar = 1 mln `datetime` ob'ekti = OOM.

**Yechim.** `hour_expression()` — dialect'ga qarab `EXTRACT('hour', …)`
(PostgreSQL) yoki `CAST(strftime('%H', …) AS INTEGER)` (SQLite). Hisoblash
to'liq bazada, xotiraga faqat 24 qator qaytadi.

---

## 6. Kanal postlari haqiqiy ismlarni ochardi (P0)

**Muammo.** TZ 10 "topic nomida ism bo'lmaydi" deb va'da beradi, lekin
`ChannelService.announce_topic` va `render_gallery_caption` ochiq kanalga
`👤 Akbar` va `Akbar ❤️ Salima` chiqarardi — ya'ni anonimlik faqat topic sarlavhasida
edi, kanal'da emas.

**Yechim.** `channel.show_names` (default **false**) va `channel.show_gallery`
sozlamalari. Default holatda post'da faqat kod va `👤 Egasi` / `👤 Sherigi`
rollari chiqadi; admin xohlasa ismlarni yoqadi.

**Testlar:** `test_new_topic_announcement_contains_code_not_names`,
`test_gallery_caption_is_anonymous_by_default`,
`test_new_topic_announcement_can_include_names`,
`test_gallery_can_be_disabled`.

---

## 7. `reactions/forward/copy` o'lik config edi (P2)

**Muammo.** Uchta flag faqat yozilardi, hech qayerda o'qilmasdi.

**Yechim.**

- `forward_enabled` — **haqiqiy enforcement**. DM'da `forward_origin` bo'lsa va
  flag o'chiq bo'lsa, xabar `DenyReason.FORWARD` bilan rad etiladi.
- `reactions_enabled` — Bot API topic-miqyosida reaction'larni taqiqlay olmaydi,
  lekin `setMessageReaction` bilan keyin o'chirish mumkin. `strip_reaction()`
  qo'shildi va `message_reaction` update'idan chaqiriladi.
- `copy_enabled` — **faqat maslahat**. Sessiz ko'chirilgan xabar qo'lda yozilgandan
  farq qilmaydi, shuning uchun uni rad etishning iloji yo'q. Bu kod izohida va
  admin panelda ochiq aytilgan.

**Testlar:** `test_forwarded_message_is_refused_when_forwarding_is_off`,
`test_reactions_are_stripped_when_disabled`.

---

## 8. Celery vazifalari va bot adapter testi yo'q edi (P1)

**Muammo.** `app/tasks.py` (sweeper ma'lumot **o'chiradi**) va
`app/bot/handlers` uchun bitta ham test yo'q edi.

**Yechim.**

- Parsing mantiqi `app/bot/adapter.py` ga ko'chirildi — sof funksiyalar, aiogram
  I/O'siz. `tests/test_adapter.py` (12 test) content type, photo size tanlash,
  keyboard, `/schedule` va `/event` argument parsing'ini qoplaydi.
- `tests/test_tasks.py` (7 test) haqiqiy baza + `FakeGateway` bilan ishlaydi:
  sweeper arxiv yozib topic'ni o'chirishi, 96 soat ichidagi topic'ga tegmasligi,
  scheduler oynasi, event reminder'ining ikkala sherikga borishi va takroran
  yubormasligi, daily snapshot'ning kuniga bitta qator yozishi.

---

## 9. Tahrir/o'chirish qayta ishlanmasdi (P1)

**Muammo.** Foydalanuvchi DM'dagi xabarini tahrirlasa yoki o'chirsa, topic'dagi
nusxa o'zgarmasdi.

**Yechim.**

- `relay_edit()` — tahrirni topic nusxasiga ko'chiradi (`edit_message_text`),
  `messages.edited = true`.
- `@router.edited_message` handler'i qo'shildi.
- O'chirish uchun `/undo` buyrug'i: **Bot API foydalanuvchi o'z DM xabarini
  o'chirgani haqida bot'ga xabar bermaydi**, shuning uchun yagona ishonchli yo'l —
  aniq buyruq. `relay_delete()` topic nusxasini o'chiradi.

**Testlar:** `test_edit_in_dm_updates_the_topic_copy`,
`test_undo_deletes_the_topic_copy`, `test_undo_without_messages_is_reported`.

---

## 10. Parol tizimi (P0 — audit topmagan, ish jarayonida chiqdi)

**Muammo.** Audit "bootstrap parol" ni past darajali deb baholagandi, lekin
`manage.py setpassword` ni yozish paytida haqiqiy sabab ochildi:
`passlib 1.7.4` `bcrypt 5.0.0` bilan **umuman ishlamaydi**. passlib'ning
backend-detection kodi 72 baytdan uzun maxfiy so'z bilan `bcrypt.hashpw` ni
chaqiradi, bcrypt 5.x esa endi buni istisno bilan qaytaradi:

```
ValueError: password cannot be longer than 72 bytes
```

Ya'ni `hash_password()` har bir chaqiruvda yiqilardi — **hech kim login qila
olmasdi**. Bu PR'dagi eng jiddiy xato edi va hech bir test uni ushlamagandi.

**Yechim.**

- passlib o'chirildi (`requirements.txt`: `passlib[bcrypt]>=1.7` → `bcrypt>=4.0`).
  passlib 2020-yildan beri yangilanmayapti.
- `hash_password` / `verify_password` to'g'ridan-to'g'ri `bcrypt` ishlatadi.
  72 bayt chegarasi `_secret()` da ochiq hal qilinadi: uzun kirish SHA-256
  orqali 64 baytli ASCII'ga yig'iladi (JWT token'lari ham shu funksiya bilan
  hash'lanadi, ular ~200 bayt).
- `users.password_hash` ustuni va `manage.py setpassword <username>` qo'shildi.
- `_verify_credentials()`: saqlangan hash bo'lsa — faqat u; bo'lmasa — bootstrap
  (`<username>:<SECRET_KEY>`) va `allow_bootstrap_login` (prod'da o'chiriladi).
  Bootstrap ishlatilsa, log'ga ogohlantirish yoziladi.

**Testlar:** `tests/test_auth_password.py` (14 test) — 71/72/73/400 bayt, UTF-8,
bo'sh parol, noto'g'ri hash, bootstrap o'chirilishi, `setpassword`'dan keyin
bootstrap'ning ishlamay qolishi va router orqali haqiqiy login.

**Alembic `0002_relay_provenance`** yangi ustunlarni qo'shadi. `0001_initial`
ORM metadata'dan qurilgani uchun bu migratsiya inspector tekshiruvi bilan
idempotent: toza bazada no-op, eski bazada ustunlarni qo'shadi. Ikkala yo'l ham
(upgrade → downgrade → re-upgrade) tekshirilgan.

---

## Qo'shimcha: til (TZ 24)

`app/core/i18n.py` — uz / ru / en kataloglari. `users.language_code` (Telegram
beradigan) asosida tanlanadi; qo'llab-quvvatlanmaydigan til (`kk`, `uk`, `tr`)
o'zbekchaga tushadi. `t()` hech qachon istisno bermaydi va bo'sh satr qaytarmaydi —
tarjima topilmasa kalitning o'zi chiqadi, bu esa tarjima qilinmagan joyni
skrinshotda ko'rinadigan qiladi. `missing_keys()` katalog'lar orasidagi farqni
qaytaradi va test uni `== {}` bo'lishini talab qiladi.

---

## Natija

| Ko'rsatkich | Oldin | Keyin |
|---|---|---|
| Testlar | 137 | **209** |
| `ruff check` | pass | pass |
| `messages` jadvallari indekslari | 6 | 8 (+partial unique) |
| Alembic reviziyalari | 1 | 2 |
| Til | uz (hardcoded) | uz / ru / en |
| Login | **ishlamasdi** | ishlaydi |

---

# Ikkinchi bosqich — "nima qoldi" ro'yxatidagi tuzatishlar

## 11. Alembic `0001_initial` har doim *hozirgi* modelni qurardi

**Muammo.** `0001_initial` ichida `Base.metadata.create_all()` chaqirilardi. ORM
metadata har doim **joriy** modellarni tasvirlaydi, shuning uchun noldan
migratsiya qilingan baza aslida head holatiga yetib borardi — `alembic_version`
esa `0001_initial` deb yozib qo'yardi. Natijada keyingi har bir reviziya toza
bazada `duplicate column name` bilan yiqilardi. Bu `0002` ni yozish paytida
aniqlandi va `0002` idempotent qilinib, muammo niqoblangan edi.

**Yechim.** `backend/alembic_schema.py` — `schema_at(revision)`. ORM metadata'ni
nusxalaydi va **keyingi** reviziyalar qo'shgan ob'ektlarni olib tashlaydi:

```python
LATER_REVISION_OBJECTS = {
    "0002_relay_provenance": {
        "columns": {"messages": ("source_message_id", "edited"),
                    "users": ("password_hash",)},
        "indexes": {"ix_message_source", "ix_messages_source_message_id"},
    },
}
```

Endi `0001_initial` o'zi da'vo qilgan sxemani quradi. Yangi `0003` yozilganda
faqat shu lug'atga bir qator qo'shiladi. Nusxa dialect-neytral — `create_all`
PostgreSQL va SQLite uchun mos DDL generatsiya qiladi.

Ikki nazariy xato yo'l davomida tuzatildi: reviziyalarni taqqoslash teskari edi
(`revision > up_to` o'rniga `<=`) va `Table.columns` read-only ko'rinish bo'lgani
uchun o'chirish `_columns` orqali bajariladi.

**Testlar** (`tests/test_migrations.py`, 10 ta) — eng muhimi:

```python
def test_migrated_schema_matches_create_all(tmp_path):
    """migrate-from-zero == build-at-head, ustunma-ustun"""
```

Bundan tashqari: noldan head'ga yetish, indekslar mosligi, partial unique
index'ning `WHERE` sharti bilan saqlanishi, downgrade, `base`gacha qaytib qayta
upgrade, va 0001'da stamp qilingan legacy bazaning tozalanishi.

## 12. Admin panel'da bitta ham test yo'q edi

**Yechim.** Vitest + Testing Library qo'shildi (`frontend/vitest.config.ts`,
`npm test`), CI'ning frontend job'iga test qadami qo'yildi.

**36 test**, va ular darhol **uchta haqiqiy bug** topdi:

1. **`api.ts` xato javobini `"{}"` qilib ko'rsatardi.** `body.detail ??
   JSON.stringify(body)` — `detail` bo'lmagan bo'sh ob'ektda foydalanuvchi
   ekranda `{}` ko'rardi. Endi: `detail` satr bo'lsa — u, aks holda HTTP reason
   phrase (`Unauthorized`, `Bad Gateway`).
2. **`StatusChip` da `draft` uchun rang yo'q edi.** `TopicStatus` da 7 ta qiymat
   bor, `tones` lug'atida 6 ta — `draft` statusidagi topic admin panelda
   uslublanmagan, ya'ni deyarli ko'rinmas chip bo'lib chiqardi.
3. **`status.replace("_", " ")` faqat birinchi pastki chiziqni almashtirardi** →
   `replaceAll`.

## 13. `copy_enabled` "o'lik config" emas, lekin aldamchi edi

**Aniqlashtirish.** Oldingi audit buni "hech qayerda o'qilmaydi" deb yozgandi —
bu qisman noto'g'ri: flag saqlanardi, lekin uning **enforce qilinmasligi**
sababi ochiq aytilmagandi. Bot API sessiz ko'chirilgan xabarni qo'lda
yozilgandan farqlay olmaydi, shuning uchun uni rad etishning iloji yo'q.

**Yechim.** `SETTINGS_META` — har bir muhim sozlama uchun `label`, `note` va
`enforcement` darajasi:

| enforcement | ma'nosi | misol |
|---|---|---|
| `enforced` | relay xabarni butunlay rad etadi | `topic.forward_enabled` |
| `reactive` | API oldindan taqiqlay olmaydi, bot keyin bekor qiladi | `topic.reactions_enabled` |
| `advisory` | saqlanadi va ko'rsatiladi, lekin kafolatlab bo'lmaydi | `topic.copy_enabled` |

`GET /api/v1/settings` endi `{items, meta}` qaytaradi, shuning uchun admin panel
qaysi tugma haqiqiy kafolat ekanini ko'rsata oladi.

**Testlar:** meta kalitlari haqiqiy sozlamalarga mosligi (typo kemaga chiqmasligi
uchun), `enforcement` qiymatlari lug'atdan ekanligi, `copy_enabled`'ning aynan
`advisory` deb belgilangani, va endpoint'ning `{items, meta}` qaytarishi.

---

## Yakuniy holat

| Ko'rsatkich | PR #1 merge | 1-bosqich | 2-bosqich |
|---|---|---|---|
| Backend testlar | 137 | 209 | **223** |
| Frontend testlar | 0 | 0 | **36** |
| `ruff check` qamrovi | app, tests, manage.py | + | **+ alembic, alembic_schema.py** |
| Alembic `0001` | joriy modelni qurardi | idempotent `0002` bilan niqoblangan | **muzlatilgan sxema** |
| Login | ishlamasdi | ishlaydi | ishlaydi |

Hali ham tekshirilmagan (muhit cheklovi, kod emas): `docker compose up`
(docker binary yo'q), PostgreSQL'da Alembic (faqat SQLite'da sinaldi), haqiqiy
Telegram forumida end-to-end relay.