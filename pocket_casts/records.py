"""Protobuf Record builders for the /user/sync/update endpoint.

Shared by apply_folders.py and rollback_folders.py so the two scripts
can't drift on how a folder/podcast record is constructed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pocket_casts import sync_api_pb2 as pb


def folder_record(
    folder_uuid: str,
    name: str,
    color: int,
    sort_position: int,
    podcasts_sort_type: int,
    date_added_iso: str | None = None,
    is_deleted: bool = False,
) -> pb.Record:
    rec = pb.Record()
    rec.folder.folder_uuid = folder_uuid
    rec.folder.is_deleted = is_deleted
    rec.folder.name = name
    rec.folder.color = color
    rec.folder.sort_position = sort_position
    rec.folder.podcasts_sort_type = podcasts_sort_type
    if date_added_iso:
        rec.folder.date_added.FromJsonString(date_added_iso)
    else:
        rec.folder.date_added.FromDatetime(datetime.now(timezone.utc))
    return rec


def podcast_folder_record(podcast_uuid: str, target_folder_uuid: str) -> pb.Record:
    """target_folder_uuid should be client.HOME_FOLDER_UUID to remove the
    podcast from all folders."""
    rec = pb.Record()
    rec.podcast.uuid = podcast_uuid
    rec.podcast.folder_uuid.value = target_folder_uuid
    return rec
