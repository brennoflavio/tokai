# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application for the Tokai web interface."""

from contextlib import asynccontextmanager
from pathlib import Path
import re
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from scraper import (
    ContentUnavailableError,
    JobCapacityError,
    MediaJobNotFoundError,
    ScraperError,
    VideoDownloadJobs,
)
from utils.env import Environment, get_required_env
from utils.logging import get_logger
from utils.urls import redact_url
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PACKAGE_DIRECTORY = Path(__file__).parent
MEDIA_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
SHORT_CODE_PATH_RE = re.compile(r"([A-Za-z0-9]+)/?")
VIDEO_PATH_RE = re.compile(r"^@[A-Za-z0-9_.]*/video/([0-9]+)/?$")
RESERVED_PATHS = frozenset({"docs", "redoc", "static", "media", "download"})
TIKTOK_VIDEO_HOSTS = frozenset({"tiktok.com", "www.tiktok.com", "m.tiktok.com"})
TIKTOK_SHORT_LINK_HOSTS = frozenset({"vm.tiktok.com", "vt.tiktok.com"})

logger = get_logger("web")


def compact_count(value: int) -> str:
    """Format a non-negative count for compact display."""
    for divisor, suffix in ((1_000_000, "M"), (1_000, "K")):
        if value >= divisor:
            return f"{value / divisor:.1f}".rstrip("0").rstrip(".") + suffix
    return str(value)


def post_links(tiktok_path: str) -> tuple[str, str]:
    """Build canonical Tokai and TikTok links for a rendered post path."""
    path = tiktok_path.strip("/")
    permalink = f"{get_required_env(Environment.TOKAI_APP_URL)}/{path}"
    if VIDEO_PATH_RE.fullmatch(path) is not None:
        return permalink, f"https://www.tiktok.com/{path}"
    if path.isdecimal():
        return permalink, f"https://www.tiktok.com/@/video/{path}"
    return permalink, f"https://vm.tiktok.com/{path}/"


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.media_jobs = VideoDownloadJobs()
    try:
        yield
    finally:
        await application.state.media_jobs.aclose()


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
app.state.media_jobs = VideoDownloadJobs()
app.mount("/static", StaticFiles(directory=PACKAGE_DIRECTORY / "static"), name="static")
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")
templates.env.filters["compact_count"] = compact_count


@app.exception_handler(404)
async def not_found(request: Request, _: HTTPException):
    """Render a consistent HTML response for missing pages."""
    return templates.TemplateResponse(
        request=request,
        name="not_found.html",
        status_code=404,
    )


def retrieval_error(
    request: Request,
    *,
    status_code: int = 502,
    title: str = "Couldn’t retrieve video",
    message: str = "TikTok could not provide this video right now. Try again later.",
):
    """Render a consistent HTML response for unavailable TikTok operations."""
    return templates.TemplateResponse(
        request=request,
        name="retrieval_error.html",
        context={"status_code": status_code, "title": title, "message": message},
        status_code=status_code,
    )


def capacity_error(request: Request):
    """Render a consistent HTML response when the in-memory queue is full."""
    return retrieval_error(
        request,
        status_code=503,
        title="Video temporarily unavailable",
        message="TokAI is busy retrieving other videos. Try again later.",
    )


@app.get("/", include_in_schema=False)
async def home(request: Request):
    """Render the initial web interface."""
    logger.debug("Rendering home page")
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/", include_in_schema=False)
async def submitted_video(request: Request, url: Annotated[str, Form()]):
    """Open a submitted TikTok video URL without retaining its query string."""
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
    except ValueError:
        logger.debug("Rejected submitted TikTok URL: invalid URL url=%s", redact_url(url))
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": "Enter a valid TikTok video URL."},
            status_code=400,
        )

    tiktok_path = parsed_url.path.lstrip("/")
    is_video_url = (
        hostname in TIKTOK_VIDEO_HOSTS
        and VIDEO_PATH_RE.fullmatch(tiktok_path) is not None
    )
    is_short_link = (
        hostname in TIKTOK_SHORT_LINK_HOSTS
        and SHORT_CODE_PATH_RE.fullmatch(tiktok_path) is not None
    )
    if not (parsed_url.scheme in {"http", "https"} and (is_video_url or is_short_link)):
        logger.debug("Rejected submitted TikTok URL: unsupported URL url=%s", redact_url(url))
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": "Enter a valid TikTok video URL."},
            status_code=400,
        )

    logger.debug(
        "Accepted submitted TikTok URL kind=%s destination_path=%s",
        "video" if is_video_url else "short_link",
        f"/{tiktok_path}",
    )
    return RedirectResponse(url=f"/{tiktok_path}", status_code=303)


@app.get("/docs", include_in_schema=False)
@app.get("/redoc", include_in_schema=False)
async def disabled_documentation():
    raise HTTPException(status_code=404, detail="Not found")


async def media_response(request: Request, media_id: str, *, download: bool) -> Response:
    if MEDIA_ID_RE.fullmatch(media_id) is None:
        logger.debug("Rejected media request: invalid media ID")
        raise HTTPException(status_code=404, detail="TikTok video not found")

    logger.debug("Fetching media job media_id=%s download=%s", media_id, download)
    try:
        scraped_video = await app.state.media_jobs.get_video(media_id)
    except (ContentUnavailableError, MediaJobNotFoundError) as error:
        logger.debug("TikTok media is unavailable error_type=%s", type(error).__name__)
        raise HTTPException(status_code=404, detail="TikTok video not found") from error
    except JobCapacityError as error:
        logger.debug("TikTok media job capacity reached error_type=%s", type(error).__name__)
        return capacity_error(request)
    except ScraperError as error:
        logger.debug("TikTok media fetch failed error_type=%s", type(error).__name__)
        return retrieval_error(request)

    logger.debug(
        "Returning media job media_id=%s byte_count=%d download=%s",
        media_id,
        len(scraped_video.media),
        download,
    )
    headers = {"Cache-Control": "private, no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{scraped_video.metadata.video_id}.mp4"'
    return Response(content=scraped_video.media, media_type="video/mp4", headers=headers)


@app.get("/media/{media_id}", include_in_schema=False)
async def media(request: Request, media_id: str):
    """Wait for an in-memory job and return its validated TikTok MP4."""
    return await media_response(request, media_id, download=False)


@app.get("/download/{media_id}", include_in_schema=False)
async def download(request: Request, media_id: str):
    """Download a validated TikTok MP4 as an attachment."""
    return await media_response(request, media_id, download=True)


@app.get("/{tiktok_path:path}", include_in_schema=False)
async def video(request: Request, tiktok_path: str):
    """Render a supported TikTok video without client-side code."""
    if tiktok_path.rstrip("/") in RESERVED_PATHS:
        logger.debug("Rejected video page: reserved path")
        raise HTTPException(status_code=404, detail="TikTok video path not found")

    match = VIDEO_PATH_RE.fullmatch(tiktok_path) or SHORT_CODE_PATH_RE.fullmatch(tiktok_path)
    if match is None:
        logger.debug("Rejected video page: unsupported path")
        raise HTTPException(status_code=404, detail="TikTok video path not found")

    identifier = match.group(1)
    logger.debug("Preparing video page identifier=%s", identifier)
    try:
        prepared_video = await app.state.media_jobs.prepare_video(identifier)
    except ContentUnavailableError as error:
        logger.debug("TikTok video is unavailable error_type=%s", type(error).__name__)
        raise HTTPException(status_code=404, detail="TikTok video not found") from error
    except JobCapacityError as error:
        logger.debug("TikTok media job capacity reached error_type=%s", type(error).__name__)
        return capacity_error(request)
    except ScraperError as error:
        logger.debug("TikTok video preparation failed error_type=%s", type(error).__name__)
        return retrieval_error(request)

    permalink, tiktok_url = post_links(tiktok_path)
    logger.debug(
        "Rendering prepared video page video_id=%s media_id=%s",
        prepared_video.metadata.video_id,
        prepared_video.media_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="video.html",
        context={
            "metadata": prepared_video.metadata,
            "media_url": request.url_for("media", media_id=prepared_video.media_id).path,
            "download_url": request.url_for("download", media_id=prepared_video.media_id).path,
            "permalink": permalink,
            "tiktok_url": tiktok_url,
        },
    )
