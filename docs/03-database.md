# Ma'lumotlar bazasi — 24 jadval

`python manage.py schema` buyrug'i ro'yxatni jonli ko'rsatadi.

## Guruhlar bo'yicha

### Foydalanuvchilar va huquqlar (4)
| Jadval | Vazifa |
|---|---|
| `users` | Telegram akkaunti, rol, gender, ban/mute holati, statistika |
| `subscriptions` | Majburiy obuna tekshiruvi (guruh + kanal), `checked_at` bilan |
| `warns` | Ogohlantirishlar tarixi |
| `blacklist` | Qora/oq ro'yxat (`kind = black | white`) |

### Topic va ishtirokchilar (6)
| Jadval | Vazifa |
|---|---|
| `code_prefixes` | Kod sxemasi: harflar, gender, separator, pad, emoji, **counter** |
| `topics` | Kod, `message_thread_id`, holat, egasi/sherigi (id va tg_id), statistika, jadval oynasi |
| `topic_participants` | owner/partner rollari va qo'shilish/chiqish vaqti |
| `invites` | Sherik taklifi: token, muddat, `uses`, holat |
| `close_codes` | Ikki tomonlama yopish kodi: `owner_confirmed`, `partner_confirmed` |
| `restore_requests` | Tiklash so'rovi va qarori |

### Kontent (4)
| Jadval | Vazifa |
|---|---|
| `messages` | Har bir uzatilgan xabar — **arxiv manbai** |
| `media` | file_id, o'lcham, davomiylik, thumbnail, kanalga chiqqanmi |
| `events` | date / reminder / checklist / deadline / location |
| `channel_posts` | Kanalga chiqqan postlar (yangi topic, galereya, system) |

### Kuzatuv va sozlamalar (4)
| Jadval | Vazifa |
|---|---|
| `audit_logs` | Kim, qachon, qayerdan, nima, IP, device, source, meta |
| `notifications` | Bot yuborgan bildirishnomalar (yetkazilmaganlari saqlanadi) |
| `stats_daily` | Kunlik analitika snapshot |
| `settings` | Ish vaqtida o'zgaradigan sozlamalar (typed) |

### Xavfsizlik va arxiv (6)
| Jadval | Vazifa |
|---|---|
| `captcha_challenges` | Captcha savoli, javobi, urinishlar |
| `spam_events` | AI/flood detektori natijalari, risk score |
| `archives` | Eksport qilingan ZIP: path, size, checksum, formatlar |
| `backup_history` | Avtomatik backup tarixi |
| `sessions` | Admin panel sessiyalari (revocation uchun) |
| `api_keys` | Tashqi integratsiya uchun API kalitlari (hash saqlanadi) |

## Muhim indekslar

```
topics.code                       UNIQUE   — kod takrorlanmasligi
topics.owner_tg_id / partner_tg_id         — relay'ning issiq yo'li
messages(topic_id, tg_message_id)          — duplikat tekshiruvi
messages(topic_id, created_at)             — arxiv va analitika
events(due_at, status)                     — scheduler
audit_logs(actor_tg_id, action)            — moderatsiya tarixi
stats_daily.day                     UNIQUE — snapshot idempotent
```

## Nega `owner_tg_id` / `partner_tg_id` duplikat?

`topics.owner_id` — `users.id` ga FK. Lekin Telegram update'ida faqat **tg_id**
bor. Relay har bir xabarda "bu odam shu topicning yozuvchisimi?" deb so'raydi; bu
savolga join'siz javob berish uchun tg_id topic qatorida denormalizatsiya qilingan.
Bu — issiq yo'ldagi yagona join'ni olib tashlaydi.

## Migratsiya

```bash
alembic upgrade head          # boshlang'ich sxema
alembic revision --autogenerate -m "add xxx"
```

Boshlang'ich reviziya (`0001_initial`) modellardan yaratiladi, shuning uchun yangi
baza va migratsiya qilingan baza bir xil. Keyingi reviziyalar avtogeneratsiya
qilinadi.
