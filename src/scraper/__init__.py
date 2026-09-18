# SPDX-License-Identifier: AGPL-3.0-or-later
"""Async, in-memory retrieval of public TikTok MP4 posts."""

from .client import TikTokScraper, fetch_video
from .errors import (
    ContentUnavailableError,
    InvalidIdentifierError,
    JobCapacityError,
    MediaIntegrityError,
    MediaJobNotFoundError,
    MediaTooLargeError,
    ProtocolError,
    ScraperError,
    TransportError,
)
from .jobs import VideoDownloadJobs
from .models import PreparedVideo, ScrapedVideo, VideoMetadata

__all__ = [
    "ContentUnavailableError",
    "InvalidIdentifierError",
    "JobCapacityError",
    "MediaIntegrityError",
    "MediaJobNotFoundError",
    "MediaTooLargeError",
    "PreparedVideo",
    "ProtocolError",
    "ScrapedVideo",
    "ScraperError",
    "TikTokScraper",
    "TransportError",
    "VideoDownloadJobs",
    "VideoMetadata",
    "fetch_video",
]
