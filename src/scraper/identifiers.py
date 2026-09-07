# SPDX-License-Identifier: AGPL-3.0-or-later
"""Identifier and redirect-target validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import InvalidIdentifierError, ProtocolError

_VIDEO_ID_RE = re.compile(r"[0-9]+")
_SHORT_CODE_RE = re.compile(r"[A-Za-z0-9]+")
_VIDEO_PATH_RE = re.compile(r"/@[A-Za-z0-9_.]*/video/([0-9]+)/?")
_TIKTOK_HOSTS = frozenset({"tiktok.com", "www.tiktok.com"})
_SHORT_HOST = "vm.tiktok.com"


@dataclass(frozen=True, slots=True)
class Identifier:
    value: str
    is_video_id: bool

    @property
    def initial_url(self) -> str:
        if self.is_video_id:
            return f"https://www.tiktok.com/@/video/{self.value}"
        return f"https://vm.tiktok.com/{self.value}/"


def parse_identifier(value: str) -> Identifier:
    """Accept only a decimal video ID or an alphanumeric short code."""
    if not isinstance(value, str) or not value:
        raise InvalidIdentifierError("Identifier must be a non-empty video ID or short code")
    if _VIDEO_ID_RE.fullmatch(value):
        return Identifier(value, is_video_id=True)
    if _SHORT_CODE_RE.fullmatch(value):
        return Identifier(value, is_video_id=False)
    raise InvalidIdentifierError("Identifier must be a decimal video ID or alphanumeric short code")


def video_id_from_page_url(url: str) -> str | None:
    """Return the video ID only from a canonical supported TikTok page URL."""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _TIKTOK_HOSTS
            or parsed.username
            or parsed.password
            or parsed.port is not None
        ):
            return None
        match = _VIDEO_PATH_RE.fullmatch(parsed.path)
        return match.group(1) if match else None
    except ValueError:
        return None


def validate_redirect_target(url: str) -> None:
    """Reject redirects outside supported public TikTok video routing."""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port is not None
        ):
            raise ProtocolError("Redirect target is not a supported HTTPS TikTok URL")
        if parsed.hostname == _SHORT_HOST and _SHORT_CODE_RE.fullmatch(parsed.path.strip("/")):
            return
        if video_id_from_page_url(url) is not None:
            return
    except ValueError as exc:
        raise ProtocolError("Redirect target is not a supported HTTPS TikTok URL") from exc
    raise ProtocolError("Redirect target is not a supported TikTok video page")
