# SPDX-License-Identifier: AGPL-3.0-or-later
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from scraper import ContentUnavailableError, JobCapacityError, TransportError

from web.app import app, compact_count, post_links

client = TestClient(app)


class FakeMediaJobs:
    def __init__(
        self,
        *,
        media: bytes = b"video",
        error: Exception | None = None,
        prepare_error: Exception | None = None,
    ) -> None:
        self.media = media
        self.error = error
        self.prepare_error = prepare_error
        self.prepared_identifiers: list[str] = []
        self.media_ids: list[str] = []

    async def prepare_video(self, identifier: str) -> SimpleNamespace:
        self.prepared_identifiers.append(identifier)
        if self.prepare_error is not None:
            raise self.prepare_error
        return SimpleNamespace(
            media_id="media-job",
            metadata=SimpleNamespace(
                video_id=identifier,
                caption="A public caption",
                author_display_name="Creator Name",
                author_handle="creator",
                created_at=datetime(2023, 11, 14, tzinfo=UTC),
                digg_count=1_100_000,
                play_count=12_500_000,
                share_count=114_600,
            ),
        )

    async def get_video(self, media_id: str) -> SimpleNamespace:
        self.media_ids.append(media_id)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            media=self.media,
            byte_count=len(self.media),
            metadata=SimpleNamespace(video_id="1234567890"),
        )


def use_fake_jobs(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> FakeMediaJobs:
    jobs = FakeMediaJobs(**kwargs)
    monkeypatch.setattr(app.state, "media_jobs", jobs)
    return jobs


@pytest.mark.parametrize(
    ("value", "expected"),
    [(999, "999"), (1_100, "1.1K"), (1_100_000, "1.1M"), (12_500_000, "12.5M")],
)
def test_compact_count(value: int, expected: str) -> None:
    assert compact_count(value) == expected


def test_post_links_use_the_configured_app_url_and_canonical_tiktok_hosts(monkeypatch) -> None:
    monkeypatch.setenv("TOKAI_APP_URL", "https://tokai.example.com/tokai/")

    assert post_links("@creator/video/123/") == post_links("@creator/video/123") == (
        "https://tokai.example.com/tokai/@creator/video/123",
        "https://www.tiktok.com/@creator/video/123",
    )
    assert post_links("ZMAj83k4w/") == post_links("ZMAj83k4w") == (
        "https://tokai.example.com/tokai/ZMAj83k4w",
        "https://vm.tiktok.com/ZMAj83k4w/",
    )
    assert post_links("123/") == (
        "https://tokai.example.com/tokai/123",
        "https://www.tiktok.com/@/video/123",
    )


def test_root_renders_html_template() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'href="/static/styles.css"' in response.text
    assert "A privacy preserving frontend for TikTok" in response.text
    assert 'name="url"' in response.text
    assert 'method="post"' in response.text
    assert "<script" not in response.text


def test_lifespan_creates_a_fresh_job_registry() -> None:
    with TestClient(app):
        first_jobs = app.state.media_jobs
    assert first_jobs._closed is True

    with TestClient(app):
        assert app.state.media_jobs is not first_jobs
        assert app.state.media_jobs._closed is False


def test_generated_same_origin_urls_preserve_root_path(monkeypatch) -> None:
    use_fake_jobs(monkeypatch)
    root_path_client = TestClient(app, root_path="/tokai")

    home = root_path_client.get("/")
    page = root_path_client.get("/ZMAVwmojg/")

    assert 'href="/tokai/static/styles.css"' in home.text
    assert '<source src="/tokai/media/media-job" type="video/mp4">' in page.text


def test_root_redirects_submitted_tiktok_video_url() -> None:
    response = client.post(
        "/",
        data={"url": "https://www.tiktok.com/@nerublanco/video/7542076400346451232?share_app_id=1233"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/@nerublanco/video/7542076400346451232"


@pytest.mark.parametrize("host", ["vm.tiktok.com", "vt.tiktok.com"])
def test_root_redirects_submitted_tiktok_short_link(host: str) -> None:
    response = client.post(
        "/",
        data={"url": f"https://{host}/ZMAVwmojg/"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ZMAVwmojg/"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video",
        "https://www.tiktok.com/explore",
        "https://[not-a-host",
    ],
)
def test_root_rejects_unsupported_tiktok_url(url: str) -> None:
    response = client.post("/", data={"url": url})

    assert response.status_code == 400
    assert "Enter a valid TikTok video URL." in response.text


def test_rejected_submission_logs_a_redacted_url(caplog: pytest.LogCaptureFixture) -> None:
    tokai_logger = logging.getLogger("tokai")
    tokai_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG, logger="tokai"):
            response = client.post("/", data={"url": "https://example.com/video?token=secret"})
    finally:
        tokai_logger.removeHandler(caplog.handler)

    assert response.status_code == 400
    assert "url=https://example.com/video" in caplog.text
    assert "token=secret" not in caplog.text


@pytest.mark.parametrize("handle", ["nerublanco", ""])
def test_tiktok_video_path_renders_metadata_and_uses_its_media_job(monkeypatch, handle: str) -> None:
    video_id = "7542076400346451232"
    media = b"\x00\x00\x00\x0cftypisomdata"
    jobs = use_fake_jobs(monkeypatch, media=media)
    monkeypatch.setenv("TOKAI_APP_URL", "https://tokai.example.com/tokai")
    page = client.get(
        f"/@{handle}/video/{video_id}?share_app_id=1233&share_item_id={video_id}"
    )

    assert page.status_code == 200
    assert '<source src="/media/media-job" type="video/mp4">' in page.text
    assert "Creator Name · @creator" in page.text
    assert "Published 14 Nov 2023" in page.text
    assert "<h1" not in page.text
    assert '<p class="video-caption">A public caption</p>' in page.text
    assert "Likes <strong>1.1M</strong>" in page.text
    assert "Views <strong>12.5M</strong>" in page.text
    assert "Shares <strong>114.6K</strong>" in page.text
    tiktok_path = f"@{handle}/video/{video_id}"
    assert f'href="https://tokai.example.com/tokai/{tiktok_path}">Permalink</a>' in page.text
    assert f'href="https://www.tiktok.com/{tiktok_path}">TikTok</a>' in page.text
    assert 'href="/download/media-job">Download</a>' in page.text
    assert page.text.index("Shares <strong>114.6K</strong>") < page.text.index('<p class="video-links">') < page.text.index('<p class="video-caption">')
    assert "<script" not in page.text
    assert jobs.prepared_identifiers == [video_id]

    media_response = client.get("/media/media-job")

    assert media_response.status_code == 200
    assert media_response.headers["content-type"].startswith("video/mp4")
    assert media_response.content == media
    assert media_response.headers["cache-control"] == "private, no-store"

    download_response = client.get("/download/media-job")

    assert download_response.status_code == 200
    assert download_response.content == media
    assert download_response.headers["cache-control"] == "private, no-store"
    assert download_response.headers["content-disposition"] == 'attachment; filename="1234567890.mp4"'
    assert jobs.media_ids == ["media-job", "media-job"]


def test_media_debug_logging_records_the_web_route(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    use_fake_jobs(monkeypatch)

    tokai_logger = logging.getLogger("tokai")
    tokai_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG, logger="tokai"):
            response = client.get("/media/media-job?share_app_id=1233")
    finally:
        tokai_logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    assert any(message.startswith("Fetching media job") for message in caplog.messages)
    assert any(message.startswith("Returning media job") for message in caplog.messages)
    assert "share_app_id=1233" not in caplog.text


def test_tiktok_short_code_renders_playable_scraped_mp4(monkeypatch) -> None:
    short_code = "ZMAVwmojg"
    media = b"\x00\x00\x0cftypisomdata"
    jobs = use_fake_jobs(monkeypatch, media=media)
    monkeypatch.setenv("TOKAI_APP_URL", "https://tokai.example.com")
    page = client.get(f"/{short_code}/?share_app_id=1233")

    assert page.status_code == 200
    assert '<source src="/media/media-job" type="video/mp4">' in page.text
    assert 'href="https://tokai.example.com/ZMAVwmojg">Permalink</a>' in page.text
    assert 'href="https://vm.tiktok.com/ZMAVwmojg/">TikTok</a>' in page.text

    media_response = client.get("/media/media-job")

    assert media_response.status_code == 200
    assert media_response.content == media
    assert jobs.prepared_identifiers == [short_code]
    assert jobs.media_ids == ["media-job"]


@pytest.mark.parametrize(
    "path",
    [
        "/x@nerublanco/video/7542076400346451232",
        "/@nerublanco/video/7542076400346451232/extra",
        "/@nerublanco/video/7542076400346451232%2Fextra",
    ],
)
def test_invalid_tiktok_video_paths_are_not_sent_to_scraper(monkeypatch, path: str) -> None:
    jobs = use_fake_jobs(monkeypatch)

    assert client.get(path).status_code == 404
    assert jobs.prepared_identifiers == []


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ContentUnavailableError("unavailable"), 404),
        (TransportError("unreachable"), 502),
        (JobCapacityError("full"), 503),
    ],
)
def test_media_route_reports_scraper_errors(monkeypatch, error: Exception, status_code: int) -> None:
    use_fake_jobs(monkeypatch, error=error)

    response = client.get("/media/media-job")

    assert response.status_code == status_code
    if status_code == 502:
        assert response.headers["content-type"].startswith("text/html")
        assert "Couldn’t retrieve video" in response.text
    if status_code == 503:
        assert response.headers["content-type"].startswith("text/html")
        assert "Video temporarily unavailable" in response.text


def test_download_route_renders_capacity_error_when_job_registry_is_full(monkeypatch) -> None:
    use_fake_jobs(monkeypatch, error=JobCapacityError("full"))

    response = client.get("/download/media-job")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert "Video temporarily unavailable" in response.text


def test_video_route_renders_retrieval_error_when_metadata_fetch_fails(monkeypatch) -> None:
    use_fake_jobs(monkeypatch, prepare_error=TransportError("unreachable"))

    response = client.get("/@creator/video/7542076400346451232")

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("text/html")
    assert "Couldn’t retrieve video" in response.text
    assert 'href="/">Go home</a>' in response.text


def test_video_route_renders_capacity_error_when_job_registry_is_full(monkeypatch) -> None:
    use_fake_jobs(monkeypatch, prepare_error=JobCapacityError("full"))

    response = client.get("/@creator/video/7542076400346451232")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert "Video temporarily unavailable" in response.text


def test_missing_page_renders_standard_404_template() -> None:
    response = client.get("/missing/page")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Page not found" in response.text
    assert 'href="/">Go home</a>' in response.text
    assert "<script" not in response.text


def test_static_css_is_served() -> None:
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/docs", "/docs/", "/redoc", "/redoc/", "/static", "/download"])
def test_reserved_paths_are_not_tiktok_short_codes(path: str) -> None:
    assert client.get(path).status_code == 404
