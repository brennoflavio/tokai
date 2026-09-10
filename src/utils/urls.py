# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL helpers for privacy-safe logging."""

from urllib.parse import urlsplit, urlunsplit


def redact_url(value: str) -> str:
    """Remove query, fragment, and credentials before logging a URL."""
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "<invalid-url>"
    if hostname is None:
        return parsed.path or "<invalid-url>"
    host = f"[{hostname}]" if ":" in hostname else hostname
    authority = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
