# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application for the Tokai web interface."""

from pathlib import Path
import re
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from scraper import ContentUnavailableError, ScraperError, fetch_video
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PACKAGE_DIRECTORY = Path(__file__).parent
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9]+")
SHORT_CODE_PATH_RE = re.compile(r"([A-Za-z0-9]+)/?")
VIDEO_PATH_RE = re.compile(r"^@[A-Za-z0-9_.]*/video/([0-9]+)/?$")
RESERVED_PATHS = frozenset({"docs", "redoc", "static", "media"})
TIKTOK_VIDEO_HOSTS = frozenset({"tiktok.com", "www.tiktok.com", "m.tiktok.com"})
TIKTOK_SHORT_LINK_HOSTS = frozenset({"vm.tiktok.com", "vt.tiktok.com"})

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=PACKAGE_DIRECTORY / "static"), name="static")
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")


@app.exception_handler(404)
async def not_found(request: Request, _: HTTPException):
    """Render a consistent HTML response for missing pages."""
    return templates.TemplateResponse(
        request=request,
        name="not_found.html",
        status_code=404,
    )


@app.get("/", include_in_schema=False)
async def home(request: Request):
    """Render the initial web interface."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/", include_in_schema=False)
async def submitted_video(request: Request, url: Annotated[str, Form()]):
    """Open a submitted TikTok video URL without retaining its query string."""
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
    except ValueError:
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
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": "Enter a valid TikTok video URL."},
            status_code=400,
        )

    return RedirectResponse(url=f"/{tiktok_path}", status_code=303)


@app.get("/docs", include_in_schema=False)
@app.get("/redoc", include_in_schema=False)
async def disabled_documentation():
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/media/{identifier}", include_in_schema=False)
async def media(identifier: str):
    """Retrieve a validated TikTok MP4 for the video element."""
    if IDENTIFIER_RE.fullmatch(identifier) is None:
        raise HTTPException(status_code=404, detail="TikTok video not found")

    try:
        scraped_video = await fetch_video(identifier)
    except ContentUnavailableError as error:
        raise HTTPException(status_code=404, detail="TikTok video not found") from error
    except ScraperError as error:
        raise HTTPException(status_code=502, detail="TikTok video could not be retrieved") from error

    return Response(content=scraped_video.media, media_type="video/mp4")


@app.get("/{tiktok_path:path}", include_in_schema=False)
async def video(request: Request, tiktok_path: str):
    """Render a supported TikTok video without client-side code."""
    if tiktok_path.rstrip("/") in RESERVED_PATHS:
        raise HTTPException(status_code=404, detail="TikTok video path not found")

    match = VIDEO_PATH_RE.fullmatch(tiktok_path) or SHORT_CODE_PATH_RE.fullmatch(tiktok_path)
    if match is None:
        raise HTTPException(status_code=404, detail="TikTok video path not found")

    return templates.TemplateResponse(
        request=request,
        name="video.html",
        context={"media_url": request.url_for("media", identifier=match.group(1)).path},
    )
