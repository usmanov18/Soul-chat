"""Object storage adapters (TZ 33).

The local target is fully implemented; S3 / Google Drive are thin stubs that
pick up credentials from the environment so the rest of the code path is real.
"""

from __future__ import annotations

import os

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def store_local(path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return path


async def upload_to_s3(path: str) -> str:  # pragma: no cover - needs credentials
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed; pip install boto3") from exc

    bucket = os.environ.get("S3_BUCKET", "soulchat")
    key = f"backups/{os.path.basename(path)}"
    client = boto3.client("s3")
    client.upload_file(path, bucket, key)
    return f"s3://{bucket}/{key}"


async def upload_to_gdrive(path: str) -> str:  # pragma: no cover - needs credentials
    token = os.environ.get("GDRIVE_TOKEN")
    if not token:
        raise RuntimeError("GDRIVE_TOKEN is not set")
    logger.info("google drive upload requested for %s", path)
    return f"gdrive://{os.path.basename(path)}"


def media_path(file_id: str, extension: str = "bin") -> str:
    os.makedirs(settings.media_dir, exist_ok=True)
    return os.path.join(settings.media_dir, f"{file_id}.{extension}")