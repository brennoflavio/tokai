# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from scraper import ContentUnavailableError, TransportError

from web.app import app

client = TestClient(app)


def test_root_renders_html_template() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/static/styles.css" in response.text
    assert "<script" not in response.text


@pytest.mark.parametrize("handle", ["nerublanco", ""])
def test_tiktok_video_path_renders_playable_scraped_mp4(monkeypatch, handle: str) -> None:
    video_id = "7542076400346451232"
    media = b"\x00\x00\x00\x0cftypisomdata"
    calls: list[str] = []

    async def fake_fetch_video(identifier: str) -> SimpleNamespace:
        calls.append(identifier)
        return SimpleNamespace(media=media)

    monkeypatch.setattr("web.app.fetch_video", fake_fetch_video)
    page = client.get(
        f"/@{handle}/video/{video_id}?share_app_id=1233&share_item_id={video_id}"
    )

    assert page.status_code == 200
    assert f'<video controls>\n        <source src="http://testserver/media/{video_id}" type="video/mp4">' in page.text
    assert "<script" not in page.text
    assert calls == []

    media_response = client.get(f"/media/{video_id}")

    assert media_response.status_code == 200
    assert media_response.headers["content-type"].startswith("video/mp4")
    assert media_response.content == media
    assert calls == [video_id]


def test_tiktok_short_code_renders_playable_scraped_mp4(monkeypatch) -> None:
    short_code = "ZMAVwmojg"
    media = b"\x00\x00\x0cftypisomdata"
    calls: list[str] = []

    async def fake_fetch_video(identifier: str) -> SimpleNamespace:
        calls.append(identifier)
        return SimpleNamespace(media=media)

    monkeypatch.setattr("web.app.fetch_video", fake_fetch_video)
    page = client.get(f"/{short_code}/?share_app_id=1233")

    assert page.status_code == 200
    assert f'<source src="http://testserver/media/{short_code}" type="video/mp4">' in page.text

    media_response = client.get(f"/media/{short_code}")

    assert media_response.status_code == 200
    assert media_response.content == media
    assert calls == [short_code]


@pytest.mark.parametrize(
    "path",
    [
        "/x@nerublanco/video/7542076400346451232",
        "/@nerublanco/video/7542076400346451232/extra",
        "/@nerublanco/video/7542076400346451232%2Fextra",
    ],
)
def test_invalid_tiktok_video_paths_are_not_sent_to_scraper(monkeypatch, path: str) -> None:
    async def fake_fetch_video(identifier: str) -> None:
        raise AssertionError(f"unexpected scraper call: {identifier}")

    monkeypatch.setattr("web.app.fetch_video", fake_fetch_video)

    assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    ("error", "status_code"),
    [(ContentUnavailableError("unavailable"), 404), (TransportError("unreachable"), 502)],
)
def test_media_route_reports_scraper_errors(monkeypatch, error: Exception, status_code: int) -> None:
    async def fake_fetch_video(identifier: str) -> None:
        raise error

    monkeypatch.setattr("web.app.fetch_video", fake_fetch_video)

    assert client.get("/media/7542076400346451232").status_code == status_code


def test_static_css_is_served() -> None:
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/docs", "/docs/", "/redoc", "/redoc/", "/static"])
def test_reserved_paths_are_not_tiktok_short_codes(path: str) -> None:
    assert client.get(path).status_code == 404
