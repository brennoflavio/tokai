# SPDX-License-Identifier: AGPL-3.0-or-later
"""Development entry point for the Tokai web server."""

import uvicorn

from web.app import app


if __name__ == "__main__":
    uvicorn.run(app)
