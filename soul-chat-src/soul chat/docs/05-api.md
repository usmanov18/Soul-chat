# REST API

Baza: `/api/v1` · Swagger: `/docs` · OpenAPI: `/openapi.json`

## Autentifikatsiya

Ikki usul:

```http
Authorization: Bearer <access_token>
X-API-Key: <api key>
```

Token olish:

```http
POST /api/v1/auth/login
{ "username": "admin", "password": "<username>:<SECRET_KEY>" }
```

Rollar: `user` < `moderator` < `admin` < `super_admin`.

## Endpointlar

### Auth
| Metod | Yo'l | Rol | Tavsif |
|---|---|---|---|
| POST | `/auth/login` | — | JWT juftligi |
| POST | `/auth/refresh` | — | Access tokenni yangilash |
| GET | `/auth/me` | har qanday | Joriy foydalanuvchi |

### Topics
| Metod | Yo'l | Rol | Tavsif |
|---|---|---|---|
| GET | `/topics?status=active&limit=50` | moderator+ | Ro'yxat (status filtri bilan) |
| GET | `/topics/{code}` | moderator+ | Bitta topic |
| GET | `/topics/{code}/messages` | moderator+ | Xabarlar |
| POST | `/topics/{code}/freeze` | moderator+ | Muzlatish |
| POST | `/topics/{code}/block` | moderator+ | Bloklash + 96 soat timer |
| POST | `/topics/{code}/restore` | moderator+ | Tiklash |
| POST | `/topics/{code}/archive` | moderator+ | Arxivlash |
| DELETE | `/topics/{code}` | admin+ | Telegram topicni o'chirish |
| GET | `/topics/{code}/archive` | moderator+ | ZIP yuklab olish (`X-Archive-Checksum`) |

### Users
| Metod | Yo'l | Rol |
|---|---|---|
| GET | `/users?role=&banned=&limit=` | moderator+ |
| GET | `/users/count` | moderator+ |
| GET | `/users/{tg_id}` | moderator+ |
| PATCH | `/users/{tg_id}` | admin+ |
| GET | `/users/{tg_id}/subscriptions` | moderator+ |

### Analytics
| Metod | Yo'l | Rol |
|---|---|---|
| GET | `/analytics/dashboard?days=30` | moderator+ |
| GET | `/analytics/daily`, `/weekly`, `/monthly` | moderator+ |
| GET | `/analytics/top-users`, `/top-hours` | moderator+ |
| POST | `/analytics/search` | moderator+ |
| POST | `/analytics/snapshot` | moderator+ |

### Moderation
| Metod | Yo'l | Rol | Tavsif |
|---|---|---|---|
| POST | `/moderation/action` | moderator+ | `warn` / `mute` / `ban` (admin) / `freeze` / `restore` |
| GET | `/moderation/spam` | moderator+ | AI/flood detektori natijalari |
| GET | `/moderation/audit` | admin+ | Audit log |
| GET | `/moderation/actions` | moderator+ | Mavjud amallar |

### Settings / System
| Metod | Yo'l | Rol |
|---|---|---|
| GET / PUT / POST | `/settings`, `/settings/reset` | admin+ |
| POST / GET | `/backup` | admin+ |
| POST | `/webhook` | — |
| GET | `/health` | — |
| GET | `/metrics` | — (Prometheus) |

## Misol

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin:change-me"}' | jq -r .access_token)

curl -s http://localhost:8000/api/v1/analytics/dashboard \
  -H "Authorization: Bearer $TOKEN" | jq .stats

curl -s -X POST http://localhost:8000/api/v1/topics/A-0042/freeze \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"spam"}'
```

## Rate limit

Rate limit Redis orqali barcha kirish nuqtalari uchun umumiy
(`RATE_LIMIT_PER_MINUTE`, default 20/daq). Nginx qatlamida qo'shimcha
`limit_req_zone 30r/s burst=40` qo'yilgan.

## Xato formati

```json
{ "detail": "Ruxsat etilmagan holat o'tishi: deleted -> active" }
```

| Kod | Ma'no |
|---|---|
| 401 | Token yo'q / yaroqsiz |
| 403 | Rol yetarli emas |
| 404 | Topilmadi |
| 409 | Biznes qoida buzildi (masalan noqonuniy holat o'tishi) |
| 422 | Validatsiya xatosi |