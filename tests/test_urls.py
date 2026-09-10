# SPDX-License-Identifier: AGPL-3.0-or-later

from utils.urls import redact_url


def test_redact_url_removes_query_fragment_and_credentials() -> None:
    assert redact_url("https://user:password@cdn.tiktok.com:443/video.mp4?token=one#fragment") == (
        "https://cdn.tiktok.com:443/video.mp4"
    )
