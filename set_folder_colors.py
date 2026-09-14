#!/usr/bin/env python3
"""Recolor Pocket Casts folders by name.

Color indices are positions into the app's fixed 12-color palette
(pulled from Automattic/pocket-casts-android's Theme.folderColors /
filter_01..filter_12): 0 red, 1 orange, 2 yellow, 3 green, 4 sky blue,
5 purple, 6 pink, 7 grey, 8 lavender, 9 teal, 10 blue, 11 brown.

Reads the folder-name -> color-index mapping from a JSON file (default
data/colors.json, gitignored since folder names are personal). See
colors.example.json for the shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pocket_casts.backup import write_backup
from pocket_casts.client import PocketCastsClient, PocketCastsError
from pocket_casts.env import load_dotenv_if_present
from pocket_casts.records import folder_record

DATA_DIR = Path(__file__).parent / "data"


def load_colors(path: Path) -> dict[str, int]:
    if not path.exists():
        raise SystemExit(f"error: {path} not found. Copy colors.example.json to {path} and fill in your folder names.")
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def main() -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print the diff and exit; makes no network calls that write data")
    parser.add_argument("--colors", type=Path, default=DATA_DIR / "colors.json", help="Path to a JSON file mapping folder name -> color index (default: data/colors.json)")
    args = parser.parse_args()

    colors = load_colors(args.colors)

    client = PocketCastsClient()
    try:
        client.login()
        current = client.get_subscriptions()
    except PocketCastsError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    folders = current.get("folders", [])
    podcasts = current.get("podcasts", [])

    unknown = [f["name"] for f in folders if f["name"] not in colors]
    if unknown:
        print(f"warning: no color assignment for {len(unknown)} folder(s), leaving unchanged:", file=sys.stderr)
        for name in unknown:
            print(f"  {name}", file=sys.stderr)

    changes = []
    for f in folders:
        target_color = colors.get(f["name"])
        if target_color is None or target_color == f["color"]:
            continue
        changes.append({**f, "target_color": target_color})

    if not changes:
        print("Nothing to do -- colors already match.")
        return

    print(f"Color changes ({len(changes)}):")
    for f in changes:
        print(f"  {f['name']}: {f['color']} -> {f['target_color']}")

    if args.dry_run:
        print("\nDry run -- no changes made.")
        return

    backup_path = write_backup(folders, podcasts)
    print(f"\nBacked up current state to {backup_path}")

    records = [
        folder_record(
            folder_uuid=f["folderUuid"],
            name=f["name"],
            color=f["target_color"],
            sort_position=f["sortPosition"],
            podcasts_sort_type=f["podcastsSortType"],
            date_added_iso=f.get("dateAdded"),
        )
        for f in changes
    ]

    try:
        client.sync_update(records)
    except PocketCastsError as e:
        print(f"error recoloring folders: {e}", file=sys.stderr)
        print(f"State before this attempt is backed up at {backup_path} -- see rollback_folders.py.", file=sys.stderr)
        raise SystemExit(1)

    print(f"\nRecolored {len(changes)} folder(s).")
    print("Run fetch_subscriptions.py to refresh the local cache.")


if __name__ == "__main__":
    main()
