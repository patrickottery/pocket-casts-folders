#!/usr/bin/env python3
"""Delete Pocket Casts folders that currently contain zero podcasts.

Typical use: after apply_folders.py reclassifies everything into new
folders, the old folder names are often left behind empty. This finds
and deletes them. Backs up current state first, same as apply_folders.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from pocket_casts.backup import write_backup
from pocket_casts.client import PocketCastsClient, PocketCastsError
from pocket_casts.env import load_dotenv_if_present
from pocket_casts.records import folder_record


def main() -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the empty folders and exit; makes no network calls that write data")
    args = parser.parse_args()

    client = PocketCastsClient()
    try:
        client.login()
        current = client.get_subscriptions()
    except PocketCastsError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    folders = current.get("folders", [])
    podcasts = current.get("podcasts", [])
    counts = Counter(p.get("folderUuid") for p in podcasts if p.get("folderUuid"))
    empty_folders = [f for f in folders if counts.get(f["folderUuid"], 0) == 0]

    if not empty_folders:
        print("No empty folders -- nothing to do.")
        return

    print(f"Empty folders to delete ({len(empty_folders)}):")
    for f in empty_folders:
        print(f"  - {f['name']}")

    if args.dry_run:
        print("\nDry run -- no changes made.")
        return

    backup_path = write_backup(folders, podcasts)
    print(f"\nBacked up current state to {backup_path}")

    records = [
        folder_record(
            folder_uuid=f["folderUuid"],
            name=f["name"],
            color=f["color"],
            sort_position=f["sortPosition"],
            podcasts_sort_type=f["podcastsSortType"],
            date_added_iso=f.get("dateAdded"),
            is_deleted=True,
        )
        for f in empty_folders
    ]

    try:
        client.sync_update(records)
    except PocketCastsError as e:
        print(f"error deleting folders: {e}", file=sys.stderr)
        print(f"State before this attempt is backed up at {backup_path} -- see rollback_folders.py.", file=sys.stderr)
        raise SystemExit(1)

    print(f"\nDeleted {len(empty_folders)} empty folder(s).")
    print("Run fetch_subscriptions.py to refresh the local cache.")


if __name__ == "__main__":
    main()
