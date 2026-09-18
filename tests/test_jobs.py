# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import pytest

from scraper import JobCapacityError, MediaIntegrityError, MediaJobNotFoundError, VideoDownloadJobs

VIDEO_ID = "1234567890"
SIGNED_URL = "https://cdn.tiktok.com/video.mp4?token=one"
MP4 = b"\x00\x00\x00\x0cftypisomdata"


def hydration_html() -> str:
    item = {
        "id": VIDEO_ID,
        "desc": "A public caption",
        "author": {"uniqueId": "creator", "nickname": "Creator Name"},
        "stats": {},
        "video": {
            "playAddr": SIGNED_URL,
            "format": "mp4",
            "size": len(MP4),
            "bitrateInfo": [
                {
                    "PlayAddr": {
                        "UrlList": [SIGNED_URL],
                        "DataSize": len(MP4),
                        "FileHash": hashlib.md5(MP4, usedforsecurity=False).hexdigest(),
                    }
                }
            ],
        },
    }
    data = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": 0, "itemInfo": {"itemStruct": item}}}}
    return f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{json.dumps(data)}</script>'


class BytesStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield MP4

    async def aclose(self) -> None:
        pass


def media_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        stream=BytesStream(),
        headers={"Content-Type": "video/mp4", "Content-Length": str(len(MP4))},
        request=request,
    )


@pytest.mark.anyio
async def test_job_returns_metadata_then_downloads_with_the_page_cookie() -> None:
    requests: list[httpx.Request] = []
    media_started = asyncio.Event()
    release_media = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "www.tiktok.com":
            return httpx.Response(
                200,
                content=hydration_html().encode(),
                headers={
                    "Content-Type": "text/html",
                    "Set-Cookie": "tt_chain_token=session; Domain=.tiktok.com; Path=/; Secure",
                },
                request=request,
            )
        media_started.set()
        await release_media.wait()
        assert "tt_chain_token=session" in request.headers["cookie"]
        return media_response(request)

    jobs = VideoDownloadJobs(transport=httpx.MockTransport(handler))
    try:
        prepared = await jobs.prepare_video(VIDEO_ID)
        assert prepared.metadata.video_id == VIDEO_ID
        assert prepared.metadata.caption == "A public caption"
        assert len(requests) == 1

        await media_started.wait()
        response_task = asyncio.create_task(jobs.get_video(prepared.media_id))
        release_media.set()
        result = await response_task

        assert result.media == MP4
        assert [request.url.host for request in requests] == ["www.tiktok.com", "cdn.tiktok.com"]
    finally:
        await jobs.aclose()


@pytest.mark.anyio
async def test_unclaimed_job_is_cancelled_and_removed_after_its_ttl() -> None:
    media_cancelled = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return httpx.Response(
                200,
                content=hydration_html().encode(),
                headers={"Content-Type": "text/html"},
                request=request,
            )
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            media_cancelled.set()
            raise

    jobs = VideoDownloadJobs(job_ttl_seconds=0.01, transport=httpx.MockTransport(handler))
    try:
        prepared = await jobs.prepare_video(VIDEO_ID)
        await asyncio.wait_for(media_cancelled.wait(), timeout=1)
        with pytest.raises(MediaJobNotFoundError):
            await jobs.get_video(prepared.media_id)
    finally:
        await jobs.aclose()


@pytest.mark.anyio
async def test_claimed_completed_job_is_reused_before_its_retry_ttl() -> None:
    media_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal media_requests
        if request.url.host == "www.tiktok.com":
            return httpx.Response(
                200,
                content=hydration_html().encode(),
                headers={"Content-Type": "text/html"},
                request=request,
            )
        media_requests += 1
        return media_response(request)

    jobs = VideoDownloadJobs(completed_ttl_seconds=1, transport=httpx.MockTransport(handler))
    try:
        prepared = await jobs.prepare_video(VIDEO_ID)
        first = await jobs.get_video(prepared.media_id)
        second = await jobs.get_video(prepared.media_id)

        assert first.media == second.media == MP4
        assert media_requests == 1
    finally:
        await jobs.aclose()


@pytest.mark.anyio
async def test_job_capacity_limits_active_jobs() -> None:
    release_media = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return httpx.Response(
                200,
                content=hydration_html().encode(),
                headers={"Content-Type": "text/html"},
                request=request,
            )
        await release_media.wait()
        return media_response(request)

    jobs = VideoDownloadJobs(max_jobs=1, transport=httpx.MockTransport(handler))
    try:
        await jobs.prepare_video(VIDEO_ID)
        with pytest.raises(JobCapacityError):
            await jobs.prepare_video("9876543210")
    finally:
        release_media.set()
        await jobs.aclose()


@pytest.mark.anyio
async def test_job_capacity_reserves_a_slot_before_metadata_fetch() -> None:
    page_started = asyncio.Event()
    release_page = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            page_started.set()
            await release_page.wait()
            return httpx.Response(
                200,
                content=hydration_html().encode(),
                headers={"Content-Type": "text/html"},
                request=request,
            )
        return media_response(request)

    jobs = VideoDownloadJobs(max_jobs=1, transport=httpx.MockTransport(handler))
    try:
        first = asyncio.create_task(jobs.prepare_video(VIDEO_ID))
        await page_started.wait()
        with pytest.raises(JobCapacityError):
            await jobs.prepare_video("9876543210")
        release_page.set()
        await first
    finally:
        await jobs.aclose()


@pytest.mark.anyio
async def test_close_cancels_a_pending_preparation() -> None:
    page_started = asyncio.Event()
    page_cancelled = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        page_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            page_cancelled.set()
            raise

    jobs = VideoDownloadJobs(transport=httpx.MockTransport(handler))
    preparation = asyncio.create_task(jobs.prepare_video(VIDEO_ID))
    await page_started.wait()

    await jobs.aclose()

    with pytest.raises(asyncio.CancelledError):
        await preparation
    assert page_cancelled.is_set()


@pytest.mark.anyio
async def test_failed_download_does_not_retain_a_traceback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return httpx.Response(
                200,
                content=hydration_html().encode(),
                headers={"Content-Type": "text/html"},
                request=request,
            )
        return httpx.Response(
            200,
            stream=BytesStream(),
            headers={"Content-Type": "text/html", "Content-Length": str(len(MP4))},
            request=request,
        )

    jobs = VideoDownloadJobs(transport=httpx.MockTransport(handler))
    try:
        prepared = await jobs.prepare_video(VIDEO_ID)
        with pytest.raises(MediaIntegrityError):
            await jobs.get_video(prepared.media_id)

        error = jobs._jobs[prepared.media_id].error
        assert isinstance(error, MediaIntegrityError)
        assert error.__traceback__ is None
    finally:
        await jobs.aclose()


@pytest.mark.anyio
async def test_completed_media_limit_does_not_evict_a_valid_existing_job() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tiktok.com":
            return httpx.Response(
                200,
                content=hydration_html().encode(),
                headers={"Content-Type": "text/html"},
                request=request,
            )
        return media_response(request)

    jobs = VideoDownloadJobs(
        max_completed_media_bytes=len(MP4),
        transport=httpx.MockTransport(handler),
    )
    try:
        first = await jobs.prepare_video(VIDEO_ID)
        assert (await jobs.get_video(first.media_id)).media == MP4

        second = await jobs.prepare_video(VIDEO_ID)
        with pytest.raises(JobCapacityError):
            await jobs.get_video(second.media_id)

        assert (await jobs.get_video(first.media_id)).media == MP4
    finally:
        await jobs.aclose()
