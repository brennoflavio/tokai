# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from scraper import (
    ContentUnavailableError,
    InvalidIdentifierError,
    MediaIntegrityError,
    MediaTooLargeError,
    ProtocolError,
    TikTokScraper,
    TransportError,
    fetch_video,
)

VIDEO_ID = "1234567890"
SIGNED_URL = "https://cdn.tiktok.com/video.mp4?token=one&&signature=two"
MP4 = b"\x00\x00\x00\x0cftypisomdata"


def hydration_html(**overrides: object) -> str:
    video = {
        "playAddr": SIGNED_URL,
        "format": "mp4",
        "size": len(MP4),
        "duration": 12.5,
        "width": 576,
        "height": 1024,
        "codecType": "h264",
        "bitrateInfo": [
            {
                "PlayAddr": {
                    "UrlList": [SIGNED_URL],
                    "DataSize": len(MP4),
                    "FileHash": hashlib.md5(MP4, usedforsecurity=False).hexdigest(),
                }
            }
        ],
    }
    item = {
        "id": VIDEO_ID,
        "desc": "A public caption",
        "createTime": 1_700_000_000,
        "author": {"uniqueId": "creator", "nickname": "Creator Name"},
        "stats": {"commentCount": 1, "diggCount": 2, "playCount": 3, "shareCount": 4},
        "video": video,
    }
    for key, value in overrides.items():
        if key == "video":
            video.update(value)  # type: ignore[arg-type]
        else:
            item[key] = value
    data = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": 0, "itemInfo": {"itemStruct": item}}}}
    return f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{json.dumps(data)}</script>'


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self):
        yield self.content

    async def aclose(self) -> None:
        pass


def response(request: httpx.Request, *, content: bytes = MP4, **headers: str) -> httpx.Response:
    return httpx.Response(200, headers=headers, stream=BytesStream(content), request=request)


@pytest.mark.anyio
async def test_numeric_identifier_returns_redacted_metadata_and_verified_media() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "www.tiktok.com":
            return response(request, content=hydration_html().encode(), **{"Content-Type": "text/html"})
        return response(
            request,
            **{"Content-Type": "video/mp4", "Content-Length": str(len(MP4))},
        )

    result = await fetch_video(VIDEO_ID, transport=httpx.MockTransport(handler))

    assert result.media == MP4
    assert result.byte_count == len(MP4)
    assert result.md5 == hashlib.md5(MP4, usedforsecurity=False).hexdigest()
    assert result.file_hash_verified is True
    assert result.metadata.video_id == VIDEO_ID
    assert result.metadata.author_handle == "creator"
    assert result.metadata.author_display_name == "Creator Name"
    assert result.metadata.created_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert result.metadata.play_count == 3
    assert not hasattr(result, "play_addr")
    assert str(requests[0].url) == f"https://www.tiktok.com/@/video/{VIDEO_ID}"


@pytest.mark.anyio
async def test_debug_logging_records_scrape_lifecycle_without_signed_query_values(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return response(request, content=hydration_html().encode(), **{"Content-Type": "text/html"})
        return response(
            request,
            **{"Content-Type": "video/mp4", "Content-Length": str(len(MP4))},
        )

    tokai_logger = logging.getLogger("tokai")
    tokai_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG, logger="tokai"):
            await fetch_video(VIDEO_ID, transport=httpx.MockTransport(handler))
    finally:
        tokai_logger.removeHandler(caplog.handler)

    messages = caplog.messages
    assert any(message.startswith("Started scraper fetch") for message in messages)
    assert any(message.startswith("Requesting TikTok page") for message in messages)
    assert any(message.startswith("Resolved TikTok page") for message in messages)
    assert any(message.startswith("Validated TikTok hydration") for message in messages)
    assert any(message.startswith("Received TikTok media") for message in messages)
    assert any(message.startswith("Validated TikTok media") for message in messages)
    assert any(message.startswith("Completed scraper fetch") for message in messages)
    assert SIGNED_URL not in caplog.text
    assert "https://cdn.tiktok.com/video.mp4" in caplog.text


@pytest.mark.anyio
async def test_short_code_redirect_keeps_page_cookie_referer_and_signed_url() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "vm.tiktok.com":
            return httpx.Response(
                302,
                headers={"Location": f"https://www.tiktok.com/@/video/{VIDEO_ID}"},
                request=request,
            )
        if request.url.host == "www.tiktok.com":
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "text/html",
                    "Set-Cookie": "tt_chain_token=session; Domain=.tiktok.com; Path=/; Secure",
                },
                content=hydration_html().encode(),
                request=request,
            )
        assert str(request.url) == SIGNED_URL
        assert request.headers["referer"] == "https://www.tiktok.com/"
        assert request.headers["accept-encoding"] == "identity"
        assert "tt_chain_token=session" in request.headers["cookie"]
        return response(
            request,
            **{"Content-Type": "video/mp4", "Content-Length": str(len(MP4))},
        )

    result = await fetch_video("Ztest9", transport=httpx.MockTransport(handler))

    assert result.metadata.video_id == VIDEO_ID
    assert [request.url.host for request in requests] == [
        "vm.tiktok.com",
        "www.tiktok.com",
        "cdn.tiktok.com",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("identifier", ["", "https://www.tiktok.com/@a/video/1", "short-code", "äbc"])
async def test_invalid_identifiers_are_rejected_without_requests(identifier: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.url}")

    with pytest.raises(InvalidIdentifierError):
        await fetch_video(identifier, transport=httpx.MockTransport(handler))


@pytest.mark.anyio
@pytest.mark.parametrize("location", ["https://example.com/", f"https://www.tiktok.com:bad/@/video/{VIDEO_ID}"])
async def test_unsafe_redirect_is_rejected(location: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": location}, request=request)

    with pytest.raises(ProtocolError):
        await fetch_video("Ztest9", transport=httpx.MockTransport(handler))


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("html", "error"),
    [
        (hydration_html(id="999"), ContentUnavailableError),
        (hydration_html(privateItem=True), ContentUnavailableError),
        ("<html>no hydration</html>", ProtocolError),
        (
            '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{not json}</script>',
            ProtocolError,
        ),
        (hydration_html(video={"playAddr": "https://token@cdn.tiktok.com/video.mp4"}), ProtocolError),
    ],
)
async def test_hydration_identity_availability_and_schema_failures(
    html: str, error: type[Exception]
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response(request, content=html.encode(), **{"Content-Type": "text/html"})

    with pytest.raises(error):
        await fetch_video(VIDEO_ID, transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_only_recognized_app_shell_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    page_requests = 0

    async def no_wait(seconds: float) -> None:
        assert seconds == 1

    monkeypatch.setattr("scraper.client.asyncio.sleep", no_wait)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_requests
        if request.url.host == "www.tiktok.com":
            page_requests += 1
            html = 'data-source="downgrade-mssdk-preload"' if page_requests == 1 else hydration_html()
            return response(request, content=html.encode(), **{"Content-Type": "text/html"})
        return response(request, **{"Content-Type": "video/mp4", "Content-Length": str(len(MP4))})

    result = await fetch_video(VIDEO_ID, transport=httpx.MockTransport(handler))
    assert result.media == MP4
    assert page_requests == 2


@pytest.mark.anyio
async def test_repeated_recognized_shell_fails_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(seconds: float) -> None:
        pass

    monkeypatch.setattr("scraper.client.asyncio.sleep", no_wait)
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return response(
            request,
            content=b'data-source="downgrade-mssdk-preload"',
            **{"Content-Type": "text/html"},
        )

    with pytest.raises(ProtocolError, match="no video hydration"):
        await fetch_video(VIDEO_ID, transport=httpx.MockTransport(handler))
    assert requests == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("video_overrides", "media", "headers", "limit", "error"),
    [
        ({"bitrateInfo": [{"PlayAddr": {"UrlList": [SIGNED_URL], "DataSize": len(MP4) + 1, "FileHash": hashlib.md5(MP4, usedforsecurity=False).hexdigest()}}]}, MP4, {"Content-Type": "video/mp4", "Content-Length": str(len(MP4))}, 100, MediaIntegrityError),
        ({}, b"not-an-mp4", {"Content-Type": "video/mp4", "Content-Length": "10"}, 100, MediaIntegrityError),
        ({}, MP4, {"Content-Type": "text/html", "Content-Length": str(len(MP4))}, 100, MediaIntegrityError),
        ({}, MP4, {"Content-Type": "video/mp4", "Content-Length": str(len(MP4))}, len(MP4) - 1, MediaTooLargeError),
        ({"bitrateInfo": [{"PlayAddr": {"UrlList": [SIGNED_URL], "DataSize": len(MP4), "FileHash": "0" * 32}}]}, MP4, {"Content-Type": "video/mp4", "Content-Length": str(len(MP4))}, 100, MediaIntegrityError),
    ],
)
async def test_media_validation_failures(
    video_overrides: dict[str, object], media: bytes, headers: dict[str, str], limit: int, error: type[Exception]
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return response(request, content=hydration_html(video=video_overrides).encode(), **{"Content-Type": "text/html"})
        return response(request, content=media, **headers)

    with pytest.raises(error):
        await fetch_video(VIDEO_ID, max_media_bytes=limit, transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_streaming_limit_and_content_encoding_are_rejected() -> None:
    async def oversized_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return response(request, content=hydration_html().encode(), **{"Content-Type": "text/html"})
        return response(
            request,
            content=MP4 + b"x" * 20,
            **{"Content-Type": "video/mp4", "Content-Length": str(len(MP4))},
        )

    with pytest.raises(MediaTooLargeError):
        await fetch_video(VIDEO_ID, max_media_bytes=20, transport=httpx.MockTransport(oversized_handler))

    async def encoded_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return response(request, content=hydration_html().encode(), **{"Content-Type": "text/html"})
        return response(
            request,
            **{
                "Content-Type": "video/mp4",
                "Content-Length": str(len(MP4)),
                "Content-Encoding": "gzip",
            },
        )

    with pytest.raises(MediaIntegrityError, match="content encoding"):
        await fetch_video(VIDEO_ID, transport=httpx.MockTransport(encoded_handler))


@pytest.mark.anyio
async def test_page_http_failure_is_a_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with pytest.raises(TransportError):
        await fetch_video(VIDEO_ID, transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_context_serializes_cookie_bound_fetch_chains() -> None:
    active_pages = 0
    maximum_active_pages = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_pages, maximum_active_pages
        if request.url.host == "www.tiktok.com":
            active_pages += 1
            maximum_active_pages = max(maximum_active_pages, active_pages)
            await asyncio.sleep(0)
            active_pages -= 1
            identifier = request.url.path.rsplit("/", 1)[-1]
            return response(
                request,
                content=hydration_html(id=identifier).encode(),
                **{"Content-Type": "text/html"},
            )
        return response(
            request,
            **{"Content-Type": "video/mp4", "Content-Length": str(len(MP4))},
        )

    async with TikTokScraper(transport=httpx.MockTransport(handler)) as scraper:
        results = await asyncio.gather(
            scraper.fetch_video(VIDEO_ID), scraper.fetch_video("9876543210")
        )

    assert [result.metadata.video_id for result in results] == [VIDEO_ID, "9876543210"]
    assert maximum_active_pages == 1


@pytest.mark.anyio
async def test_context_manager_requires_an_open_session() -> None:
    scraper = TikTokScraper(transport=httpx.MockTransport(lambda request: None))
    with pytest.raises(RuntimeError, match="async context manager"):
        await scraper.fetch_video(VIDEO_ID)
