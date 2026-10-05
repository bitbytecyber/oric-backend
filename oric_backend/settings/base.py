"""
Base settings for the NED ORIC data portal.

Layout mirrors sis_backend: settings/{base,dev,prod}.py, ``__init__`` re-exports
base, env read through the small helpers below.
"""
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent  # oric_backend/
BASE_DIR = PROJECT_DIR.parent  # repo root (manage.py) — root modules importable


def _env(key: str, default: str = "") -> str:
    """Env var with surrounding whitespace / quotes stripped (Compose passes them verbatim)."""
    value = os.environ.get(key, default)
    if value is None:
        return default
    return value.strip().strip('"').strip("'")


def _env_flag(key: str, default: bool = False) -> bool:
    raw = _env(key, "1" if default else "0").lower()
    return raw in ("1", "true", "yes", "on")


def _env_pem(key: str) -> str:
    """PEM from env: Compose/.env can't hold real newlines, so accept literal backslash-n (as sis_backend)."""
    return _env(key).replace("\\n", "\n")


def _env_list(key: str, default: str = "") -> list[str]:
    return [item.strip() for item in _env(key, default).split(",") if item.strip()]


SECRET_KEY = _env("SECRET_KEY", "local-dev-insecure-key-change-me")
DEBUG = _env_flag("DEBUG", default=True)
TESTING = "test" in sys.argv
ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,backend")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LIBRARIES = [
    "rest_framework",
    "drf_spectacular",
    "django_filters",
    "django_extensions",
    "corsheaders",
    "auditlog",
    # Authentication = django-allauth, configured like sis_backend: headless only
    # (the SPA is the only UI), email login, login-by-code, TOTP MFA, user sessions.
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.apple",
    "allauth.headless",
    "allauth.usersessions",
    "allauth.mfa",
]

APP_MODULES = [
    # First: its middleware mints the request id that auditlog rows and
    # ActivityEvent rows are correlated by.
    "audit.apps.AuditConfig",
    # Users + session login/logout/me. AUTH_USER_MODEL lives here.
    "people.apps.PeopleConfig",
    # Departments, reporting cycles (fiscal years), ORIC team, contact inbox.
    "org.apps.OrgConfig",
    # Capability catalog, roles, department-scoped role assignments, /me/abilities.
    "rbac.apps.RbacConfig",
    # The three pillar returns (legacy RicForm1/2/3), their entries + evidence,
    # review workflow. Form definitions: submissions/registry.py.
    "submissions.apps.SubmissionsConfig",
    # Year-wise dashboards and CSV/XLSX exports (legacy /reports, /report_ric_3).
    "reports.apps.ReportsConfig",
    # In-app notifications (+ email) for workflow events.
    "notifications.apps.NotificationsConfig",
]

INSTALLED_APPS = DJANGO_APPS + LIBRARIES + APP_MODULES

MIDDLEWARE = [
    "audit.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    # CsrfViewMiddleware deliberately absent (same as sis_backend): API auth is a
    # SameSite=Lax session cookie and DRF's session class is CSRF-exempt; the
    # admin site keeps its own csrf_protect decorators.
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "allauth.usersessions.middleware.UserSessionsMiddleware",
]

ROOT_URLCONF = "oric_backend.urls"
WSGI_APPLICATION = "oric_backend.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

if _env("DATABASE_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": _env("DATABASE_HOST"),
            "PORT": _env("DATABASE_PORT", "5432"),
            "NAME": _env("DATABASE_NAME", "oric-local"),
            "USER": _env("DATABASE_USER", "oric"),
            "PASSWORD": _env("DATABASE_PASSWORD", ""),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    # Lets `manage.py test` / makemigrations run outside Docker.
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "people.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessions ---------------------------------------------------------------
# Web auth = session cookie (legacy portal kept a JWT in localStorage: XSS-readable,
# 1h hard expiry that logged people out mid-form). Sliding idle expiry, renewed at
# most once per SESSION_TOUCH_INTERVAL (see people/authentications.py).
SESSION_COOKIE_AGE = int(_env("SESSION_COOKIE_AGE", str(14 * 24 * 3600)))
SESSION_TOUCH_INTERVAL = int(_env("SESSION_TOUCH_INTERVAL", str(12 * 3600)))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"  # compensating control for CSRF-exempt session auth
SESSION_COOKIE_NAME = "oric_sessionid"

# --- DRF ----------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("people.authentications.CsrfExemptSessionAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "oric_backend.pagination.OricLimitOffsetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "oric_backend.envelope.EnvelopeJSONRenderer",
        *(["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    ],
    "EXCEPTION_HANDLER": "oric_backend.envelope.envelope_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "contact": _env("THROTTLE_CONTACT", "5/hour"),
    },
}
SERVE_API_DOCS = _env_flag("SERVE_API_DOCS")
SPECTACULAR_SETTINGS = {
    "TITLE": "NED ORIC Data Portal API",
    "DESCRIPTION": "Research, innovation & commercialization returns (HEC ORIC scorecard).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Authentication (django-allauth, same shape as sis_backend) -------------------
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
ACCOUNT_ADAPTER = "people.adapters.ORICAccountAdapter"
HEADLESS_ADAPTER = "people.adapters.ORICHeadlessAdapter"
MFA_ADAPTER = "people.adapters.ORICMFAAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
# Accounts are provisioned by ORIC with a verified address (people/services/profile.py),
# so mandatory verification never blocks a real user; it is required for login-by-code.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED = False
ACCOUNT_PASSWORD_RESET_BY_CODE_ENABLED = False
# Forgot-password must not reveal whether an address has an account.
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[ORIC Data Portal] "
ACCOUNT_LOGIN_ON_PASSWORD_RESET = False
ACCOUNT_RATE_LIMITS = {"login_failed": "10/m/ip,5/5m/key"}
HEADLESS_ONLY = True
HEADLESS_SERVE_SPECIFICATION = True
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_TOTP_ISSUER = "NED ORIC"
USERSESSIONS_TRACK_ACTIVITY = True
ALLAUTH_TRUSTED_PROXY_COUNT = int(_env("ALLAUTH_TRUSTED_PROXY_COUNT", "0"))

# --- Social login: Google (same settings-based setup as sis_backend) ---------------
# Credentials come from env per environment, NOT a DB SocialApp row, so dev/prod
# never share or clobber each other's app config. Unset = Google sign-in hidden.
GOOGLE_OAUTH_CLIENT_ID = _env("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = _env("GOOGLE_OAUTH_CLIENT_SECRET")
# Optional: only accept Google accounts on these domains (comma-separated), e.g.
# "neduet.edu.pk,cloud.neduet.edu.pk". Empty = any verified Google address that
# matches an existing ORIC account.
GOOGLE_ALLOWED_DOMAINS = [d.lower() for d in _env_list("GOOGLE_ALLOWED_DOMAINS")]
# --- Social login: Apple (same settings-based setup as sis_backend) ----------------
# Server-side redirect flow (POST /_allauth/browser/v1/auth/provider/redirect).
# Register "{origin}/accounts/apple/login/callback/" as the Return URL on the Services ID;
# Apple requires a live HTTPS domain, so this can't run on plain localhost.
APPLE_OAUTH_CLIENT_ID = _env("APPLE_OAUTH_CLIENT_ID")  # Services ID (comma-separated for several)
APPLE_TEAM_ID = _env("APPLE_TEAM_ID")
APPLE_KEY_ID = _env("APPLE_KEY_ID")
APPLE_PRIVATE_KEY = _env_pem("APPLE_PRIVATE_KEY")  # full .p8 PEM, headers included
SOCIALACCOUNT_ADAPTER = "people.adapters.ORICSocialAccountAdapter"
# We trust Google's `email_verified` claim (checked explicitly in the adapter).
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
# Linking to an existing account happens explicitly in the adapter so our rules
# apply (verified email, no reactivation of disabled accounts, no escalation).
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APPS": [{"client_id": GOOGLE_OAUTH_CLIENT_ID, "secret": GOOGLE_OAUTH_CLIENT_SECRET, "key": ""}]
        if GOOGLE_OAUTH_CLIENT_ID else [],
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        # Do not blindly trust the provider; the adapter checks email_verified.
        "VERIFIED_EMAIL": False,
    },
    "apple": {
        # One APPS entry per client_id (web Services ID first); later ones are "hidden" so
        # get_app() still resolves to the web entry by default — exactly as sis_backend.
        "APPS": [
            {
                "client_id": client_id,
                "secret": APPLE_KEY_ID,
                "key": APPLE_TEAM_ID,
                "settings": {"certificate_key": APPLE_PRIVATE_KEY, **({"hidden": True} if index > 0 else {})},
            }
            for index, client_id in enumerate(
                cid.strip() for cid in APPLE_OAUTH_CLIENT_ID.split(",") if cid.strip()
            )
        ],
        "VERIFIED_EMAIL": False,
    },
}

# --- CORS ---------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = _env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:3000")
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["X-Request-Id", "Content-Disposition"]
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (*default_headers, "x-request-id")

# Public URL of the web app (links in emails, allauth redirects). Same name as sis_backend.
FRONTEND_URL = FRONTEND_ORIGIN = _env("FRONTEND_ORIGIN", _env("FRONTEND_URL", "http://localhost:3000"))
LOGIN_URL = f"{FRONTEND_URL}/sign-in"
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": f"{FRONTEND_URL}/verify-email/{{key}}",
    "account_reset_password": f"{FRONTEND_URL}/sign-in?mode=forgot",
    "account_reset_password_from_key": f"{FRONTEND_URL}/reset-password/{{key}}",
    "account_signup": f"{FRONTEND_URL}/sign-in",
    "socialaccount_login_error": f"{FRONTEND_URL}/sign-in?error=social",
}

# --- Email ----------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = _env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(_env("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = _env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = _env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = _env_flag("EMAIL_USE_TLS")
DEFAULT_FROM_EMAIL = _env("DEFAULT_FROM_EMAIL", "ORIC NED <oric@neduet.edu.pk>")
ORIC_INBOX_EMAIL = _env("ORIC_INBOX_EMAIL", "oric@neduet.edu.pk")

# --- Audit (django-auditlog) ------------------------------------------------------
AUDITLOG_INCLUDE_ALL_MODELS = True
AUDITLOG_EXCLUDE_TRACKING_MODELS = (
    "sessions",
    "contenttypes",
    "admin.logentry",
    "auditlog.logentry",
    "audit.activityevent",
    "rbac.authzdeniallog",
    "usersessions.usersession",
    "account.emailconfirmation",
    "notifications.notification",
)
AUDITLOG_EXCLUDE_TRACKING_FIELDS = ("last_login", "updated_at")
AUDITLOG_MASK_TRACKING_FIELDS = ("password",)
AUDITLOG_CID_GETTER = "audit.cid.get_request_cid"

# --- Cache (RBAC abilities payload) ------------------------------------------------
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "oric"}}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "authentication.security": {"handlers": ["console"], "level": "INFO"},
        "oric": {"handlers": ["console"], "level": "INFO"},
    },
}
