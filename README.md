# SplatTop Blog

Wagtail-powered blog for blog.splat.top.

## Quick Start (Local Development)

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup project (installs deps, creates .env, runs migrations)
make setup

# Create admin account
make superuser

# Run development server
make dev

# Visit the site
# macOS:
open http://localhost:8000
open http://localhost:8000/admin
# Linux:
xdg-open http://localhost:8000
xdg-open http://localhost:8000/admin
```

## Available Commands

```bash
make help          # Show all commands
make install       # Install dependencies
make dev           # Run dev server
make migrate       # Run migrations
make makemigrations # Create migrations
make lint          # Run linting (ruff)
make format        # Format code (ruff)
make shell         # Django shell
make superuser     # Create admin user
make static        # Collect static files
make clean         # Clean cache files
```

## Docker Development

If you prefer Docker (uses PostgreSQL):

```bash
make docker-up     # Start containers
make docker-logs   # View logs
make docker-down   # Stop containers
```

## Project Structure

```
SplatTopBlog/
├── src/                      # Application code
│   ├── blog/                 # Blog app (posts, index)
│   ├── home/                 # Home page app
│   ├── splattopblog/         # Django settings
│   ├── templates/            # Base templates
│   ├── static/               # Static assets
│   ├── media/                # User uploads
│   └── manage.py
├── docs/                     # Documentation
│   └── SplatTop_style_bible.md
├── .github/workflows/        # CI/CD
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── Makefile
```

## Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `true` |
| `DJANGO_SECRET_KEY` | Django secret key | (required in prod) |
| `ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | `http://localhost:8000` |
| `DATABASE_URL` | PostgreSQL connection string; supports `sslmode` and `sslrootcert` options | (empty = SQLite) |
| `USE_SPACES` | Use DO Spaces/S3 for media storage | `false` |
| `SITE_NAME` | Public site/feed name | `SplatTop Blog` |
| `SITE_DESCRIPTION` | Public metadata/feed description | `SplatTop blog posts and analysis.` |
| `SITE_AUTHOR` | Default public author name | `SplatTop` |
| `WAGTAILADMIN_BASE_URL` | Canonical admin URL | `http://localhost:8000` |
| `ALLOWED_EMBED_HOSTS` | Exact HTTPS hosts allowed in sandboxed imported iframes | `cesaregarza.github.io` |
| `CSP_ENFORCE` | Enforce CSP (otherwise report-only) | `false` |

**Note:** When `DATABASE_URL` is not set, the app uses SQLite, which is perfect for local development.

In non-debug mode, the app now defaults to stricter security behavior (SSL redirect, secure cookies, HSTS, etc.) and fails fast if a weak or missing `DJANGO_SECRET_KEY` is detected.

## Ghost import

The importer accepts only the purpose-built, pruned migration JSON and a
media-only tar archive containing regular image files under `content/images/`.
It never extracts the archive. Strict inline PNG fallbacks inside SVG
`<image>` nodes are decoded, canonically re-encoded, deduplicated, and stored
under opaque local media names; raw data URLs and SVG `foreignObject` HTML are
not published.

```bash
python src/manage.py import_ghost \
  /imports/cegarza-import.json \
  /imports/cegarza-import-media.tar.gz \
  --hostname preview.cegarza.com \
  --site-name "Bringing Down The Gauss" \
  --site-description "Thoughts, stories and ideas." \
  --site-author "Cesar Garza" \
  --dry-run

python src/manage.py import_ghost \
  /imports/cegarza-import.json \
  /imports/cegarza-import-media.tar.gz \
  --hostname preview.cegarza.com \
  --site-name "Bringing Down The Gauss" \
  --site-description "Thoughts, stories and ideas." \
  --site-author "Cesar Garza"
```

Run the dry run first. An identical repeated real run leaves the same Ghost
identities and revisions unchanged without creating duplicate pages, authors,
tags, or images. The identity flags shown above pin the existing Ghost
publication branding; when omitted, the importer derives the title and
description from the validated Ghost settings and the fallback author from the
sole imported author. Real imports serialize on the Wagtail tree-root database
row before media writes, and Spaces object overwrite is disabled, so concurrent
workers cannot overwrite or delete another import's media. If a storage or
database commit acknowledgement is lost, deterministic media is preserved; an
identical retry byte-verifies and reconciles either committed rows or a
mapping-less canonical object.

After preview acceptance, add the apex hostname as an explicit alias of the
existing preview site:

```bash
python src/manage.py activate_cegarza_hostname
```

The command requires exactly one `preview.cegarza.com:443` site rooted at a
blog index. It safely does nothing when the matching `cegarza.com:443` alias
already exists, copies the preview site's compatible permanent redirects,
rejects conflicting site or redirect records, and never changes the default
Wagtail site.

## Production Deployment

Push to `main` triggers the CI/CD pipeline:
1. Builds Docker image → DigitalOcean Container Registry
2. Creates PR to update Helm values in GarzAICluster
3. ArgoCD syncs deployment to Kubernetes
