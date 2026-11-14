"""Cloudflare R2 helpers (S3-compatible) for presigned uploads."""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Union

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from backend.paths import REPO_ROOT

load_dotenv(REPO_ROOT / ".env")

logger = logging.getLogger(__name__)

R2_ACCESS_KEY = (os.getenv("R2_ACCESS_KEY") or os.getenv("R2_ACCESS_KEY_ID") or "").strip()
R2_SECRET_KEY = (os.getenv("R2_SECRET_KEY") or os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()
R2_ENDPOINT = (os.getenv("R2_ENDPOINT") or "").strip().rstrip("/")
R2_BUCKET = (os.getenv("R2_BUCKET") or "nesto-director").strip()
R2_REGION = (os.getenv("R2_REGION") or "auto").strip()


class R2NotConfigured(RuntimeError):
    """Raised when R2 env vars are missing."""


def r2_configured() -> bool:
    return bool(R2_ACCESS_KEY and R2_SECRET_KEY and R2_ENDPOINT and R2_BUCKET)


@lru_cache(maxsize=1)
def get_s3_client():
    if not r2_configured():
        raise R2NotConfigured(
            "R2 is not configured. Set R2_ACCESS_KEY, R2_SECRET_KEY, "
            "R2_ENDPOINT, R2_BUCKET in the repo-root .env"
        )
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        region_name=R2_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def generate_upload_url(
    key: str,
    *,
    content_type: str = "application/octet-stream",
    expires_in: int = 3600,
) -> str:
    """Return a PUT presigned URL (default 1 hour)."""
    client = get_s3_client()
    return client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": R2_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def generate_download_url(key: str, *, expires_in: int = 3600) -> str:
    client = get_s3_client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": R2_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def object_exists(key: str) -> bool:
    client = get_s3_client()
    try:
        client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except ClientError as exc:
        code = (exc.response or {}).get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def r2_public_uri(key: str) -> str:
    """Canonical URI stored in Supabase (not a temporary signed URL)."""
    return f"r2://{R2_BUCKET}/{key}"


def parse_r2_uri(uri: str) -> tuple[str, str]:
    """Return ``(bucket, key)`` from ``r2://bucket/key`` or bare key."""
    raw = (uri or "").strip()
    if raw.startswith("r2://"):
        rest = raw[len("r2://") :]
        bucket, _, key = rest.partition("/")
        if not bucket or not key:
            raise ValueError(f"Invalid R2 URI: {uri}")
        return bucket, key
    return R2_BUCKET, raw.lstrip("/")


def download_object(uri_or_key: str, dest: Union[Path, str]) -> Path:
    """Download an R2 object to a local path."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    bucket, key = parse_r2_uri(uri_or_key)
    client = get_s3_client()
    client.download_file(bucket, key, str(dest_path))
    logger.info("R2 download s3://%s/%s → %s", bucket, key, dest_path)
    return dest_path


def upload_file(
    local_path: Union[Path, str],
    key: str,
    *,
    content_type: str = "video/mp4",
) -> str:
    """Upload a local file to R2; return ``r2://bucket/key``."""
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    client = get_s3_client()
    extra = {
        "ContentType": content_type,
        "CacheControl": "private, max-age=3600",
    }
    if content_type == "video/mp4":
        extra["ContentDisposition"] = f'inline; filename="{path.name}"'
    started = time.monotonic()
    client.upload_file(str(path), R2_BUCKET, key, ExtraArgs=extra)
    uri = r2_public_uri(key)
    logger.info(
        "R2 upload %s → %s bytes=%s seconds=%.2f",
        path,
        uri,
        path.stat().st_size,
        time.monotonic() - started,
    )
    return uri


def list_keys(prefix: str, *, max_keys: int = 1000) -> list[str]:
    """List object keys under a prefix."""
    client = get_s3_client()
    prefix = prefix.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"
    keys: list[str] = []
    token: Optional[str] = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": R2_BUCKET,
            "Prefix": prefix,
            "MaxKeys": min(1000, max_keys - len(keys)),
        }
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents") or []:
            key = obj.get("Key")
            if key:
                keys.append(key)
                if len(keys) >= max_keys:
                    return keys
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
        if not token:
            break
    return keys


def download_prefix(
    prefix: str,
    dest_dir: Union[Path, str],
    *,
    skip_large_video: bool = False,
) -> int:
    """Download all objects under ``prefix`` into ``dest_dir``, preserving relative paths.

    Returns number of files downloaded.
    When ``skip_large_video`` is True, skip bulky walkthrough/final MP4s so Studio
    can open quickly and play via R2 presigned URLs instead.
    """
    dest_root = Path(dest_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    prefix = prefix.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"
    keys = list_keys(prefix)
    skip_names = {
        "source.mp4",
        "final_video.mp4",
        "final_video_v2.mp4",
        "preview.mp4",
        "final.mp4",
    }
    downloads: list[tuple[str, Path]] = []
    for key in keys:
        rel = key[len(prefix) :] if key.startswith(prefix) else key
        if not rel or rel.endswith("/"):
            continue
        name = Path(rel).name.lower()
        if skip_large_video and (
            name in skip_names or (name.endswith((".mp4", ".mov")) and "/output/" in f"/{rel}")
        ):
            # Keep small timeline audio; skip large video bodies.
            if name.endswith((".mp4", ".mov")):
                logger.info("Skipping large video during hydrate: %s", key)
                continue
        downloads.append((key, dest_root / rel))

    def _download(item: tuple[str, Path]) -> None:
        key, dest = item
        download_object(r2_public_uri(key), dest)

    # Studio assets are mostly small JSON/MP3 files. Bounded concurrency
    # removes per-object R2 latency while keeping memory and connection use low.
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(downloads)))) as pool:
        list(pool.map(_download, downloads))
    return len(downloads)


def health_check() -> dict[str, Any]:
    """Light connectivity check (list bucket or head)."""
    if not r2_configured():
        return {"ok": False, "configured": False, "error": "missing env"}
    try:
        client = get_s3_client()
        client.head_bucket(Bucket=R2_BUCKET)
        return {
            "ok": True,
            "configured": True,
            "bucket": R2_BUCKET,
            "endpoint": R2_ENDPOINT,
        }
    except Exception as exc:  # noqa: BLE001 — surface to /health
        logger.warning("R2 health check failed: %s", exc)
        return {
            "ok": False,
            "configured": True,
            "bucket": R2_BUCKET,
            "endpoint": R2_ENDPOINT,
            "error": str(exc),
        }
