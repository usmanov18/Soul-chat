"""Bot reply translations (uz / ru / en).

Telegram hands us ``from_user.language_code`` on every update and it is stored on
``users.language_code``. This module turns that into a localised reply.

Design notes
------------
* Uzbek is the source language — the key lookup falls back to ``uz`` first and
  only then to English, so a partially filled catalogue can never produce an
  empty string.
* ``t()`` never raises. A missing key returns the key itself, which makes an
  untranslated string obvious in a screenshot instead of crashing a relay.
* Catalogues are plain dicts so a translator can edit them without touching
  code, and ``missing_keys()`` reports the gaps for CI review.
"""

from __future__ import annotations

from collections.abc import Mapping

SUPPORTED_LANGUAGES: tuple[str, ...] = ("uz", "ru", "en")
DEFAULT_LANGUAGE = "uz"
FALLBACK_LANGUAGE = "en"

UZ: dict[str, str] = {
    "start.welcome": "🌸 <b>SoulChat AI</b>ga xush kelibsiz, {name}!\n\nBu yerda har bir suhbat — alohida maxfiy mavzu. Faqat siz va bitta sherik yozadi, boshqalar o'qiy oladi.",
    "start.gate": "⛔ Botdan foydalanish uchun avval guruh a'zosi va kanal obunachisi bo'lishingiz kerak.",
    "topic.created": "✅ Suhbatingiz ochildi: <code>{code}</code>",
    "topic.limit": "⚠️ Sizda allaqachon {count} ta suhbat bor (limit {limit}).",
    "topic.none": "Sizda hozircha faol suhbat yo'q. /new bilan yangi suhbat oching.",
    "invite.created": "📨 Sherigingizga shu havolani yuboring:\n<code>{link}</code>\n\n⏳ Havola {hours} soat amal qiladi.",
    "invite.expired": "Taklif muddati tugagan.",
    "invite.used": "Bu taklif allaqachon ishlatilgan yoki bekor qilingan.",
    "invite.not_found": "Taklif topilmadi.",
    "invite.slot_busy": "Bu suhbatta sherik o'rni band.",
    "invite.slot_limit": "Siz allaqachon {count} ta suhbatda sheriksiniz (limit {limit}).",
    "invite.accepted": "✅ Tabriklaymiz! Endi <code>{code}</code> suhbatida ikkalangiz yoza olasiz.",
    "close.code": "🔐 Suhbatni yopish uchun sherigingiz bilan bir xil kodni kiriting:\n<code>{code}</code>\n\nIkkaloviz ham tasdiqlagach suhbat blok bo'ladi.",
    "close.confirmed": "✅ Kodingiz qabul qilindi. Sherikingiz tasdiqlashini kuting.",
    "close.blocked": "🔒 Suhbat bloklandi. 96 soat ichida /restore bilan qaytarishingiz mumkin, aks holda u o'chiriladi.",
    "close.wrong_code": "Kod noto'g'ri.",
    "restore.requested": "♻️ Qayta tiklash so'rovi yuborildi.",
    "restore.restored": "♻️ Suhbat qayta tiklandi.",
    "restore.too_late": "Kechikdingiz — suhbat allaqachon o'chirilgan.",
    "archive.sent": "📦 Arxivingiz tayyor.",
    "archive.empty": "Arxivlash uchun xabar topilmadi.",
    "archive.failed": "Arxiv tayyorlashda xatolik yuz berdi.",
    "status.header": "📊 <b>{code}</b> — {status}",
    "forward.refused": "⛔ Ushbu suhbatda boshqa chatdan ko'chirilgan xabar yuborish mumkin emas.",
    "undo.done": "🗑 Oxirgi xabaringiz suhbatdan o'chirildi.",
    "undo.none": "O'chiradigan xabar topilmadi.",
    "moderation.muted": "🔇 Siz vaqtincha yozolmaysiz: {reason}",
    "moderation.banned": "⛔ Siz ushbu platformadan bloklangansiz.",
    "moderation.warned": "⚠️ Ogohlantirish ({count}/{max}): {reason}",
    "rate_limited": "⏳ Juda tez yuboryapsiz. Bir oz kuting.",
    "captcha.required": "🤖 Iltimos, avval captcha'ni yeching.",
    "event.created": "📅 Voqea qo'shildi: {title}",
    "event.reminder": "⏰ Eslatma: {title}",
    "schedule.set": "🕒 Jadval o'rnatildi: {days} kunlari {start}–{end}.",
    "help.body": "🌸 <b>Buyruqlar</b>\n\n/new — yangi suhbat\n/invite — sherik taklif qilish\n/close — suhbatni yopish\n/restore — qayta tiklash\n/archive — arxiv olish\n/status — holat\n/undo — oxirgi xabarni o'chirish\n/event — voqea qo'shish\n/schedule — jadval o'rnatish\n/search — qidirish\n/help — yordam",
}

RU: dict[str, str] = {
    "start.welcome": "🌸 Добро пожаловать в <b>SoulChat AI</b>, {name}!\n\nЗдесь каждый разговор — отдельная приватная тема. Пишете только вы и один партнёр, остальные могут читать.",
    "start.gate": "⛔ Чтобы пользоваться ботом, нужно быть участником группы и подписчиком канала.",
    "topic.created": "✅ Ваш диалог открыт: <code>{code}</code>",
    "topic.limit": "⚠️ У вас уже {count} диалогов (лимит {limit}).",
    "topic.none": "У вас пока нет активного диалога. Создайте новый командой /new.",
    "invite.created": "📨 Отправьте партнёру эту ссылку:\n<code>{link}</code>\n\n⏳ Ссылка действует {hours} ч.",
    "invite.expired": "Срок приглашения истёк.",
    "invite.used": "Это приглашение уже использовано или отменено.",
    "invite.not_found": "Приглашение не найдено.",
    "invite.slot_busy": "Место партнёра в этом диалоге занято.",
    "invite.slot_limit": "Вы уже партнёр в {count} диалогах (лимит {limit}).",
    "invite.accepted": "✅ Поздравляем! Теперь вы оба можете писать в <code>{code}</code>.",
    "close.code": "🔐 Чтобы закрыть диалог, введите одинаковый код с партнёром:\n<code>{code}</code>\n\nДиалог закроется после подтверждения обоих.",
    "close.confirmed": "✅ Код принят. Ждите подтверждения партнёра.",
    "close.blocked": "🔒 Диалог заблокирован. У вас 96 часов, чтобы вернуть его командой /restore, иначе он будет удалён.",
    "close.wrong_code": "Неверный код.",
    "restore.requested": "♻️ Запрос на восстановление отправлен.",
    "restore.restored": "♻️ Диалог восстановлен.",
    "restore.too_late": "Слишком поздно — диалог уже удалён.",
    "archive.sent": "📦 Ваш архив готов.",
    "archive.empty": "Сообщений для архива не найдено.",
    "archive.failed": "Ошибка при создании архива.",
    "status.header": "📊 <b>{code}</b> — {status}",
    "forward.refused": "⛔ В этом диалоге нельзя пересылать сообщения из других чатов.",
    "undo.done": "🗑 Ваше последнее сообщение удалено из диалога.",
    "undo.none": "Сообщение для удаления не найдено.",
    "moderation.muted": "🔇 Вы временно не можете писать: {reason}",
    "moderation.banned": "⛔ Вы заблокированы на этой платформе.",
    "moderation.warned": "⚠️ Предупреждение ({count}/{max}): {reason}",
    "rate_limited": "⏳ Слишком быстро. Подождите немного.",
    "captcha.required": "🤖 Сначала решите капчу.",
    "event.created": "📅 Событие добавлено: {title}",
    "event.reminder": "⏰ Напоминание: {title}",
    "schedule.set": "🕒 Расписание установлено: {days}, {start}–{end}.",
    "help.body": "🌸 <b>Команды</b>\n\n/new — новый диалог\n/invite — пригласить партнёра\n/close — закрыть диалог\n/restore — восстановить\n/archive — получить архив\n/status — статус\n/undo — удалить последнее сообщение\n/event — добавить событие\n/schedule — расписание\n/search — поиск\n/help — помощь",
}

EN: dict[str, str] = {
    "start.welcome": "🌸 Welcome to <b>SoulChat AI</b>, {name}!\n\nEvery conversation here is its own private topic. Only you and one partner can write; everyone else can read.",
    "start.gate": "⛔ To use the bot you must be a member of the group and subscribed to the channel.",
    "topic.created": "✅ Your conversation is open: <code>{code}</code>",
    "topic.limit": "⚠️ You already have {count} conversations (limit {limit}).",
    "topic.none": "You have no active conversation yet. Start one with /new.",
    "invite.created": "📨 Send this link to your partner:\n<code>{link}</code>\n\n⏳ The link is valid for {hours}h.",
    "invite.expired": "This invitation has expired.",
    "invite.used": "This invitation was already used or cancelled.",
    "invite.not_found": "Invitation not found.",
    "invite.slot_busy": "The partner slot in this conversation is taken.",
    "invite.slot_limit": "You are already a partner in {count} conversations (limit {limit}).",
    "invite.accepted": "✅ Congratulations! You can both write in <code>{code}</code> now.",
    "close.code": "🔐 To close the conversation, enter the same code as your partner:\n<code>{code}</code>\n\nIt closes once both of you confirm.",
    "close.confirmed": "✅ Code accepted. Waiting for your partner to confirm.",
    "close.blocked": "🔒 Conversation locked. You have 96 hours to bring it back with /restore, otherwise it is deleted.",
    "close.wrong_code": "Wrong code.",
    "restore.requested": "♻️ Restore request sent.",
    "restore.restored": "♻️ Conversation restored.",
    "restore.too_late": "Too late — the conversation is already deleted.",
    "archive.sent": "📦 Your archive is ready.",
    "archive.empty": "No messages to archive.",
    "archive.failed": "Failed to build the archive.",
    "status.header": "📊 <b>{code}</b> — {status}",
    "forward.refused": "⛔ Forwarded messages from other chats are not allowed in this conversation.",
    "undo.done": "🗑 Your last message was removed from the conversation.",
    "undo.none": "No message to delete.",
    "moderation.muted": "🔇 You are temporarily muted: {reason}",
    "moderation.banned": "⛔ You are banned from this platform.",
    "moderation.warned": "⚠️ Warning ({count}/{max}): {reason}",
    "rate_limited": "⏳ Too fast. Please wait a moment.",
    "captcha.required": "🤖 Please solve the captcha first.",
    "event.created": "📅 Event added: {title}",
    "event.reminder": "⏰ Reminder: {title}",
    "schedule.set": "🕒 Schedule set: {days}, {start}–{end}.",
    "help.body": "🌸 <b>Commands</b>\n\n/new — new conversation\n/invite — invite a partner\n/close — close the conversation\n/restore — restore it\n/archive — download the archive\n/status — status\n/undo — delete your last message\n/event — add an event\n/schedule — set a schedule\n/search — search\n/help — help",
}

CATALOGUES: dict[str, Mapping[str, str]] = {"uz": UZ, "ru": RU, "en": EN}


def normalise_language(language_code: str | None) -> str:
    """``'ru-RU'`` / ``'RU'`` / ``None`` -> a supported catalogue key."""
    if not language_code:
        return DEFAULT_LANGUAGE
    code = language_code.strip().lower().replace("_", "-").split("-")[0]
    if code in CATALOGUES:
        return code
    # Telegram sends 'uk', 'kk', 'tr' … — nothing to guess, fall back to Uzbek
    return DEFAULT_LANGUAGE


def t(key: str, language: str | None = None, **params: object) -> str:
    """Translate ``key``; never raises and never returns an empty string."""
    code = normalise_language(language)
    catalogue = CATALOGUES.get(code, UZ)
    template = catalogue.get(key) or UZ.get(key) or EN.get(key) or key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        # a template/param mismatch must not break a relay
        return template


def available_keys() -> set[str]:
    return set(UZ)


def missing_keys() -> dict[str, list[str]]:
    """Keys present in Uzbek but absent from another catalogue."""
    return {
        code: sorted(set(UZ) - set(catalogue))
        for code, catalogue in CATALOGUES.items()
        if code != "uz" and set(UZ) - set(catalogue)
    }