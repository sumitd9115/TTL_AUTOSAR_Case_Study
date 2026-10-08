"""
Shared pytest fixtures.

The tests never call the real Gemini API and never download an embedding model:
- `sentence_transformers` is replaced by a tiny deterministic hashing embedder,
- Gemini calls are replaced by a fake model.
Every test run uses a temporary storage folder, so your real data is untouched.
"""
import math
import re
import sys
import types
import zlib
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLE_PDF = BACKEND_DIR.parent / "data" / "Sample_AUTOSAR_HLD_BodyControlModule.pdf"
sys.path.insert(0, str(BACKEND_DIR))

# If the heavy real library isn't installed (e.g. CI), provide a stub so imports succeed.
try:  # pragma: no cover
    import sentence_transformers  # noqa: F401
except ImportError:  # pragma: no cover
    stub = types.ModuleType("sentence_transformers")
    stub.SentenceTransformer = object
    sys.modules["sentence_transformers"] = stub

STOPWORDS = {"the", "a", "an", "is", "of", "and", "to", "in", "for", "on", "what", "which", "are", "does", "do", "how"}
DIM = 512


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder (L2 normalised)."""

    def encode(self, texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False):
        import numpy as np

        vectors = []
        for text in texts:
            vec = [0.0] * DIM
            for tok in re.findall(r"[a-z0-9_]+", text.lower()):
                if tok in STOPWORDS:
                    continue
                vec[zlib.crc32(tok.encode()) % DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return np.array(vectors)


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def list(self):
        return iter([object()])

    def generate_content(self, model, contents, config=None):
        return _FakeResponse("FAKE-LLM ANSWER (Page 3, Section: 3.1 CentralLockingMgr Ports)")


class FakeGeminiClient:
    """Stands in for google.genai.Client - no network, no API key needed."""

    def __init__(self, *args, **kwargs):
        self.models = _FakeModels()


@pytest.fixture(scope="session")
def sample_pdf_bytes():
    return SAMPLE_PDF.read_bytes()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient

    from app import config, rag_pipeline

    tmp = tmp_path_factory.mktemp("storage")
    config.SQLITE_DB_PATH = tmp / "test.db"
    config.CHROMA_DB_PATH = tmp / "chroma"
    config.UPLOADS_DIR = tmp / "uploads"
    config.CHROMA_DB_PATH.mkdir()
    config.UPLOADS_DIR.mkdir()

    rag_pipeline._state.update({"chroma": None, "gemini_configured": False})
    rag_pipeline.get_embedder = lambda: FakeEmbedder()

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fake_gemini(monkeypatch):
    from app import rag_pipeline

    monkeypatch.setattr(rag_pipeline.genai, "Client", FakeGeminiClient)