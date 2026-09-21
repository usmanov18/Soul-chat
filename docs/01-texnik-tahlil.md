# Texnik tahlil — "faqat ikki kishi yoza oladi" talabi

> TZ 37-bo'limiga javob. Loyihaning arxitekturasi shu hujjat xulosasiga qurilgan.

## 1. Muammo

Talab: bitta Telegram super guruh ichida har bir Topic (forum mavzusi) faqat **ikki
kishi** — egasi va sherigi — yozishi mumkin bo'lsin, qolgan barcha a'zolar faqat
o'qisin.

TZ 37 bu talabni Bot API orqali to'g'ridan-to'g'ri bajarib bo'lmasligini taxmin
qilgan edi. **Tahlil bu taxminni tasdiqladi.**

## 2. Tekshirilgan faktlar

| Tekshiruv | Manba / usul | Natija |
|---|---|---|
| `ChatPermissions` maydonlari | aiogram 3.31.0, `ChatPermissions.model_fields` orqali bevosita o'qildi | 16 ta maydon, barchasi **guruh miqyosida**: `can_send_messages`, `can_send_audios`, `can_send_documents`, `can_send_photos`, `can_send_videos`, `can_send_video_notes`, `can_send_voice_notes`, `can_send_polls`, `can_send_other_messages`, `can_add_web_page_previews`, `can_react_to_messages`, `can_edit_tag`, `can_change_info`, `can_invite_users`, `can_pin_messages`, `can_manage_topics`. **Topic miqyosidagi maydon yo'q.** |
| `createForumTopic` / `closeForumTopic` / `reopenForumTopic` | aiogram `Bot` obyekti + Bot API hujjatlari | Uchala metod ham botdan `can_manage_topics` admin huquqini talab qiladi (agar bot topicni o'zi yaratmagan bo'lsa). Yopiq topicda yoza olish huquqi **faqat adminlarga** berilgan. |
| Topic-miqyosidagi ruxsatlar | `telegramdesktop/tdesktop` issue #28932 (Feature Request: Configurable Permissions for Topics) | Hali ham **ochiq** feature request — ya'ni Telegram klientida ham, API'da ham mavjud emas. |
| Amaliyot | Telegram jamoasi muhokamalari | "No, it's not possible sadly. You would need to create separate group." Per-topic ruxsat yo'q; yopiq topic = faqat adminlar yozadi. |

### Xulosa

Bot API'da "topic A-001 da faqat X va Y yoza oladi" deb aytishning **hech qanday
usuli yo'q**. Mavjud variantlar faqat ikki xil holatni beradi:

1. **Guruh ochiq** → hamma yoza oladi (talab buziladi).
2. **Topic yopiq** yoki **guruh `can_send_messages=False`** → faqat adminlar yoza
   oladi, oddiy a'zolar umuman yoza olmaydi.

`restrictChatMember` ham yordam bermaydi: u **bitta foydalanuvchi**ni cheklaydi
("shu odam yoza olmasin"), lekin "shu topicda faqat shu ikki odam yoza olsin"
degan ijobiy ruxsat bera olmaydi. `use_independent_chat_permissions` esa
"guruh sozlamasidan mustaqil shaxsiy ruxsat" ma'nosini beradi, topic bilan bog'liq
emas.

## 3. Nega MTProto (userbot) ham yechim emas

TZ 37 ikkinchi variant sifatida MTProto'ni taklif qilgan. Tahlil shuni ko'rsatdiki,
u ham kerakli natijani bermaydi va yangi xavf tug'diradi:

| Mezon | Bot API + Relay | MTProto userbot |
|---|---|---|
| Topic-miqyosidagi ruxsat | Yo'q (relay bilan hal qilinadi) | **Yo'q** — cheklov Telegram server tomonida, klient kutubxonasi uni kengaytira olmaydi |
| Akkaunt xavfi | Yo'q, rasmiy bot | Bor — userbot'lar ToS bo'yicha bloklanishi mumkin |
| Telefon raqami | Kerak emas | Kerak (va uning ban bo'lishi butun tizimni to'xtatadi) |
| Barqarorlik | Rasmiy, versiyalangan API | Ichki API, tez-tez o'zgaradi |
| Xabar atributsiyasi | Bot nomidan + imzo bilan | Ikki xil akkauntdan, lekin faqat 2 ta "qo'l" |

MTProto faqat bitta narsada yutadi: xabarni aynan o'sha ikki foydalanuvchi
akkauntidan yuborish. Lekin buning uchun **ularning** akkauntini emas, **bizning**
akkauntimizni ishlatamiz — ya'ni "ikki kishi yozadi" talabi baribir buziladi,
ustiga ban xavfi qo'shiladi.

**Qaror: Bot API + Relay arxitekturasi.**

## 4. Tanlangan yechim — Relay (bot orqali uzatish)

```
                        ┌──────────────────────────────┐
                        │  Forum supergroup (read-only) │
   hamma o'qiy oladi ◄──┤  A-001  A-002  A-003  ...     │
                        └──────────────▲───────────────┘
                                       │ sendMessage(message_thread_id=…)
                                       │
                        ┌──────────────┴───────────────┐
                        │      Bot (admin huquqli)      │
                        │  RelayService.relay_private() │
                        └──────▲────────────────▲──────┘
                    xabar      │                │     xabar
                ┌──────────────┴───┐      ┌─────┴────────────┐
                │ Egasi (DM / inline)│     │ Sherigi (DM / inline)│
                └──────────────────┘      └──────────────────┘
```

### Qadamlar

1. **Guruhni qulflash.** Ishga tushganda va har bir yangi a'zo qo'shilganda
   `restrictChatMember` / `setChatPermissions` orqali barcha yozish huquqlari
   o'chiriladi (`app/services/relay.py: LOCKDOWN_PERMISSIONS`, 14 ta maydon
   `False`). Natijada forum hamma uchun faqat o'qish rejimida, bot esa admin
   bo'lgani uchun yoza oladi.

2. **Yozish botga.** Egasi va sherigi xabarni botga yozadi (shaxsiy chat yoki
   topic ichida inline rejim). `RelayService.permission_for()` tekshiradi:
   - foydalanuvchi `topic.writer_ids` ichidami (maksimal 2 ta);
   - topic holati `active`mi (`frozen` / `blocked` / `delete_pending` / `archived`
     bo'lsa — aniq sabab bilan rad etiladi);
   - foydalanuvchi ban/mute emasmi;
   - rate limit va AI moderatsiyadan o'tdimi.

3. **Uzatish.** Tekshiruvdan o'tgan xabar `sendMessage(chat_id, message_thread_id)`
   bilan topicga chiqariladi va yuboruvchi nomi bilan imzolanadi:
   `👤 Akbar Karimov\nSalom`. Media turlari alohida metodlar bilan uzatiladi
   (photo, video, voice, document, audio, animation, sticker, video_note,
   location).

4. **Zaxira nazorat.** Agar guruh sozlamasi buzilsa va uchinchi shaxs yozsa,
   `moderate_group_message()` uning xabarini o'chiradi.

### Natija

| Talab | Bajarilishi |
|---|---|
| Hamma suhbatni ko'radi | ✅ Forum ochiq, topic read-only |
| Faqat ruxsat berilgan ikki kishi yoza oladi | ✅ `writer_ids` tekshiruvi + guruh qulfi |
| Barcha boshqaruv bot orqali | ✅ `/new`, `/invite`, `/close`, `/restore`, … |
| Statistika saqlanadi | ✅ Har bir uzatilgan xabar `messages` jadvaliga yoziladi |
| Kanal va guruh sinxron | ✅ `ChannelService` har yangi topic va mediani kanalga chiqaradi |

## 5. Relay'ning cheklovlari (ochiq aytish kerak)

Bu yechim mahsulot talabini to'liq bajaradi, lekin texnik oqibatlari bor va ularni
yashirmaymiz:

1. **Xabar bot nomidan chiqadi**, foydalanuvchi nomidan emas. Shu sababli har bir
   xabar yuboruvchi ismi bilan imzolanadi. Bu — Telegram'ning o'zi qo'ygan
   cheklovning to'g'ridan-to'g'ri natijasi.
2. **Reaksiya va forward** mavjud Telegram imkoniyatlariga bog'liq: reaksiyani
   admin sozlamasi (`topic.reactions_enabled`) boshqaradi, lekin topic read-only
   bo'lgani uchun oddiy a'zolarning reaksiyasi guruh ruxsatlariga bog'liq
   (`can_react_to_messages`).
3. **"Yozish…" (typing) indikatori** botniki bo'ladi.
4. **Inline rejim** muqobil yo'l sifatida qo'llab-quvvatlanadi: topic ichida
   `@bot matn` yozilsa, bot xabarni topicga qaytaradi. Bu foydalanuvchiga
   "o'z topicimda yozayapman" hissini beradi.

Agar kelajakda Telegram topic-miqyosidagi ruxsatlarni qo'shsa (tdesktop #28932),
`RelayService` ichidagi bitta funksiya — `_post_to_topic` — o'chirilib, to'g'ridan
-to'g'ri yozishga o'tish mumkin. Arxitekturaning qolgan qismi (kod tizimi,
lifecycle, arxiv, analitika) o'zgarmaydi.

## 6. Bot uchun zarur admin huquqlari

| Huquq | Nega kerak |
|---|---|
| `can_manage_topics` | Topic yaratish, yopish, ochish, o'chirish |
| `can_delete_messages` | Ruxsatsiz xabarlarni o'chirish, arxivdan keyin tozalash |
| `can_restrict_members` | Guruhni read-only qilish, mute/ban |
| `can_post_messages` | Kanalga post chiqarish |
| `can_delete_messages` (kanal) | Galereya postlarini tahrirlash/o'chirish |
| `can_invite_users` | Sherik havolalari |
| `can_pin_messages` | Muhim e'lonlarni qadash |

Bot guruhda **admin** bo'lishi shart — aks holda lockdown ham, relay ham ishlamaydi.
