###############################
#         Base Image          #
###############################
FROM python:3.12-slim AS base

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (pinned instead of :latest for reproducible builds)
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

###############################
#    Install Dependencies     #
###############################
FROM base AS dependencies

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (frozen from lockfile)
RUN uv sync --frozen --no-dev --no-install-project

###############################
#        Build Image          #
###############################
FROM dependencies AS build

# Build arguments for versioning
ARG BUILD_VERSION=dev
ARG GIT_SHA=unknown

# Set version info as environment variables
ENV APP_VERSION=${BUILD_VERSION} \
    GIT_SHA=${GIT_SHA}

# Copy project files
COPY src/ ./src/

WORKDIR /app/src

# Collect static files
RUN DJANGO_SECRET_KEY="build-time-only-secret-not-used-at-runtime" \
    /app/.venv/bin/python manage.py collectstatic --noinput --clear

# Create non-root user
RUN useradd -m -u 1000 wagtail && chown -R wagtail:wagtail /app
USER wagtail

EXPOSE 8000

# Run with gunicorn
CMD ["/app/.venv/bin/gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "cegarza_site.wsgi:application"]
