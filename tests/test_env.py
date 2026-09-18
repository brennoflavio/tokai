# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

import pytest

from utils.env import DEFAULT_VALUES, Environment, VALID_LOG_LEVELS, get_required_env
from utils.logging import LOGGER_NAME, configure_logging, get_logger


def test_get_required_env_uses_defaults_only_when_unset(monkeypatch) -> None:
    monkeypatch.delenv(Environment.TOKAI_HOST, raising=False)
    assert get_required_env(Environment.TOKAI_HOST) == DEFAULT_VALUES[Environment.TOKAI_HOST]

    monkeypatch.setenv(Environment.TOKAI_HOST, "")
    assert get_required_env(Environment.TOKAI_HOST) == ""


def test_get_required_env_validates_port(monkeypatch) -> None:
    monkeypatch.delenv(Environment.TOKAI_PORT, raising=False)
    assert get_required_env(Environment.TOKAI_PORT) == DEFAULT_VALUES[Environment.TOKAI_PORT]

    monkeypatch.setenv(Environment.TOKAI_PORT, "8001")
    assert get_required_env(Environment.TOKAI_PORT) == "8001"

    monkeypatch.setenv(Environment.TOKAI_PORT, "invalid")
    with pytest.raises(ValueError, match="TOKAI_PORT must be a number"):
        get_required_env(Environment.TOKAI_PORT)

    monkeypatch.setenv(Environment.TOKAI_PORT, "65536")
    with pytest.raises(ValueError, match="TOKAI_PORT must be between"):
        get_required_env(Environment.TOKAI_PORT)


def test_configure_logging_uses_the_configured_log_level(monkeypatch) -> None:
    monkeypatch.setenv(Environment.TOKAI_LOG_LEVEL, "debug")
    try:
        assert configure_logging().level == logging.DEBUG
    finally:
        configure_logging("info")


def test_get_logger_uses_the_tokai_namespace() -> None:
    assert get_logger("scraper").name == "tokai.scraper"
    assert get_logger("web").parent.name == LOGGER_NAME


def test_get_required_env_normalizes_app_url(monkeypatch) -> None:
    monkeypatch.delenv(Environment.TOKAI_APP_URL, raising=False)
    assert get_required_env(Environment.TOKAI_APP_URL) == "http://127.0.0.1:8000"

    monkeypatch.setenv(Environment.TOKAI_APP_URL, "https://tokai.example.com/tokai/")
    assert get_required_env(Environment.TOKAI_APP_URL) == "https://tokai.example.com/tokai"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "tokai.example.com",
        "ftp://tokai.example.com",
        "https://tokai.example.com/?x=1",
        "https://tokai.example.com/?",
        "https://tokai.example.com/#",
    ],
)
def test_get_required_env_rejects_invalid_app_url(monkeypatch, value: str) -> None:
    monkeypatch.setenv(Environment.TOKAI_APP_URL, value)

    with pytest.raises(ValueError, match="TOKAI_APP_URL must be an absolute HTTP\\(S\\) URL"):
        get_required_env(Environment.TOKAI_APP_URL)


def test_get_required_env_normalizes_log_level(monkeypatch) -> None:
    monkeypatch.delenv(Environment.TOKAI_LOG_LEVEL, raising=False)
    assert get_required_env(Environment.TOKAI_LOG_LEVEL) == DEFAULT_VALUES[Environment.TOKAI_LOG_LEVEL]

    monkeypatch.setenv(Environment.TOKAI_LOG_LEVEL, "DEBUG")
    assert get_required_env(Environment.TOKAI_LOG_LEVEL) == "debug"


def test_get_required_env_rejects_unsafe_log_levels(monkeypatch) -> None:
    monkeypatch.setenv(Environment.TOKAI_LOG_LEVEL, "trace")

    with pytest.raises(ValueError, match="TOKAI_LOG_LEVEL must be one of"):
        get_required_env(Environment.TOKAI_LOG_LEVEL)

    assert "trace" not in VALID_LOG_LEVELS
