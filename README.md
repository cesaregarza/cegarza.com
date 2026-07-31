# cegarza.com

The Wagtail-powered personal site for [cegarza.com](https://cegarza.com).

## Local development

Install dependencies, configure a local environment, migrate, and start the
development server:

```bash
make setup
make superuser
make dev
```

The public site is available at `http://localhost:8000`; Wagtail admin is at
`http://localhost:8000/admin/`.

Useful commands:

```bash
make help
make lint
make format
make migrate
make makemigrations
make shell
make static
```

Docker-based development uses PostgreSQL:

```bash
make docker-up
make docker-logs
make docker-down
```

## Project layout

```text
src/
├── blog/          # Wagtail pages, imports, feeds, and tests
├── cegarza_site/  # Django settings, URLs, and WSGI
├── home/          # Directory page
├── static/        # Versioned site assets and applets
└── templates/     # Shared public templates
ops/               # Explicit operator-run migration tools
docs/              # Design and operational documentation
```

## Configuration

Copy `.env.example` to `.env`. Production requires a strong
`DJANGO_SECRET_KEY`. `DATABASE_URL` supports PostgreSQL SSL parameters;
without it, local development uses SQLite.

The public defaults are:

| Variable | Default |
| --- | --- |
| `SITE_NAME` | `cegarza.com` |
| `SITE_DESCRIPTION` | `Thoughts, stories and ideas.` |
| `SITE_AUTHOR` | `Cesar Garza` |
| `WAGTAILADMIN_BASE_URL` | `http://localhost:8000` |

## Ghost import

The existing `import_ghost` command accepts a purpose-built JSON export and a
bounded media archive. Always validate first:

```bash
python src/manage.py import_ghost \
  /imports/export.json \
  /imports/media.tar.gz \
  --hostname preview.cegarza.com \
  --dry-run
```

An identical real import is idempotent. Imported media uses deterministic
names and is byte-verified before reuse.

## Wagtail-to-Wagtail port

`ops/export_wagtail_bundle.py` is a read-only, version-compatible exporter for
small PostgreSQL-backed Wagtail sites. It reads through a repeatable-read,
read-only transaction and emits a credential-free, mode-0600 archive
containing published page snapshots, the latest distinct draft, restriction
type, and checksummed original images. It deliberately excludes restriction
passwords.

Record the compressed archive SHA-256 outside the repository. On the
destination, validate and then import the exact same pinned archive:

```bash
python src/manage.py import_wagtail_bundle /imports/site.tar.gz \
  --hostname dev.cegarza.com \
  --source-namespace source-primary \
  --bundle-sha256 "$BUNDLE_SHA256" \
  --dry-run

python src/manage.py import_wagtail_bundle /imports/site.tar.gz \
  --hostname dev.cegarza.com \
  --source-namespace source-primary \
  --bundle-sha256 "$BUNDLE_SHA256"
```

The importer uses namespaced page/image mappings, fails on unrelated slug
collisions, deterministic media collisions, publication-timestamp drift, or
destination editorial drift. Dry-run validates rewritten Wagtail revisions
without writing destination rows or media. The real import preserves live
versus draft state, keeps restricted pages fail-closed, and removes newly
written media if the database transaction rolls back. A repeated identical
import must report all pages and images unchanged.

Restriction passwords may be transferred only through the dedicated
non-interactive stdin command. Never put them in an archive, file, log, shell
argument, or commit.

## Release

A merge to `main` builds and publishes
`registry.digitalocean.com/sendouq/cegarza-blog`, creates a GitHub release, and
opens a narrowly scoped GitOps activation PR for
`helm/cegarza-blog/values-cegarza.yaml`. Argo CD deployment remains an explicit
reviewed GitOps action.
