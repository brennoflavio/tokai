# SPDX-License-Identifier: AGPL-3.0-or-later

from web import main
from web.app import app


def test_main_starts_uvicorn_with_the_configured_log_level(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_run(application, **kwargs) -> None:
        calls["application"] = application
        calls.update(kwargs)

    monkeypatch.setenv("TOKAI_HOST", "0.0.0.0")
    monkeypatch.setenv("TOKAI_PORT", "8001")
    monkeypatch.setenv("TOKAI_LOG_LEVEL", "debug")
    monkeypatch.setattr(main.uvicorn, "run", fake_run)

    main.main()

    assert calls == {
        "application": app,
        "host": "0.0.0.0",
        "port": 8001,
        "log_level": "debug",
        "access_log": False,
    }
