"""Shared backup-writing helper for any script that mutates folder state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BACKUP_DIR = DATA_DIR / "backups"


def write_backup(folders: list, podcasts: list) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = BACKUP_DIR / f"backup_{timestamp}.json"
    payload = {
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
        "folders": folders,
        "podcasts": [{"uuid": p["uuid"], "folderUuid": p.get("folderUuid")} for p in podcasts],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path
