# SPDX-License-Identifier: AGPL-3.0-or-later
"""Portable, redacted result types returned by the scraper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Public video fields safe to render in Tokai's own frontend."""

    video_id: str
    author_handle: str | None
    author_display_name: str | None
    caption: str
    created_at: datetime | None
    duration_seconds: int | float | None
    width: int | None
    height: int | None
    codec: str | None
    comment_count: int | None
    digg_count: int | None
    play_count: int | None
    share_count: int | None


@dataclass(frozen=True, slots=True)
class ScrapedVideo:
    """A complete, integrity-checked MP4 held only in memory."""

    metadata: VideoMetadata
    media: bytes
    byte_count: int
    md5: str
    file_hash_verified: bool


@dataclass(frozen=True, slots=True)
class PreparedVideo:
    """Public metadata and an opaque handle for an in-memory media job."""

    metadata: VideoMetadata
    media_id: str
