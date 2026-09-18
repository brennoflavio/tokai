# syntax=docker/dockerfile:1
# SPDX-License-Identifier: AGPL-3.0-or-later
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV UV_CACHE_DIR=/tmp/uv-cache
ENV TOKAI_HOST=0.0.0.0
ENV TOKAI_PORT=8000
ENV TOKAI_LOG_LEVEL=info
ENV TOKAI_APP_URL=http://127.0.0.1:8000
RUN useradd --uid 10001 --create-home --user-group tokai
USER tokai

EXPOSE 8000

CMD exec uv run --no-sync python -m web.main 2>&1
