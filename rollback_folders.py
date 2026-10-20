#!/usr/bin/env python3
"""Restore folder state from a backup written by apply_folders.py.

Restores folder metadata (name/color/sort position/sort type) for
folders that existed at backup time, and moves podcasts back to the
folder (or top level) they were in at backup time. It does not delete
folders that were created after the backup -- if apply_folders.py made
a new folder you don't want, remove it by hand in the app; this script
only ever moves podcasts out of it, leaving it empty.

Dry run by default; pass --apply to write. Before writing it takes its own
backup of the current state (so a rollback can itself be rolled back), and
afterwards re-fetches and reports anything that does not match the backup.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pocket_casts.backup import write_backup
from pocket_casts.client import HOME_FOLDER_UUID, PocketCastsClient, PocketCastsError
from pocket_casts.env import load_dotenv_if_present
from pocket_casts.records import folder_record, podcast_folder_record
from pocket_casts.safety import (
    add_mode_flags,
    diff_folders,
    diff_podcast_folders,
    is_dry_run,
    print_dry_run_footer,
    refetch,
    report_verification,
)


def main() -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backup", type=Path, help="Path to a data/backups/backup_*.json file")
    add_mode_flags(parser)
    args = parser.parse_args()

    if not args.backup.exists():
        raise SystemExit(f"error: backup file not found: {args.backup}")
    backup = json.loads(args.backup.read_text())

    client = PocketCastsClient()
    try:
        client.login()
        current = client.get_subscriptions()
    except PocketCastsError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    current_podcasts = {p["uuid"]: p for p in current.get("podcasts", [])}
    current_folders = {f["folderUuid"]: f for f in current.get("folders", [])}

    backup_folders = {f["folderUuid"]: f for f in backup.get("folders", [])}
    backup_podcast_folder = {p["uuid"]: (p.get("folderUuid") or HOME_FOLDER_UUID) for p in backup.get("podcasts", [])}

    folders_to_restore = []
    for folder_uuid, f in backup_folders.items():
        cur = current_folders.get(folder_uuid)
        if (
            cur
            and cur["name"] == f["name"]
            and cur["color"] == f["color"]
            and cur["sortPosition"] == f["sortPosition"]
            and cur["podcastsSortType"] == f["podcastsSortType"]
        ):
            continue
        folders_to_restore.append(f)

    moves = []
    for podcast_uuid, target_folder_uuid in backup_podcast_folder.items():
        cur = current_podcasts.get(podcast_uuid)
        if cur is None:
            continue  # no longer subscribed, nothing to restore
        current_folder_uuid = cur.get("folderUuid") or HOME_FOLDER_UUID
        if current_folder_uuid == target_folder_uuid:
            continue
        moves.append({"uuid": podcast_uuid, "title": cur.get("title") or "(untitled)", "target_folder_uuid": target_folder_uuid})

    if not folders_to_restore and not moves:
        print("Nothing to restore -- current state already matches the backup.")
        return

    print(f"Folders to restore ({len(folders_to_restore)}):")
    for f in folders_to_restore:
        print(f"  {f['name']} (color={f['color']}, sort_position={f['sortPosition']}, sort_type={f['podcastsSortType']})")
    print(f"Podcast moves ({len(moves)}):")
    for m in moves:
        print(f"  {m['title']} -> folder_uuid {m['target_folder_uuid']}")

    if is_dry_run(args):
        print_dry_run_footer()
        return

    pre_rollback_backup = write_backup(list(current_folders.values()), list(current_podcasts.values()))
    print(f"\nBacked up current (pre-rollback) state to {pre_rollback_backup}")

    records = [
        folder_record(
            folder_uuid=f["folderUuid"],
            name=f["name"],
            color=f["color"],
            sort_position=f["sortPosition"],
            podcasts_sort_type=f["podcastsSortType"],
            date_added_iso=f.get("dateAdded"),
        )
        for f in folders_to_restore
    ]
    records += [podcast_folder_record(m["uuid"], m["target_folder_uuid"]) for m in moves]

    try:
        client.sync_update(records)
    except PocketCastsError as e:
        print(f"error restoring backup: {e}", file=sys.stderr)
        print(f"State before this attempt is backed up at {pre_rollback_backup}.", file=sys.stderr)
        raise SystemExit(1)

    print(f"\nRestored {len(folders_to_restore)} folder(s) and {len(moves)} podcast move(s) from {args.backup}")
    print("Run fetch_subscriptions.py to refresh the local cache.")

    expected_folders = {
        f["folderUuid"]: {k: f[k] for k in ("name", "color", "sortPosition", "podcastsSortType")}
        for f in folders_to_restore
    }
    expected_podcasts = {m["uuid"]: m["target_folder_uuid"] for m in moves}
    names = {u: f["name"] for u, f in backup_folders.items()}
    after = refetch(client)
    mismatches = diff_folders(after, expected_folders)
    mismatches += diff_podcast_folders(after, expected_podcasts, names)
    report_verification(mismatches, pre_rollback_backup)


if __name__ == "__main__":
    main()
