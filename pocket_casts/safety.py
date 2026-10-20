"""Shared safety rails for the scripts that write to Pocket Casts.

- Dry run by default: a script only writes when given --apply.
- After a write, re-fetch and diff against what was intended, so a partial
  failure -- or the phone app syncing an older state over ours (Pocket Casts
  sync is last-write-wins) -- is reported instead of silently missed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from pocket_casts.client import HOME_FOLDER_UUID, PocketCastsClient, PocketCastsError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BACKUP_DIR = DATA_DIR / "backups"

# Give the server a moment before reading back what was just written.
SETTLE_SECONDS = 3


def add_mode_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true",
                       help="Actually write the changes (default is a dry run that only prints them)")
    group.add_argument("--dry-run", action="store_true",
                       help="Print the diff and exit (the default; kept for compatibility)")


def is_dry_run(args: argparse.Namespace) -> bool:
    return not args.apply


def print_dry_run_footer() -> None:
    print("\nDry run -- no changes made. Re-run with --apply to write them.")


def folder_of(podcast: dict[str, Any]) -> str:
    return podcast.get("folderUuid") or HOME_FOLDER_UUID


def refetch(client: PocketCastsClient) -> dict[str, Any]:
    time.sleep(SETTLE_SECONDS)
    try:
        return client.get_subscriptions()
    except PocketCastsError as e:
        print(f"warning: could not re-fetch to verify the write: {e}", file=sys.stderr)
        raise SystemExit(2)


def diff_podcast_folders(state: dict[str, Any], expected: dict[str, str],
                         folder_names: dict[str, str] | None = None) -> list[str]:
    """expected: podcast uuid -> folder uuid (HOME_FOLDER_UUID for top level)."""
    names = dict(folder_names or {})
    names.update({f["folderUuid"]: f["name"] for f in state.get("folders", [])})
    names.setdefault(HOME_FOLDER_UUID, "(none)")
    by_uuid = {p["uuid"]: p for p in state.get("podcasts", [])}
    out = []
    for uuid, want in expected.items():
        p = by_uuid.get(uuid)
        if p is None:
            out.append(f"podcast {uuid}: missing from re-fetched subscriptions")
            continue
        got = folder_of(p)
        if got != want:
            title = p.get("title") or uuid
            out.append(f"{title}: in {names.get(got, got)!r}, expected {names.get(want, want)!r}")
    return out


def diff_folders(state: dict[str, Any], expected: dict[str, dict[str, Any]],
                 deleted: set[str] | None = None) -> list[str]:
    """expected: folder uuid -> {field: value} that must match (e.g. name, color).
    deleted: folder uuids that must no longer be present."""
    by_uuid = {f["folderUuid"]: f for f in state.get("folders", [])}
    out = []
    for uuid, fields in expected.items():
        f = by_uuid.get(uuid)
        label = fields.get("name") or uuid
        if f is None:
            out.append(f"folder {label!r}: missing after write")
            continue
        for key, want in fields.items():
            if f.get(key) != want:
                out.append(f"folder {label!r}: {key}={f.get(key)!r}, expected {want!r}")
    for uuid in deleted or ():
        if uuid in by_uuid:
            out.append(f"folder {by_uuid[uuid]['name']!r}: still present, expected deleted")
    return out


def report_verification(mismatches: list[str], backup_path: Path | None) -> None:
    if not mismatches:
        print("Verified: re-fetched state matches the intended changes.")
        return
    print(f"\nVERIFY FAILED: {len(mismatches)} mismatch(es) after re-fetching:", file=sys.stderr)
    for m in mismatches[:50]:
        print(f"  {m}", file=sys.stderr)
    if len(mismatches) > 50:
        print(f"  ... and {len(mismatches) - 50} more", file=sys.stderr)
    print("Either the write partly failed, or a phone synced older state over it "
          "(Pocket Casts sync is last-write-wins). Re-run without --apply to see "
          "what is still outstanding.", file=sys.stderr)
    if backup_path:
        print(f"State before this run: {backup_path} (see rollback_folders.py).", file=sys.stderr)
    raise SystemExit(2)


def last_snapshot_podcast_count() -> tuple[int, Path] | None:
    """Podcast count from the most recent local snapshot: subscriptions_latest.json
    (fetch_subscriptions.py) or the newest data/backups/backup_*.json, whichever
    is newer."""
    candidates = []
    latest = DATA_DIR / "subscriptions_latest.json"
    if latest.exists():
        candidates.append(latest)
    if BACKUP_DIR.is_dir():
        candidates += sorted(BACKUP_DIR.glob("backup_*.json"))[-1:]
    if not candidates:
        return None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        count = len(json.loads(newest.read_text()).get("podcasts", []))
    except (OSError, ValueError):
        return None
    return count, newest
