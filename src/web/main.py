# SPDX-License-Identifier: AGPL-3.0-or-later
"""Process entry point for the Tokai web server."""

import uvicorn

from utils.env import Environment, get_required_env
from utils.logging import configure_logging

from .app import app


def main() -> None:
    """Configure logging and start the Tokai web server."""
    log_level = get_required_env(Environment.TOKAI_LOG_LEVEL)
    get_required_env(Environment.TOKAI_APP_URL)
    configure_logging(log_level)
    uvicorn.run(
        app,
        host=get_required_env(Environment.TOKAI_HOST),
        port=int(get_required_env(Environment.TOKAI_PORT)),
        log_level=log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
