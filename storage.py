import json
import os
from typing import Any

from google.cloud import storage

BUCKET_NAME = os.environ["BUCKET_NAME"]

CONFIG_BLOB = "checker/config.json"
RUNTIME_STATUS_BLOB = "checker/runtime_status.json"
ALERT_STATE_BLOB = "checker.alert_state.json"
LOCK_BLOB = "checker/lock.json"

_client = storage.Client()


def _blob(name: str):
    bucket = _client.bucket(BUCKET_NAME)
    return bucket.blob(name)


def download_json(name: str, default: dict[str, Any]) -> dict[str, Any]:
    blob = _blob(name)
    if not blob.exists():
        return default
    content = blob.download_as_text()
    return json.loads(content)


def upload_json(name: str, data: dict[str, Any]) -> None:
    blob = _blob(name)
    blob.upload_from_string(
        json.dumps(data, indent=2),
        content_type="application/json",
    )


def load_config_dict() -> dict[str, Any]:
    return download_json(CONFIG_BLOB, default={})


def save_config_dict(data: dict[str, Any]) -> None:
    upload_json(CONFIG_BLOB, data)


def load_runtime_status() -> dict[str, Any]:
    return download_json(
        RUNTIME_STATUS_BLOB,
        default={
            "is_running": False,
            "run_started_at": "",
            "last_check_time": "",
            "last_check_success": None,
            "last_check_message": "",
            "last_available": False,
            "last_available_trains": [],
            "last_alert_time": "",
            "last_error": "",
        },
    )


def save_runtime_status(data: dict[str, Any]) -> None:
    upload_json(RUNTIME_STATUS_BLOB, data)


def load_alert_state() -> dict[str, Any]:
    return download_json(ALERT_STATE_BLOB, default={"last_alert_key": ""})


def save_alert_state(data: dict[str, Any]) -> None:
    upload_json(ALERT_STATE_BLOB, data)