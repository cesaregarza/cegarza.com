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

Copy `.env.local` to `.env`:

```bash
cp .env.local .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `true` |
| `DJANGO_SECRET_KEY` | Django secret key | (required in prod) |
| `ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | `http://localhost:8000` |
| `DATABASE_URL` | PostgreSQL connection string | (empty = SQLite) |
| `USE_SPACES` | Use DO Spaces/S3 for media storage | `false` |
| `WAGTAILADMIN_BASE_URL` | Canonical admin URL | `http://localhost:8000` |
| `CSP_ENFORCE` | Enforce CSP (otherwise report-only) | `false` |

**Note:** When `DATABASE_URL` is not set, the app uses SQLite, which is perfect for local development.

In non-debug mode, the app now defaults to stricter security behavior (SSL redirect, secure cookies, HSTS, etc.) and fails fast if a weak or missing `DJANGO_SECRET_KEY` is detected.

## Production Deployment

Push to `main` triggers the CI/CD pipeline:
1. Builds Docker image → DigitalOcean Container Registry
2. Creates PR to update Helm values in GarzAICluster
3. ArgoCD syncs deployment to Kubernetes
