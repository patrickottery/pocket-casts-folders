#!/usr/bin/env python3
"""Fetch the Pocket Casts subscription + folder list and cache it to disk.

Run this once per iteration of the classification work, not on every
script invocation -- export_csv.py and (later) the apply script read
from the cache, not the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pocket_casts.client import PocketCastsClient, PocketCastsError
from pocket_casts.env import load_dotenv_if_present

DATA_DIR = Path(__file__).parent / "data"


def main() -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=DATA_DIR, type=Path)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    client = PocketCastsClient()
    try:
        client.login()
        data = client.get_subscriptions()
    except PocketCastsError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = args.out_dir / f"subscriptions_{timestamp}.json"
    latest_path = args.out_dir / "subscriptions_latest.json"

    payload = json.dumps(data, indent=2)
    snapshot_path.write_text(payload)
    latest_path.write_text(payload)

    n_podcasts = len(data.get("podcasts", []))
    n_folders = len(data.get("folders", []))
    print(f"Fetched {n_podcasts} podcasts in {n_folders} folders.")
    print(f"Wrote {snapshot_path}")
    print(f"Updated {latest_path}")


if __name__ == "__main__":
    main()
