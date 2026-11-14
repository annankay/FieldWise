"""Central configuration. Values can be overridden with environment variables or a .env file."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
DATA_DIR = BACKEND / "data"          # crop table + reference sites (shipped with the code)
FRONTEND_DIR = ROOT / "frontend"


def _load_dotenv() -> None:
    """Tiny .env loader so we don't need python-dotenv."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


# Where downloaded NASA data is stored. On a server, point this at a persistent disk/volume.
CACHE_DIR = Path(os.environ.get("FIELDWISE_DATA_DIR", str(DATA_DIR / "cache"))).expanduser()

# Production uses REAL data only. Synthetic data exists only for development and automated tests.
DEMO_MODE = _flag("FIELDWISE_DEMO", "0")

# Google Earth Engine cloud project id (required by GEE since 2024).
GEE_PROJECT = os.environ.get("GEE_PROJECT", "").strip()
# On a server use a service account instead of a personal login.
GEE_SERVICE_ACCOUNT = os.environ.get("GEE_SERVICE_ACCOUNT", "").strip()
GEE_KEY_FILE = os.environ.get("GEE_KEY_FILE", "").strip()

# NASA Earthdata login, used for ECOSTRESS through AppEEARS.
EARTHDATA_USERNAME = os.environ.get("EARTHDATA_USERNAME", "").strip()
EARTHDATA_PASSWORD = os.environ.get("EARTHDATA_PASSWORD", "").strip()

# Optional: an Anthropic API key enables the plain-language / local-language explainer.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
LLM_MODEL = os.environ.get("FIELDWISE_LLM_MODEL", "claude-haiku-5-5")

# Climate record used for profiles (POWER daily starts 1981; we use 1991 onwards = 35 years).
START_YEAR = int(os.environ.get("FIELDWISE_START_YEAR", "1991"))
END_YEAR = int(os.environ.get("FIELDWISE_END_YEAR", "2025"))

# Size of the field-vulnerability grid (cells per side, ~30 m each, from SRTM).
FIELD_GRID_CELLS = 25

# Rotation cycle length in months (2 years).
CYCLE_MONTHS = 24

HOST = os.environ.get("FIELDWISE_HOST", "127.0.0.1")
PORT = int(os.environ.get("FIELDWISE_PORT", os.environ.get("PORT", "8000")))

# Comma-separated list of other websites allowed to call the API (empty = only FieldWise itself).
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("FIELDWISE_ALLOWED_ORIGINS", "").split(",") if o.strip()]
# Protect NASA quotas: new-field downloads per visitor per hour, and at the same time.
FETCH_LIMIT_PER_HOUR = int(os.environ.get("FIELDWISE_FETCH_LIMIT_PER_HOUR", "6"))
MAX_CONCURRENT_FETCHES = int(os.environ.get("FIELDWISE_MAX_CONCURRENT_FETCHES", "2"))
# How many analysed fields to keep in memory.
MAX_SITES_IN_MEMORY = int(os.environ.get("FIELDWISE_MAX_SITES_IN_MEMORY", "24"))

CACHE_DIR.mkdir(parents=True, exist_ok=True)
