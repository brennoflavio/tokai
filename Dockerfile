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

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
