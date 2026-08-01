"""Django settings for the cegarza.com site."""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def get_env(primary_key: str, *fallback_keys: str, default: str | None = None) -> str | None:
    for key in (primary_key, *fallback_keys):
        value = os.environ.get(key)
        if value:
            return value
    return default


def get_env_bool(key: str, default: bool = False) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_list(key: str, default: str = "") -> list[str]:
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# SECURITY
DEBUG = get_env_bool("DEBUG", default=False)
SERVE_MEDIA = get_env_bool("SERVE_MEDIA", default=False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "local-dev-secret-key-not-for-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG=false.")

if not DEBUG:
    weak_keys = {
        "change-me-in-production",
        "dev-secret-key-change-in-production",
        "local-dev-secret-key-not-for-production",
    }
    if SECRET_KEY in weak_keys:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is using a known insecure development key while DEBUG=false."
        )

ALLOWED_HOSTS = get_env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = get_env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:8000")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = get_env_bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = get_env_bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = get_env_bool("CSRF_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_HTTPONLY = get_env_bool("CSRF_COOKIE_HTTPONLY", default=True)
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.environ.get("SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")
X_FRAME_OPTIONS = os.environ.get("X_FRAME_OPTIONS", "SAMEORIGIN")
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = get_env_bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=not DEBUG,
)
SECURE_HSTS_PRELOAD = get_env_bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CROSS_ORIGIN_OPENER_POLICY = os.environ.get(
    "SECURE_CROSS_ORIGIN_OPENER_POLICY", "same-origin"
)
SECURE_CROSS_ORIGIN_RESOURCE_POLICY = os.environ.get(
    "SECURE_CROSS_ORIGIN_RESOURCE_POLICY",
    "same-origin",
)

# Application definition
INSTALLED_APPS = [
    # Django apps (must come before Wagtail)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sitemaps",
    "django.contrib.staticfiles",
    # Wagtail apps
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.routable_page",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.contrib.sitemaps",
    "wagtail.admin",
    "wagtail",
    "wagtailmarkdown",
    # Wagtail dependencies
    "modelcluster",
    "taggit",
    # Health checks
    "health_check",
    "health_check.db",
    # Object storage
    "storages",
    # Project apps
    "home",
    "blog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "blog.middleware.FrontendSecurityHeadersMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "blog.middleware.SiteAwareRedirectMiddleware",
]

ROOT_URLCONF = "cegarza_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "blog.context_processors.site_identity",
            ],
        },
    },
]

WSGI_APPLICATION = "cegarza_site.wsgi.application"


# Database
# Use PostgreSQL in production, SQLite for local development
def parse_database_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    scheme = parsed.scheme.split("+", 1)[0]
    if scheme not in {"postgres", "postgresql"}:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")

    config: dict[str, object] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": (parsed.path or "").lstrip("/") or "cegarzablog",
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
    }
    if parsed.port:
        config["PORT"] = str(parsed.port)

    query = parse_qs(parsed.query)
    options: dict[str, str] = {}
    if "sslmode" in query:
        options["sslmode"] = query["sslmode"][0]
    if "sslrootcert" in query:
        options["sslrootcert"] = query["sslrootcert"][0]
    if "options" in query:
        options["options"] = query["options"][0]
    if options:
        config["OPTIONS"] = options
    return config


database_url = os.environ.get("DATABASE_URL")
sql_host = get_env("SQL_HOST", "DB_HOST")
if database_url:
    DATABASES = {
        "default": parse_database_url(database_url),
    }
elif sql_host:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": get_env("SQL_DATABASE", "DB_NAME", default="cegarzablog"),
            "USER": get_env("SQL_USER", "DB_USER", default="postgres"),
            "PASSWORD": get_env("SQL_PASSWORD", "DB_PASSWORD", default=""),
            "HOST": sql_host or "localhost",
            "PORT": get_env("SQL_PORT", "DB_PORT", default="5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# DigitalOcean Spaces configuration (S3-compatible object storage)
USE_SPACES = os.environ.get("USE_SPACES", "false").lower() == "true"
AWS_S3_FILE_OVERWRITE = False

if USE_SPACES:
    # DO Spaces credentials
    AWS_ACCESS_KEY_ID = os.environ.get("SPACES_ACCESS_KEY")
    AWS_SECRET_ACCESS_KEY = os.environ.get("SPACES_SECRET_KEY")
    AWS_STORAGE_BUCKET_NAME = os.environ.get("SPACES_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.environ.get("SPACES_REGION", "nyc3")
    AWS_S3_ENDPOINT_URL = os.environ.get(
        "SPACES_ENDPOINT_URL", f"https://{AWS_S3_REGION_NAME}.digitaloceanspaces.com"
    )

    # Optional CDN endpoint (e.g., bucket-name.nyc3.cdn.digitaloceanspaces.com)
    AWS_S3_CUSTOM_DOMAIN = os.environ.get("SPACES_CDN_DOMAIN")

    # Storage settings
    AWS_DEFAULT_ACL = "public-read"
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

    # Use Spaces for media, WhiteNoise for static
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "file_overwrite": False,
                "location": "media",
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

    # Update media URL to use Spaces
    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
    else:
        MEDIA_URL = f"{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/media/"
else:
    # Local development: use filesystem storage
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Wagtail settings
SITE_NAME = get_env("SITE_NAME", "WAGTAIL_SITE_NAME", default="cegarza.com")
SITE_DESCRIPTION = get_env(
    "SITE_DESCRIPTION",
    default="Thoughts, stories and ideas.",
)
SITE_AUTHOR = get_env("SITE_AUTHOR", "SITE_AUTHOR_NAME", default="Cesar Garza")
BLOG_TAGS_ENABLED = get_env_bool("BLOG_TAGS_ENABLED", default=False)
WAGTAIL_SITE_NAME = SITE_NAME
WAGTAILADMIN_BASE_URL = get_env(
    "WAGTAILADMIN_BASE_URL",
    default="http://localhost:8000",
)
ALLOWED_EMBED_HOSTS = get_env_list(
    "ALLOWED_EMBED_HOSTS",
    "cesaregarza.github.io",
)

# Search backend
WAGTAILSEARCH_BACKENDS = {
    "default": {
        "BACKEND": "wagtail.search.backends.database",
    }
}

# Wagtail Markdown settings
WAGTAILMARKDOWN = {
    "autodownload_fontawesome": False,
    # In wagtail-markdown, empty lists/dicts under default "extend" mode do not mean "allow all".
    "allowed_tags": [],
    "allowed_attributes": {},
    "allowed_styles": [],
    "extensions": [
        "extra",
        "blog.markdown_extensions.latex",
        "blog.markdown_extensions.random_choice",
        "codehilite",
        "tables",
        "toc",
        "nl2br",
        "smarty",
    ],
    "extension_configs": {
        "codehilite": {
            "linenums": True,
        }
    },
}
