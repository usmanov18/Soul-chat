#!/usr/bin/env python3
"""Operational CLI.

    python manage.py initdb            # create all tables
    python manage.py seed              # code prefixes + default settings
    python manage.py superadmin 12345  # promote a telegram id
    python manage.py lockdown          # apply the forum read-only permissions
    python manage.py snapshot          # write today's analytics row
    python manage.py backup            # run a backup now
    python manage.py bot               # start the aiogram bot (polling)
    python manage.py schema            # print the table list
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# The CLI is a batch tool: keep it quiet unless the operator asks for DEBUG.
os.environ.setdefault("DEBUG", "false")

from app.core.config import settings
from app.core.db import SessionLocal, create_all, table_names
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger("manage")


async def _initdb() -> None:
    await create_all()
    print(f"created {len(table_names())} tables")


async def _seed() -> None:
    from app.services.settings_service import SettingsService
    from app.services.topic_code import TopicCodeGenerator

    async with SessionLocal() as session:
        prefixes = await TopicCodeGenerator(session).ensure_default_prefixes()
        await SettingsService(session).ensure_defaults()
        await session.commit()
    print(f"seeded {len(prefixes)} code prefixes and default settings")


async def _superadmin(tg_id: int) -> None:
    from sqlalchemy import select

    from app.enums import Role
    from app.models.user import User

    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user is None:
            user = User(tg_id=tg_id, username=f"admin{tg_id}", first_name="SuperAdmin")
            session.add(user)
        user.role = Role.SUPER_ADMIN.value
        await session.commit()
    print(f"tg_id {tg_id} is now super_admin")


async def _lockdown() -> None:
    from app.services.relay import LOCKDOWN_PERMISSIONS

    if not settings.bot_token or not settings.forum_chat_id:
        print("BOT_TOKEN and FORUM_CHAT_ID must be set to apply the lockdown")
        return
    from aiogram import Bot
    from aiogram.types import ChatPermissions

    bot = Bot(token=settings.bot_token)
    await bot.set_chat_permissions(
        chat_id=settings.forum_chat_id, permissions=ChatPermissions(**LOCKDOWN_PERMISSIONS)
    )
    print(f"forum {settings.forum_chat_id} is now read-only for members")


async def _snapshot() -> None:
    from app.services.analytics_service import AnalyticsService

    async with SessionLocal() as session:
        row = await AnalyticsService(session).snapshot()
        await session.commit()
    print(f"snapshot {row.day}: {row.messages} messages, {row.new_topics} new topics")


async def _backup() -> None:
    from app.services.backup_service import BackupService

    async with SessionLocal() as session:
        result = await BackupService(session).run()
        await session.commit()
    print(f"backup {result.status}: {result.path} ({result.size} bytes)")


async def _schema() -> None:
    names = table_names()
    print(f"{len(names)} tables")
    for name in names:
        print(f"  {name}")


async def _bot() -> None:
    from app.bot.setup import run_polling

    await run_polling()


def main() -> int:
    parser = argparse.ArgumentParser(description="SoulChat operational CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("initdb")
    sub.add_parser("seed")
    sub.add_parser("lockdown")
    sub.add_parser("snapshot")
    sub.add_parser("backup")
    sub.add_parser("schema")
    sub.add_parser("bot")
    promote = sub.add_parser("superadmin")
    promote.add_argument("tg_id", type=int)
    args = parser.parse_args()

    handlers = {
        "initdb": _initdb,
        "seed": _seed,
        "lockdown": _lockdown,
        "snapshot": _snapshot,
        "backup": _backup,
        "schema": _schema,
        "bot": _bot,
    }
    if args.command == "superadmin":
        asyncio.run(_superadmin(args.tg_id))
    else:
        asyncio.run(handlers[args.command]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
