# SPDX-License-Identifier: AGPL-3.0-or-later
"""Async HTTP session and public scraper entry points."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from types import TracebackType
from urllib.parse import urljoin

import httpx

from .errors import (
    ContentUnavailableError,
    MediaIntegrityError,
    MediaTooLargeError,
    ProtocolError,
    TransportError,
)
from .hydration import HydratedVideo, parse_hydration
from .identifiers import Identifier, parse_identifier, validate_redirect_target, video_id_from_page_url
from .models import ScrapedVideo

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
PAGE_HEADERS: Mapping[str, str] = {
    "Accept": "text/html",
    "Accept-Language": "en-US,en;q=0.9",
}
MEDIA_HEADERS: Mapping[str, str] = {
    "Accept": "*/*",
    "Accept-Encoding": "identity",
    "Referer": "https://www.tiktok.com/",
}
MAX_REDIRECTS = 5
DEFAULT_MAX_MEDIA_BYTES = 100 * 1024 * 1024


class TikTokScraper:
    """A single-use async session for one or more public TikTok video fetches.

    The session's cookie jar is retained only while this context manager is open.
    """

    def __init__(
        self,
        *,
        max_media_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
        timeout: httpx.TimeoutTypes = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if max_media_bytes <= 0:
            raise ValueError("max_media_bytes must be positive")
        self.max_media_bytes = max_media_bytes
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._fetch_lock = asyncio.Lock()

    async def __aenter__(self) -> TikTokScraper:
        if self._client is not None:
            raise RuntimeError("TikTokScraper cannot be entered more than once")
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            timeout=self._timeout,
            transport=self._transport,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _session(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use TikTokScraper as an async context manager")
        return self._client

    async def _get_page(self, url: str, expected_id: str | None) -> tuple[str, str]:
        """Resolve a generated page route manually and return its final document."""
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = await self._session.get(url, headers=PAGE_HEADERS)
            except httpx.RemoteProtocolError as exc:
                raise ProtocolError("TikTok page redirect is invalid") from exc
            except httpx.HTTPError as exc:
                raise TransportError("Could not retrieve TikTok video page") from exc

            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ProtocolError("TikTok redirect did not include a location")
                url = urljoin(str(response.url), location)
                validate_redirect_target(url)
                continue

            if response.status_code in {401, 403, 404}:
                raise ContentUnavailableError("TikTok video page is unavailable")
            if response.status_code != 200:
                raise TransportError("TikTok video page returned an unsuccessful HTTP status")

            resolved_id = video_id_from_page_url(str(response.url))
            if resolved_id is None:
                raise ProtocolError("TikTok did not resolve to a supported video page")
            if expected_id is not None and resolved_id != expected_id:
                raise ContentUnavailableError("TikTok redirect changed the requested video")
            return str(response.url), response.text
        raise ProtocolError("TikTok redirect limit exceeded")

    async def fetch_video(self, identifier: str) -> ScrapedVideo:
        """Retrieve one public post as a verified, bounded in-memory MP4."""
        parsed = parse_identifier(identifier)
        async with self._fetch_lock:
            return await self._fetch_identifier(parsed)

    async def _fetch_identifier(self, identifier: Identifier) -> ScrapedVideo:
        expected_id = identifier.value if identifier.is_video_id else None
        page_url, html = await self._get_page(identifier.initial_url, expected_id)
        expected_id = video_id_from_page_url(page_url)
        assert expected_id is not None  # guaranteed by _get_page

        for attempt in range(2):
            hydrated = parse_hydration(html, expected_id)
            if hydrated is not None:
                return await self._download_media(hydrated)
            if attempt == 0 and 'data-source="downgrade-mssdk-preload"' in html:
                await asyncio.sleep(1)
                page_url, html = await self._get_page(page_url, expected_id)
                continue
            raise ProtocolError("TikTok page has no video hydration data")
        raise AssertionError("unreachable")

    async def _download_media(self, hydrated: HydratedVideo) -> ScrapedVideo:
        expected_size, expected_hash = _media_expectations(hydrated.video, hydrated.play_addr)
        if expected_size is not None and expected_size > self.max_media_bytes:
            raise MediaTooLargeError("TikTok media exceeds the configured byte limit")

        try:
            async with self._session.stream(
                "GET", hydrated.play_addr, headers=MEDIA_HEADERS
            ) as response:
                if response.status_code in {401, 403, 404}:
                    raise ContentUnavailableError("TikTok media is unavailable")
                if response.status_code != 200:
                    raise TransportError("TikTok media returned an unsuccessful HTTP status")
                if _content_type(response) != "video/mp4":
                    raise MediaIntegrityError("TikTok media response is not an MP4")
                if _content_encoding(response) not in {None, "identity"}:
                    raise MediaIntegrityError("TikTok media response has unsupported content encoding")
                content_length = _content_length(response)
                if content_length > self.max_media_bytes:
                    raise MediaTooLargeError("TikTok media exceeds the configured byte limit")

                payload = bytearray()
                digest = hashlib.md5(usedforsecurity=False)
                async for chunk in response.aiter_raw():
                    if len(payload) + len(chunk) > self.max_media_bytes:
                        raise MediaTooLargeError("TikTok media exceeds the configured byte limit")
                    payload.extend(chunk)
                    digest.update(chunk)
        except httpx.HTTPError as exc:
            raise TransportError("Could not retrieve TikTok media") from exc

        size = len(payload)
        if size < 12 or payload[4:8] != b"ftyp":
            raise MediaIntegrityError("TikTok media is missing an MP4 ftyp box")
        if size != content_length or (expected_size is not None and size != expected_size):
            raise MediaIntegrityError("TikTok media size does not match its declared metadata")
        checksum = digest.hexdigest()
        if expected_hash is not None and checksum != expected_hash:
            raise MediaIntegrityError("TikTok media checksum does not match its rendition metadata")
        return ScrapedVideo(
            metadata=hydrated.metadata,
            media=bytes(payload),
            byte_count=size,
            md5=checksum,
            file_hash_verified=expected_hash is not None,
        )


def _media_expectations(video: Mapping[str, object], play_addr: str) -> tuple[int | None, str | None]:
    """Find size and MD5 only for the exact server-selected play address."""
    try:
        expected_size = _positive_size(video.get("size"))
        bitrate_info = video.get("bitrateInfo", [])
        if not isinstance(bitrate_info, list):
            raise TypeError("bitrateInfo is not a list")
        for rendition in bitrate_info:
            address = rendition.get("PlayAddr", {})
            urls = address.get("UrlList", [])
            if play_addr in urls:
                expected_size = _positive_size(address.get("DataSize")) or expected_size
                file_hash = address.get("FileHash")
                if file_hash is None:
                    return expected_size, None
                if not isinstance(file_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", file_hash):
                    raise ValueError("invalid FileHash")
                return expected_size, file_hash.lower()
        return expected_size, None
    except (AttributeError, OverflowError, TypeError, ValueError) as exc:
        raise ProtocolError("TikTok returned unsupported media metadata") from exc


def _positive_size(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("size must not be boolean")
    size = int(value)
    if size <= 0:
        return None
    return size


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()


def _content_encoding(response: httpx.Response) -> str | None:
    value = response.headers.get("Content-Encoding")
    return value.strip().lower() if value else None


def _content_length(response: httpx.Response) -> int:
    raw_value = response.headers.get("Content-Length")
    try:
        if raw_value is None or not raw_value.isdecimal():
            raise ValueError
        length = int(raw_value)
        if length <= 0:
            raise ValueError
        return length
    except ValueError as exc:
        raise MediaIntegrityError("TikTok media has an invalid Content-Length") from exc


async def fetch_video(
    identifier: str,
    *,
    max_media_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
    timeout: httpx.TimeoutTypes = 45.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ScrapedVideo:
    """Fetch a video using a fresh session that closes before this function returns."""
    async with TikTokScraper(
        max_media_bytes=max_media_bytes,
        timeout=timeout,
        transport=transport,
    ) as scraper:
        return await scraper.fetch_video(identifier)
