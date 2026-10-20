#!/usr/bin/env python3
"""Delete Pocket Casts folders that currently contain zero podcasts.

Typical use: after apply_folders.py reclassifies everything into new
folders, the old folder names are often left behind empty. This finds
and deletes them. Backs up current state first, same as apply_folders.py.

Dry run by default; pass --apply to delete. Refuses to run if the fetched
podcast list is less than 80% of the last local snapshot's count -- a
truncated list from a transient API problem would make full folders look
empty. After deleting, re-fetches and checks the folders are really gone.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from pocket_casts.backup import write_backup
from pocket_casts.client import PocketCastsClient, PocketCastsError
from pocket_casts.env import load_dotenv_if_present
from pocket_casts.records import folder_record
from pocket_casts.safety import (
    add_mode_flags,
    diff_folders,
    is_dry_run,
    last_snapshot_podcast_count,
    print_dry_run_footer,
    refetch,
    report_verification,
)

# Refuse if the fetched podcast count drops below this share of the last snapshot.
MIN_COUNT_RATIO = 0.8


def main() -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__)
    add_mode_flags(parser)
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

    if not podcasts:
        raise SystemExit("error: Pocket Casts returned no podcasts at all -- refusing to treat every folder as empty.")
    snapshot = last_snapshot_podcast_count()
    if snapshot is None:
        raise SystemExit("error: no local snapshot to sanity-check the podcast count against. "
                         "Run fetch_subscriptions.py first.")
    baseline, snapshot_path = snapshot
    if baseline and len(podcasts) < MIN_COUNT_RATIO * baseline:
        raise SystemExit(
            f"error: fetched {len(podcasts)} podcasts but the last snapshot ({snapshot_path.name}) had "
            f"{baseline}. That looks like a partial list, which would make full folders look empty. "
            "Refusing. Try again later, or re-run fetch_subscriptions.py if you really did unsubscribe "
            "from that many.")
    print(f"Podcast count check: {len(podcasts)} now vs {baseline} in {snapshot_path.name} -- OK")

    counts = Counter(p.get("folderUuid") for p in podcasts if p.get("folderUuid"))
    empty_folders = [f for f in folders if counts.get(f["folderUuid"], 0) == 0]

    if not empty_folders:
        print("No empty folders -- nothing to do.")
        return

    print(f"Empty folders to delete ({len(empty_folders)}):")
    for f in empty_folders:
        print(f"  - {f['name']}")

    if is_dry_run(args):
        print_dry_run_footer()
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
    after = refetch(client)
    report_verification(diff_folders(after, {}, deleted={f["folderUuid"] for f in empty_folders}), backup_path)
    print("Run fetch_subscriptions.py to refresh the local cache.")


if __name__ == "__main__":
    main()
