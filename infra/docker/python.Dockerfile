# One image recipe for every Python service. PACKAGE picks which workspace member to install:
#   firstweek-core (migrations), firstweek-api, firstweek-worker
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
ARG PACKAGE

# 1. Third-party dependencies only, cached unless a pyproject or the lockfile changes.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
COPY services/worker/pyproject.toml services/worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package "${PACKAGE}"

# 2. Our own code.
COPY packages packages
COPY apps/api apps/api
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package "${PACKAGE}"
