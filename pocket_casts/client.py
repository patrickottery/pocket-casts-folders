"""Thin client for the undocumented api.pocketcasts.com web-player API.

Endpoint shapes confirmed against two independent working OSS clients
(github.com/donatj/pocketcasts-go, github.com/essoen/PocketCasts-mcp).
Treat every response as fragile: fail loudly on anything unexpected and
log the raw body rather than guessing at recovery.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from pocket_casts import sync_api_pb2 as pb

API_BASE = "https://api.pocketcasts.com"
LOGIN_URL = f"{API_BASE}/user/login"
PODCAST_LIST_URL = f"{API_BASE}/user/podcast/list"
LAST_SYNC_AT_URL = f"{API_BASE}/user/last_sync_at"
SYNC_UPDATE_URL = f"{API_BASE}/user/sync/update"

# Sentinel folder_uuid the official apps use to mean "no folder" (top level).
# Hardcoded in Automattic/pocket-casts-android: Folder.HOME_FOLDER_UUID.
HOME_FOLDER_UUID = "973df93c-e4dc-41fb-879e-0c7b532ebb70"

# Arbitrary but stable identifiers this tool sends as its device identity.
DEVICE_ID = "pocket-casts-folders-script"
DEVICE_MODEL = "pocket-casts-folders-script"

REQUEST_TIMEOUT = 30


class PocketCastsError(RuntimeError):
    """Raised on any non-2xx or malformed response. Carries the raw body."""


class PocketCastsClient:
    def __init__(self, email: str | None = None, password: str | None = None):
        self.email = email or _require_env("POCKET_CASTS_EMAIL")
        self.password = password or _require_env("POCKET_CASTS_PASSWORD")
        self.session = requests.Session()
        self.token: str | None = None

    def login(self) -> None:
        """Single attempt. Does not retry -- read the error and fix the
        actual problem before calling again."""
        resp = self.session.post(
            LOGIN_URL,
            json={"email": self.email, "password": self.password, "scope": "webplayer"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            raise PocketCastsError(f"Login failed: HTTP {resp.status_code}\n{resp.text}")
        try:
            data = resp.json()
        except ValueError as e:
            raise PocketCastsError(f"Login response was not JSON: {resp.text}") from e
        token = data.get("token")
        if not token:
            raise PocketCastsError(f"Login response missing token: {resp.text}")
        self.token = token
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get_subscriptions(self) -> dict[str, Any]:
        """Returns the raw decoded JSON: {"podcasts": [...], "folders": [...]}."""
        if not self.token:
            self.login()
        resp = self.session.post(PODCAST_LIST_URL, json={"v": 1}, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise PocketCastsError(f"Subscription list failed: HTTP {resp.status_code}\n{resp.text}")
        try:
            return resp.json()
        except ValueError as e:
            raise PocketCastsError(f"Subscription list response was not JSON: {resp.text}") from e

    def get_last_sync_at_ms(self) -> int:
        """Returns the server's last-modified watermark as epoch milliseconds,
        or 0 if the account has never synced (matches the official app's
        Instant.EPOCH fallback)."""
        if not self.token:
            self.login()
        resp = self.session.post(
            LAST_SYNC_AT_URL,
            json={"m": DEVICE_MODEL, "v": 1},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            raise PocketCastsError(f"last_sync_at failed: HTTP {resp.status_code}\n{resp.text}")
        try:
            data = resp.json()
        except ValueError as e:
            raise PocketCastsError(f"last_sync_at response was not JSON: {resp.text}") from e
        last_sync_at = data.get("lastSyncAt")
        if not last_sync_at:
            return 0
        try:
            dt = datetime.fromisoformat(last_sync_at.replace("Z", "+00:00"))
        except ValueError as e:
            raise PocketCastsError(f"last_sync_at returned an unparseable timestamp: {last_sync_at}") from e
        return int(dt.timestamp() * 1000)

    def sync_update(self, records: list) -> "pb.SyncUpdateResponse":
        """Sends a batch of Record protobuf messages to /user/sync/update.

        Fragile-API note: this is the same endpoint the official apps use
        for every kind of write (podcasts, episodes, folders, playlists,
        bookmarks). An empty `records` list is a safe no-op used to smoke
        test auth + protobuf plumbing without touching any data.
        """
        if not self.token:
            self.login()
        last_modified = self.get_last_sync_at_ms()
        request = pb.SyncUpdateRequest()
        request.device_utc_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        request.last_modified = last_modified
        request.device_id = DEVICE_ID
        request.records.extend(records)

        headers = {"Content-Type": "application/octet-stream"}
        resp = self.session.post(
            SYNC_UPDATE_URL,
            data=request.SerializeToString(),
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            raise PocketCastsError(f"sync/update failed: HTTP {resp.status_code}\n{resp.content!r}")
        response = pb.SyncUpdateResponse()
        try:
            response.ParseFromString(resp.content)
        except Exception as e:
            raise PocketCastsError(f"sync/update response was not valid protobuf: {resp.content!r}") from e
        return response


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and fill it in, or export it in your shell."
        )
    return value
