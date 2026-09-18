# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public error taxonomy for scraper callers."""

from __future__ import annotations


class ScraperError(Exception):
    """Base class for all expected scraper failures."""


class InvalidIdentifierError(ScraperError):
    """The supplied identifier is neither a video ID nor a short code."""


class ContentUnavailableError(ScraperError):
    """The requested post is unavailable, restricted, or changed identity."""


class ProtocolError(ScraperError):
    """TikTok returned an unsupported response or changed schema."""


class TransportError(ScraperError):
    """A network request failed or returned an unsuccessful HTTP status."""


class MediaTooLargeError(ScraperError):
    """The MP4 exceeds the configured in-memory byte limit."""


class MediaIntegrityError(ScraperError):
    """The MP4 failed container, length, size, or checksum validation."""


class MediaJobNotFoundError(ScraperError):
    """The requested in-memory media job has expired or does not exist."""


class JobCapacityError(ScraperError):
    """The in-memory media job registry has reached a configured limit."""
