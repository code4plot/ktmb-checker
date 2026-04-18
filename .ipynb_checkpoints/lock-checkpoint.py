import json
import os
import time
import uuid
from typing import Optional

from google.cloud import storage

BUCKET_NAME = os.environ["BUCKET_NAME"]
LOCK_BLOB = "checker/lock.json"
LOCK_TTL_SECONDS = 600

_client = storage.Client()


def _blob():
    bucket = _client.bucket(BUCKET_NAME)
    return bucket.blob(LOCK_BLOB)


def try_acquire_lock(owner: str) -> bool:
    blob = _blob()

    if not blob.exists():
        payload = {
            "owner": owner,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + LOCK_TTL_SECONDS,
        }
        try:
            blob.upload_from_string(
                json.dumps(payload),
                content_type="application/json",
                if_generation_match=0,
            )
            return True
        except Exception:
            return False

    try:
        current = json.loads(blob.download_as_text())
    except Exception:
        current = {}

    now = int(time.time())
    expires_at = int(current.get("expires_at", 0))

    if expires_at > now:
        return False

    payload = {
        "owner": owner,
        "created_at": now,
        "expires_at": now + LOCK_TTL_SECONDS,
    }
    blob.upload_from_string(
        json.dumps(payload),
        content_type="application/json",
    )
    return True


def release_lock(owner: str) -> None:
    blob = _blob()
    if not blob.exists():
        return

    try:
        current = json.loads(blob.download_as_text())
    except Exception:
        return

    if current.get("owner") == owner:
        blob.delete()


def new_lock_owner() -> str:
    return f"{os.environ.get('K_SERVICE', 'checker')}:{uuid.uuid4()}"