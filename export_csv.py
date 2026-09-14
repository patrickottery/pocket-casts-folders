#!/usr/bin/env python3
"""Export a cached subscription list (from fetch_subscriptions.py) to CSV.

Columns: uuid, title, author, description, folder_uuid, folder_name.
This is the file to base the podcast-uuid -> folder-name mapping on.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
FIELDNAMES = ["uuid", "title", "author", "description", "folder_uuid", "folder_name"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", default=DATA_DIR / "subscriptions_latest.json", type=Path)
    parser.add_argument("--out", dest="out_path", default=DATA_DIR / "subscriptions.csv", type=Path)
    args = parser.parse_args()

    if not args.in_path.exists():
        print(f"error: {args.in_path} not found. Run fetch_subscriptions.py first.", file=sys.stderr)
        raise SystemExit(1)

    data = json.loads(args.in_path.read_text())

    folder_names = {f["folderUuid"]: f["name"] for f in data.get("folders", [])}

    rows = []
    for podcast in data.get("podcasts", []):
        folder_uuid = podcast.get("folderUuid") or ""
        rows.append(
            {
                "uuid": podcast["uuid"],
                "title": podcast.get("title", ""),
                "author": podcast.get("author", ""),
                "description": (podcast.get("description") or "").replace("\n", " ").replace("\r", " ").strip(),
                "folder_uuid": folder_uuid,
                "folder_name": folder_names.get(folder_uuid, ""),
            }
        )

    rows.sort(key=lambda r: r["title"].lower())

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    with args.out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} podcasts to {args.out_path}")


if __name__ == "__main__":
    main()
