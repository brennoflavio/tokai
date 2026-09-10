# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parsing of TikTok's server-rendered video hydration document."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Mapping
from urllib.parse import urlsplit

from .errors import ContentUnavailableError, ProtocolError
from .models import VideoMetadata

_HYDRATION_ID = "__UNIVERSAL_DATA_FOR_REHYDRATION__"
_RESTRICTION_FLAGS = ("privateItem", "secret", "forFriend", "isProhibited", "takeDown")


class _HydrationScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._inside = False
        self.found = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == _HYDRATION_ID:
            self._inside = True
            self.found = True

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside = False


@dataclass(frozen=True, slots=True)
class HydratedVideo:
    metadata: VideoMetadata
    play_addr: str
    video: Mapping[str, Any]


def parse_hydration(html: str, expected_id: str) -> HydratedVideo | None:
    """Parse and validate the one server-provided video item, if present."""
    parser = _HydrationScriptParser()
    parser.feed(html)
    parser.close()
    if not parser.found:
        return None

    try:
        data = json.loads("".join(parser.parts))
        detail = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]
        if detail["statusCode"] != 0:
            raise ContentUnavailableError("TikTok marks this video as unavailable")
        item = detail["itemInfo"]["itemStruct"]
        if str(item["id"]) != expected_id:
            raise ContentUnavailableError("TikTok hydration did not match the requested video")
        if any(item.get(flag) for flag in _RESTRICTION_FLAGS):
            raise ContentUnavailableError("TikTok marks this video as restricted")
        video = item["video"]
        play_addr = video["playAddr"]
        parsed_address = urlsplit(play_addr)
        if (
            not isinstance(play_addr, str)
            or parsed_address.scheme != "https"
            or not parsed_address.hostname
            or parsed_address.username
            or parsed_address.password
        ):
            raise ProtocolError("TikTok video metadata has no HTTPS playback address")
        if video.get("format") != "mp4":
            raise ContentUnavailableError("Only public MP4 video posts are supported")
        return HydratedVideo(
            metadata=_map_metadata(item, video),
            play_addr=play_addr,
            video=video,
        )
    except ContentUnavailableError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ProtocolError("TikTok returned an unsupported video metadata schema") from exc


def _map_metadata(item: Mapping[str, Any], video: Mapping[str, Any]) -> VideoMetadata:
    author = item.get("author") or {}
    stats = item.get("stats") or {}
    return VideoMetadata(
        video_id=str(item["id"]),
        author_handle=_optional_str(author.get("uniqueId")),
        author_display_name=_optional_str(author.get("nickname")),
        caption=_optional_str(item.get("desc")) or "",
        created_at=_created_at(item.get("createTime")),
        duration_seconds=_optional_number(video.get("duration")),
        width=_optional_int(video.get("width")),
        height=_optional_int(video.get("height")),
        codec=_optional_str(video.get("codecType")),
        comment_count=_optional_int(stats.get("commentCount")),
        digg_count=_optional_int(stats.get("diggCount")),
        play_count=_optional_int(stats.get("playCount")),
        share_count=_optional_int(stats.get("shareCount")),
    )


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _created_at(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None
