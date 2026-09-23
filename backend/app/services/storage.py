"""Object storage adapters (TZ 31/33).

``store_local`` always works. The S3 and Google Drive adapters are real
implementations but their imports/credentials are optional: without them the
function raises a clear RuntimeError that ``BackupService`` records in
``backup_history`` (status=failed) instead of crashing the beat job.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx

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
        raise RuntimeError("boto3 is not installed; see requirements-backup.txt") from exc

    bucket = settings.s3_bucket or os.environ.get("S3_BUCKET", "soulchat")
    key = f"backups/{os.path.basename(path)}"
    client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None)
    await asyncio.to_thread(client.upload_file, path, bucket, key)
    logger.info("uploaded %s to s3://%s/%s", path, bucket, key)
    return f"s3://{bucket}/{key}"


async def _gdrive_access_token() -> str:  # pragma: no cover - needs credentials
    if settings.gdrive_access_token:
        return settings.gdrive_access_token
    if settings.gdrive_refresh_token and settings.gdrive_client_id and settings.gdrive_client_secret:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.gdrive_client_id,
                    "client_secret": settings.gdrive_client_secret,
                    "refresh_token": settings.gdrive_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            return response.json()["access_token"]
    raise RuntimeError(
        "Google Drive credentials missing: set GDRIVE_ACCESS_TOKEN or "
        "GDRIVE_REFRESH_TOKEN + GDRIVE_CLIENT_ID + GDRIVE_CLIENT_SECRET"
    )


async def upload_to_gdrive(path: str) -> str:  # pragma: no cover - needs credentials
    """Resumable multipart upload of a backup file to Drive's root folder."""
    token = await _gdrive_access_token()
    boundary = uuid.uuid4().hex
    metadata = b'{"name": "' + os.path.basename(path).encode() + b'"}'
    with open(path, "rb") as handle:
        payload = handle.read()
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n".encode()
        + metadata
        + f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        + payload
        + f"\r\n--{boundary}--".encode()
    )
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            content=body,
        )
        response.raise_for_status()
        file_id = response.json().get("id", "")
    logger.info("uploaded %s to gdrive file=%s", path, file_id)
    return f"https://drive.google.com/file/d/{file_id}/view"


def media_path(file_id: str, extension: str = "bin") -> str:
    os.makedirs(settings.media_dir, exist_ok=True)
    return os.path.join(settings.media_dir, f"{file_id}.{extension}")
