"""
Base settings for irri_ai project.
Environment-specific overrides live in dev.py / prod.py.
"""
from pathlib import Path
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-insecure-secret-key-change-me")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

# --- Applications ----------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "widget_tweaks",
]

LOCAL_APPS = [
    "core",
    "accounts",
    "documents",
    "keywords",
    "catalogues",
    "hooks",
    "queries",
    "dashboard",
    "image_bank",
    "api_endpoints",
]

# --- Image bank (CLIP visual knowledge) -----------------------------------
IMAGE_BANK_DISTANCE_MAX = 0.35  # cosine distance; lower is better. Above this -> "low confidence"
IMAGE_BANK_TOP_K = 5

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "irri_ai.urls"

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
                "core.context_processors.nav",
            ],
        },
    },
]

WSGI_APPLICATION = "irri_ai.wsgi.application"
ASGI_APPLICATION = "irri_ai.asgi.application"

# --- Database (MySQL via XAMPP) --------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": config("DB_NAME", default="irri_ai"),
        "USER": config("DB_USER", default="root"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="127.0.0.1"),
        "PORT": config("DB_PORT", default="3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth ------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n ------------------------------------------------------------------

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
# Set False because XAMPP MySQL ships without the timezone tables, so
# TruncMonth + CONVERT_TZ fails. Storing naive local timestamps is fine for a single-region app.
USE_TZ = False

# --- Static / media --------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 5000

# --- Chroma / embeddings / LLM --------------------------------------------

CHROMA_PERSIST_DIR = str(BASE_DIR / "chroma_db")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

OPENAI_API_KEY = config("OPENAI_API_KEY", default="")
OPENAI_EMBED_MODEL = config("OPENAI_EMBED_MODEL", default="text-embedding-3-small")
OPENAI_CHAT_MODEL = config("OPENAI_CHAT_MODEL", default="gpt-4o-mini")
OPENAI_STT_MODEL = config("OPENAI_STT_MODEL", default="whisper-1")
OPENAI_TTS_MODEL = config("OPENAI_TTS_MODEL", default="tts-1")
OPENAI_TTS_VOICE = config("OPENAI_TTS_VOICE", default="alloy")

USE_LOCAL_EMBEDDINGS = config("USE_LOCAL_EMBEDDINGS", default=False, cast=bool)

# --- Local AI4Bharat IndicConformer for Odia STT --------------------------
# No env vars needed — the model weights are downloaded from HuggingFace on
# first use and cached under ~/.cache/huggingface/. See
# queries/services/indic_stt.py.

# --- WhatsApp / Picky Assist ----------------------------------------------

PICKY_ASSIST_TOKEN = config("PICKY_ASSIST_TOKEN", default="")
PICKY_ASSIST_WEBHOOK_SECRET = config("PICKY_ASSIST_WEBHOOK_SECRET", default="")
PICKY_ASSIST_SEND_URL = config(
    "PICKY_ASSIST_SEND_URL", default="https://api.pickyassist.com/v1/outbound/send"
)

# --- Logging ---------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "irri": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
