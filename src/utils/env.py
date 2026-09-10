# SPDX-License-Identifier: AGPL-3.0-or-later
"""Environment-variable resolution helpers."""

import os
from enum import StrEnum


class Environment(StrEnum):
    """Supported Tokai environment variables."""

    TOKAI_HOST = "TOKAI_HOST"
    TOKAI_PORT = "TOKAI_PORT"
    TOKAI_LOG_LEVEL = "TOKAI_LOG_LEVEL"


DEFAULT_VALUES: dict[Environment, str] = {
    Environment.TOKAI_HOST: "127.0.0.1",
    Environment.TOKAI_PORT: "8000",
    Environment.TOKAI_LOG_LEVEL: "info",
}
VALID_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})


def get_required_env(environment: Environment) -> str:
    """Return a validated environment value, using its application default when unset."""
    value = os.getenv(environment, DEFAULT_VALUES[environment])
    if environment is Environment.TOKAI_PORT:
        _validate_port(value)
    if environment is Environment.TOKAI_LOG_LEVEL:
        value = _normalize_log_level(value)
    return value


def _validate_port(value: str) -> None:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"{Environment.TOKAI_PORT} must be a number") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{Environment.TOKAI_PORT} must be between 1 and 65535")


def _normalize_log_level(value: str) -> str:
    level = value.lower()
    if level not in VALID_LOG_LEVELS:
        valid_levels = ", ".join(sorted(VALID_LOG_LEVELS))
        raise ValueError(f"{Environment.TOKAI_LOG_LEVEL} must be one of: {valid_levels}")
    return level
