# SPDX-License-Identifier: AGPL-3.0-or-later
"""Short-lived, in-memory TikTok media download jobs."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass

import httpx

from .client import DEFAULT_MAX_MEDIA_BYTES, TikTokScraper
from .errors import JobCapacityError, MediaJobNotFoundError, ScraperError, TransportError
from .hydration import HydratedVideo
from .models import PreparedVideo, ScrapedVideo

DEFAULT_JOB_TTL_SECONDS = 5 * 60
DEFAULT_COMPLETED_TTL_SECONDS = DEFAULT_JOB_TTL_SECONDS
DEFAULT_MAX_JOBS = 10
DEFAULT_MAX_COMPLETED_MEDIA_BYTES = 500 * 1024 * 1024
DEFAULT_MAX_DOWNLOAD_SECONDS = 60.0


@dataclass(slots=True)
class _VideoJob:
    media_id: str
    prepared: PreparedVideo
    scraper: TikTokScraper
    hydrated: HydratedVideo | None
    created_at: float
    download_task: asyncio.Task[None] | None = None
    expiry_task: asyncio.Task[None] | None = None
    claimed: bool = False
    result: ScrapedVideo | None = None
    error: Exception | None = None


class VideoDownloadJobs:
    """Own short-lived scraper sessions and their asynchronous media downloads."""

    def __init__(
        self,
        *,
        job_ttl_seconds: float = DEFAULT_JOB_TTL_SECONDS,
        completed_ttl_seconds: float = DEFAULT_COMPLETED_TTL_SECONDS,
        max_jobs: int = DEFAULT_MAX_JOBS,
        max_completed_media_bytes: int = DEFAULT_MAX_COMPLETED_MEDIA_BYTES,
        max_download_seconds: float = DEFAULT_MAX_DOWNLOAD_SECONDS,
        max_media_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
        timeout: httpx.TimeoutTypes = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if job_ttl_seconds <= 0 or completed_ttl_seconds <= 0 or max_download_seconds <= 0:
            raise ValueError("job TTLs and download duration must be positive")
        if max_jobs <= 0 or max_completed_media_bytes <= 0:
            raise ValueError("job limits must be positive")
        self._job_ttl_seconds = job_ttl_seconds
        self._completed_ttl_seconds = completed_ttl_seconds
        self._max_jobs = max_jobs
        self._max_completed_media_bytes = max_completed_media_bytes
        self._max_download_seconds = max_download_seconds
        self._max_media_bytes = max_media_bytes
        self._timeout = timeout
        self._transport = transport
        self._jobs: dict[str, _VideoJob] = {}
        self._pending_preparations: set[asyncio.Task[object]] = set()
        self._completed_media_bytes = 0
        self._lock = asyncio.Lock()
        self._closed = False

    async def prepare_video(self, identifier: str) -> PreparedVideo:
        """Prepare metadata, start its download, and return an opaque media handle."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("VideoDownloadJobs requires an asyncio task")
        async with self._lock:
            self._ensure_open()
            if len(self._jobs) + len(self._pending_preparations) >= self._max_jobs:
                raise JobCapacityError("The media download queue is full")
            self._pending_preparations.add(task)

        scraper = TikTokScraper(
            max_media_bytes=self._max_media_bytes,
            timeout=self._timeout,
            transport=self._transport,
        )
        registered = False
        try:
            await scraper.__aenter__()
            hydrated = await scraper.prepare_video(identifier)
            media_id = secrets.token_urlsafe(18)
            prepared = PreparedVideo(metadata=hydrated.metadata, media_id=media_id)
            job = _VideoJob(
                media_id=media_id,
                prepared=prepared,
                scraper=scraper,
                hydrated=hydrated,
                created_at=time.monotonic(),
            )
            async with self._lock:
                self._ensure_open()
                self._jobs[media_id] = job
                job.download_task = asyncio.create_task(self._download(job), name=f"tokai-media-{media_id}")
                job.expiry_task = asyncio.create_task(
                    self._expire_unclaimed(media_id), name=f"tokai-media-expiry-{media_id}"
                )
                registered = True
            return prepared
        finally:
            if not registered:
                await scraper.__aexit__(None, None, None)
            async with self._lock:
                self._pending_preparations.discard(task)

    async def get_video(self, media_id: str) -> ScrapedVideo:
        """Claim a media job and wait for its validated MP4 result."""
        async with self._lock:
            job = self._jobs.get(media_id)
            if job is None:
                raise MediaJobNotFoundError("TikTok media job was not found")
            if not job.claimed:
                job.claimed = True
                self._cancel_task(job.expiry_task)
                job.expiry_task = None
                if job.download_task is not None and job.download_task.done():
                    self._schedule_completed_expiry(job)
            download_task = job.download_task

        assert download_task is not None
        await asyncio.shield(download_task)

        async with self._lock:
            job = self._jobs.get(media_id)
            if job is None:
                raise MediaJobNotFoundError("TikTok media job was not found")
            if job.error is not None:
                raise self._stored_error(job.error)
            if job.result is None:
                raise MediaJobNotFoundError("TikTok media job has expired")
            return job.result

    async def aclose(self) -> None:
        """Cancel all jobs and release their scraper sessions."""
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            jobs = list(self._jobs.values())
            preparations = [
                task for task in self._pending_preparations if task is not asyncio.current_task()
            ]
            self._jobs.clear()
            self._pending_preparations.clear()
            self._completed_media_bytes = 0
            for job in jobs:
                job.result = None
                job.hydrated = None
                self._cancel_task(job.expiry_task)
                self._cancel_task(job.download_task)
            for preparation in preparations:
                self._cancel_task(preparation)
        await asyncio.gather(
            *(job.download_task for job in jobs if job.download_task is not None),
            *preparations,
            return_exceptions=True,
        )

    async def _download(self, job: _VideoJob) -> None:
        try:
            assert job.hydrated is not None
            async with asyncio.timeout(self._max_download_seconds):
                result = await job.scraper.download_prepared(job.hydrated)
        except asyncio.TimeoutError:
            error: Exception | None = TransportError("TikTok media download exceeded its time limit")
            result = None
        except asyncio.CancelledError:
            return
        except Exception as exc:
            error = self._stored_error(exc)
            result = None
        else:
            error = None
        finally:
            await job.scraper.__aexit__(None, None, None)

        async with self._lock:
            if self._jobs.get(job.media_id) is not job:
                return
            job.hydrated = None
            if error is not None:
                job.error = error
            elif result is not None:
                if result.byte_count > self._max_completed_media_bytes:
                    job.error = JobCapacityError("The completed media memory limit was reached")
                else:
                    self._evict_unclaimed_completed_jobs(result.byte_count)
                    if self._completed_media_bytes + result.byte_count > self._max_completed_media_bytes:
                        job.error = JobCapacityError("The completed media memory limit was reached")
                    else:
                        job.result = result
                        self._completed_media_bytes += result.byte_count
            if job.claimed:
                self._schedule_completed_expiry(job)

    async def _expire_unclaimed(self, media_id: str) -> None:
        await asyncio.sleep(self._job_ttl_seconds)
        async with self._lock:
            job = self._jobs.get(media_id)
            if job is None or job.claimed:
                return
            self._remove_job(job)
            self._cancel_task(job.download_task)

    async def _expire_completed(self, media_id: str) -> None:
        await asyncio.sleep(self._completed_ttl_seconds)
        async with self._lock:
            job = self._jobs.get(media_id)
            if job is not None and job.claimed:
                self._remove_job(job)

    def _schedule_completed_expiry(self, job: _VideoJob) -> None:
        if job.expiry_task is None:
            job.expiry_task = asyncio.create_task(
                self._expire_completed(job.media_id), name=f"tokai-media-completed-expiry-{job.media_id}"
            )

    def _evict_unclaimed_completed_jobs(self, required_bytes: int) -> None:
        candidates = sorted(
            (job for job in self._jobs.values() if not job.claimed and job.result is not None),
            key=lambda job: job.created_at,
        )
        for job in candidates:
            if self._completed_media_bytes + required_bytes <= self._max_completed_media_bytes:
                break
            self._remove_job(job)
            self._cancel_task(job.expiry_task)

    def _remove_job(self, job: _VideoJob) -> None:
        self._jobs.pop(job.media_id, None)
        if job.result is not None:
            self._completed_media_bytes -= job.result.byte_count
            job.result = None
        job.hydrated = None

    @staticmethod
    def _stored_error(error: Exception) -> ScraperError:
        """Retain a lightweight domain error without its traceback and local buffers."""
        if isinstance(error, ScraperError):
            return type(error)(str(error))
        return TransportError("Could not retrieve TikTok media")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("VideoDownloadJobs is closed")

    @staticmethod
    def _cancel_task(task: asyncio.Task[None] | None) -> None:
        if task is not None and not task.done():
            task.cancel()
