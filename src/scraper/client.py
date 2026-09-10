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
    ScraperError,
    TransportError,
)
from .hydration import HydratedVideo, parse_hydration
from .identifiers import Identifier, parse_identifier, validate_redirect_target, video_id_from_page_url
from .models import ScrapedVideo
from utils.logging import get_logger
from utils.urls import redact_url

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

logger = get_logger("scraper")


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
        logger.debug("Opened scraper session max_media_bytes=%d", self.max_media_bytes)
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
            logger.debug("Closed scraper session")

    @property
    def _session(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use TikTokScraper as an async context manager")
        return self._client

    async def _get_page(self, url: str, expected_id: str | None) -> tuple[str, str]:
        """Resolve a generated page route manually and return its final document."""
        for redirect_count in range(MAX_REDIRECTS + 1):
            logger.debug(
                "Requesting TikTok page redirect_count=%d url=%s expected_id=%s",
                redirect_count,
                redact_url(url),
                expected_id,
            )
            try:
                response = await self._session.get(url, headers=PAGE_HEADERS)
            except httpx.RemoteProtocolError as exc:
                logger.debug("TikTok page protocol error error_type=%s", type(exc).__name__)
                raise ProtocolError("TikTok page redirect is invalid") from exc
            except httpx.HTTPError as exc:
                logger.debug("TikTok page transport error error_type=%s", type(exc).__name__)
                raise TransportError("Could not retrieve TikTok video page") from exc

            logger.debug(
                "Received TikTok page status_code=%d url=%s is_redirect=%s",
                response.status_code,
                redact_url(str(response.url)),
                response.is_redirect,
            )
            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    logger.debug("TikTok page redirect is missing a location")
                    raise ProtocolError("TikTok redirect did not include a location")
                url = urljoin(str(response.url), location)
                logger.debug("Following TikTok page redirect target=%s", redact_url(url))
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
            logger.debug(
                "Resolved TikTok page video_id=%s html_bytes=%d",
                resolved_id,
                len(response.content),
            )
            return str(response.url), response.text
        raise ProtocolError("TikTok redirect limit exceeded")

    async def fetch_video(self, identifier: str) -> ScrapedVideo:
        """Retrieve one public post as a verified, bounded in-memory MP4."""
        try:
            parsed = parse_identifier(identifier)
            logger.debug(
                "Started scraper fetch identifier=%s identifier_kind=%s",
                parsed.value,
                "video_id" if parsed.is_video_id else "short_code",
            )
            async with self._fetch_lock:
                logger.debug("Acquired scraper fetch lock")
                result = await self._fetch_identifier(parsed)
        except ScraperError as exc:
            logger.debug("Scraper fetch failed error_type=%s error=%s", type(exc).__name__, exc)
            raise
        except Exception as exc:
            logger.debug("Scraper fetch failed unexpectedly error_type=%s", type(exc).__name__)
            raise
        logger.debug(
            "Completed scraper fetch video_id=%s byte_count=%d checksum_verified=%s",
            result.metadata.video_id,
            result.byte_count,
            result.file_hash_verified,
        )
        return result

    async def _fetch_identifier(self, identifier: Identifier) -> ScrapedVideo:
        expected_id = identifier.value if identifier.is_video_id else None
        page_url, html = await self._get_page(identifier.initial_url, expected_id)
        expected_id = video_id_from_page_url(page_url)
        assert expected_id is not None  # guaranteed by _get_page

        for attempt in range(2):
            logger.debug("Parsing TikTok hydration attempt=%d video_id=%s", attempt + 1, expected_id)
            hydrated = parse_hydration(html, expected_id)
            if hydrated is not None:
                logger.debug("Validated TikTok hydration video_id=%s", hydrated.metadata.video_id)
                return await self._download_media(hydrated)
            if attempt == 0 and 'data-source="downgrade-mssdk-preload"' in html:
                logger.debug("Retrying TikTok hydration after app-shell response delay_seconds=1")
                await asyncio.sleep(1)
                page_url, html = await self._get_page(page_url, expected_id)
                continue
            logger.debug("TikTok hydration data is missing attempt=%d", attempt + 1)
            raise ProtocolError("TikTok page has no video hydration data")
        raise AssertionError("unreachable")

    async def _download_media(self, hydrated: HydratedVideo) -> ScrapedVideo:
        expected_size, expected_hash = _media_expectations(hydrated.video, hydrated.play_addr)
        logger.debug(
            "Prepared TikTok media download url=%s expected_size=%s checksum_expected=%s",
            redact_url(hydrated.play_addr),
            expected_size,
            expected_hash is not None,
        )
        if expected_size is not None and expected_size > self.max_media_bytes:
            raise MediaTooLargeError("TikTok media exceeds the configured byte limit")

        try:
            logger.debug("Requesting TikTok media url=%s", redact_url(hydrated.play_addr))
            async with self._session.stream(
                "GET", hydrated.play_addr, headers=MEDIA_HEADERS
            ) as response:
                logger.debug(
                    "Received TikTok media status_code=%d content_type=%s content_encoding=%s content_length=%s",
                    response.status_code,
                    _content_type(response),
                    _content_encoding(response),
                    response.headers.get("Content-Length"),
                )
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
                chunk_count = 0
                async for chunk in response.aiter_raw():
                    if len(payload) + len(chunk) > self.max_media_bytes:
                        raise MediaTooLargeError("TikTok media exceeds the configured byte limit")
                    payload.extend(chunk)
                    digest.update(chunk)
                    chunk_count += 1
        except httpx.HTTPError as exc:
            logger.debug("TikTok media transport error error_type=%s", type(exc).__name__)
            raise TransportError("Could not retrieve TikTok media") from exc

        size = len(payload)
        if size < 12 or payload[4:8] != b"ftyp":
            raise MediaIntegrityError("TikTok media is missing an MP4 ftyp box")
        if size != content_length or (expected_size is not None and size != expected_size):
            raise MediaIntegrityError("TikTok media size does not match its declared metadata")
        checksum = digest.hexdigest()
        if expected_hash is not None and checksum != expected_hash:
            raise MediaIntegrityError("TikTok media checksum does not match its rendition metadata")
        logger.debug(
            "Validated TikTok media byte_count=%d chunk_count=%d checksum_verified=%s",
            size,
            chunk_count,
            expected_hash is not None,
        )
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
