#!/usr/bin/env python3
"""Apply a podcast-uuid -> folder-name mapping to Pocket Casts.

Mapping file: a CSV with at least `uuid` and `folder_name` columns --
the same shape export_csv.py produces, so the normal workflow is:
copy data/subscriptions.csv, edit the folder_name column by hand (or
with LLM help), and feed the result back in here. A blank folder_name
means "no folder" (top level / home screen).

Dry run by default: it prints the diff and writes nothing. Review it,
then re-run with --apply. A real run backs up the current folder state to
data/backups/ before making any network write, re-fetches afterwards and
reports anything that does not match the mapping, and is safe to re-run:
it only sends the changes still needed to reach the mapping's target state.
"""

from __future__ import annotations

import argparse
import csv
import sys
import uuid as uuidlib
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

DATA_DIR = Path(__file__).parent / "data"


def load_mapping(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        if "uuid" not in fieldnames or "folder_name" not in fieldnames:
            raise SystemExit(f"error: {path} must have 'uuid' and 'folder_name' columns, found {fieldnames}")
        mapping = {}
        for row in reader:
            u = (row["uuid"] or "").strip()
            if not u:
                continue
            mapping[u] = (row["folder_name"] or "").strip()
        return mapping


def main() -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mapping", type=Path, help="CSV with uuid,folder_name columns")
    add_mode_flags(parser)
    parser.add_argument("--new-folder-color", type=int, default=0, help="Color index for newly created folders (default: 0)")
    parser.add_argument(
        "--new-folder-sort-type",
        type=int,
        default=0,
        choices=[0, 1, 2, 3, 4],
        help="podcasts_sort_type for new folders: 0=date added (default), 1=name A-Z, 2=episode release date, 3=manual/drag-drop, 4=recently played",
    )
    args = parser.parse_args()

    if not args.mapping.exists():
        raise SystemExit(f"error: mapping file not found: {args.mapping}")
    mapping = load_mapping(args.mapping)
    if not mapping:
        raise SystemExit(f"error: {args.mapping} has no rows with a uuid")

    client = PocketCastsClient()
    try:
        client.login()
        current = client.get_subscriptions()
    except PocketCastsError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    podcasts = current.get("podcasts", [])
    folders = current.get("folders", [])
    podcasts_by_uuid = {p["uuid"]: p for p in podcasts}

    folder_uuid_by_name: dict[str, str] = {}
    duplicate_names = set()
    for f in folders:
        if f["name"] in folder_uuid_by_name:
            duplicate_names.add(f["name"])
        folder_uuid_by_name[f["name"]] = f["folderUuid"]
    if duplicate_names:
        print(
            f"warning: you have {len(duplicate_names)} folder name(s) used by more than one folder "
            f"({', '.join(sorted(duplicate_names))}); this script will target whichever one it saw last.",
            file=sys.stderr,
        )

    unknown_uuids = [u for u in mapping if u not in podcasts_by_uuid]
    if unknown_uuids:
        print(f"warning: {len(unknown_uuids)} uuid(s) in the mapping aren't in your current subscriptions, skipping:", file=sys.stderr)
        for u in unknown_uuids[:20]:
            print(f"  {u}", file=sys.stderr)
        mapping = {u: name for u, name in mapping.items() if u in podcasts_by_uuid}

    # New folders needed (only for names actually targeted by a known podcast).
    wanted_names = {name for name in mapping.values() if name} - set(folder_uuid_by_name)
    new_folders = []
    next_sort_position = len(folders)
    for name in sorted(wanted_names):
        new_uuid = str(uuidlib.uuid4())
        folder_uuid_by_name[name] = new_uuid
        new_folders.append({"uuid": new_uuid, "name": name, "sort_position": next_sort_position})
        next_sort_position += 1

    folder_name_by_uuid = {v: k for k, v in folder_uuid_by_name.items()}

    # Podcast moves still needed to reach the mapping's target state.
    moves = []
    for u, folder_name in mapping.items():
        podcast = podcasts_by_uuid.get(u)
        if podcast is None:
            continue
        current_folder_uuid = podcast.get("folderUuid") or HOME_FOLDER_UUID
        target_folder_uuid = folder_uuid_by_name[folder_name] if folder_name else HOME_FOLDER_UUID
        if current_folder_uuid == target_folder_uuid:
            continue
        moves.append(
            {
                "uuid": u,
                "title": podcast.get("title") or "(untitled)",
                "from": folder_name_by_uuid.get(current_folder_uuid, "(none)"),
                "to": folder_name or "(none)",
                "target_folder_uuid": target_folder_uuid,
            }
        )

    if not new_folders and not moves:
        print("Nothing to do -- current state already matches the mapping.")
        return

    print(f"New folders to create ({len(new_folders)}):")
    for f in new_folders:
        print(f"  + {f['name']}")
    print(f"Podcast moves ({len(moves)}):")
    for m in moves:
        print(f"  {m['title']}: {m['from']} -> {m['to']}")

    if is_dry_run(args):
        print_dry_run_footer()
        return

    backup_path = write_backup(folders, podcasts)
    print(f"\nBacked up current state to {backup_path}")

    records = [
        folder_record(
            folder_uuid=f["uuid"],
            name=f["name"],
            color=args.new_folder_color,
            sort_position=f["sort_position"],
            podcasts_sort_type=args.new_folder_sort_type,
        )
        for f in new_folders
    ]
    records += [podcast_folder_record(m["uuid"], m["target_folder_uuid"]) for m in moves]

    try:
        client.sync_update(records)
    except PocketCastsError as e:
        print(f"error applying changes: {e}", file=sys.stderr)
        print(f"State before this attempt is backed up at {backup_path} -- see rollback_folders.py.", file=sys.stderr)
        raise SystemExit(1)

    print(f"\nApplied {len(new_folders)} new folder(s) and {len(moves)} move(s).")

    # Verify the whole mapping, not just this run's moves: it is the intended end state.
    expected_podcasts = {
        u: (folder_uuid_by_name[name] if name else HOME_FOLDER_UUID) for u, name in mapping.items()
    }
    expected_folders = {f["uuid"]: {"name": f["name"]} for f in new_folders}
    after = refetch(client)
    mismatches = diff_folders(after, expected_folders)
    mismatches += diff_podcast_folders(after, expected_podcasts, folder_name_by_uuid)
    report_verification(mismatches, backup_path)
    print("Run fetch_subscriptions.py to refresh the local cache.")


if __name__ == "__main__":
    main()
