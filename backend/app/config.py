import os
from pathlib import Path

# Base paths
BACKEND_ROOT = Path(__file__).resolve().parent.parent  # .../backend

# Optional .env support (python-dotenv). Silently skipped if not installed.
try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


STORAGE_DIR = BACKEND_ROOT / "storage"
CHROMA_DB_PATH = STORAGE_DIR / "chroma_db"
UPLOADS_DIR = STORAGE_DIR / "uploads"
SQLITE_DB_PATH = STORAGE_DIR / "hld_assistant.db"
LOG_FILE_PATH = STORAGE_DIR / "app.log"

for _p in (STORAGE_DIR, CHROMA_DB_PATH, UPLOADS_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# Application metadata
APP_NAME = "AUTOSAR HLD Document Analysis Assistant"
APP_VERSION = "1.0.0"

# Model
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-flash-latest")
GEMINI_API_KEY_ENV = os.environ.get("GEMINI_API_KEY", "")  # optional dev fallback
LLM_TEMPERATURE = 0.1          # low = factual, deterministic answers
LLM_MAX_OUTPUT_TOKENS = 4096  # headroom: newer Gemini models may spend tokens on internal reasoning
LLM_MAX_RETRIES = 3            # retries on rate-limit (HTTP 429) errors
LLM_RETRY_BASE_SECONDS = 2.0   # exponential backoff base

# Ingestion
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
MAX_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 25
OCR_ENABLED = _env_bool("OCR_ENABLED", True)  # used only if pytesseract is installed
OCR_RESOLUTION_DPI = 200

# Retrieval / answer quality
DEFAULT_TOP_K = 5
RETRIEVAL_OVERFETCH_FACTOR = 3     # fetch top_k * factor, then re-rank
IDENTIFIER_BOOST_PER_MATCH = 0.12  # bonus for exact identifier matches in a chunk
IDENTIFIER_BOOST_CAP = 0.30

# Similarity = 1 - cosine distance (range roughly 0..1, higher = better)
MIN_SIMILARITY_TO_ANSWER = 0.20    # below this we refuse instead of guessing
CONFIDENCE_HIGH_THRESHOLD = 0.55
CONFIDENCE_MEDIUM_THRESHOLD = 0.35

# API server
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
    ).split(",")
    if o.strip()
]
