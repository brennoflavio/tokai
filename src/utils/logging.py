# SPDX-License-Identifier: AGPL-3.0-or-later
"""Centralized logging configuration for Tokai application code."""

from __future__ import annotations

import logging
import sys

from .env import Environment, get_required_env

LOGGER_NAME = "tokai"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(log_level: str | int | None = None) -> logging.Logger:
    """Configure and return the root logger for Tokai application events."""
    logger = logging.getLogger(LOGGER_NAME)
    level = get_required_env(Environment.TOKAI_LOG_LEVEL) if log_level is None else log_level
    logger.setLevel(level.upper() if isinstance(level, str) else level)
    logger.propagate = False
    if not any(getattr(handler, "_tokai_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler._tokai_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


def get_logger(component: str) -> logging.Logger:
    """Return a logger for a Tokai application component."""
    return logging.getLogger(f"{LOGGER_NAME}.{component}")
