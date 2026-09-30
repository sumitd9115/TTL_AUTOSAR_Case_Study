# AUTOSAR HLD Document Analysis Assistant

A RAG-based engineering assistant that lets automotive architects and developers
upload an AUTOSAR High-Level Design (HLD) PDF and:

- ask natural-language questions grounded in the document, with page/section citations
- browse structured architecture knowledge (components, ports, runnables, dependencies, issues)
  extracted automatically from the document's own tables — no LLM required for this part
- run automated consistency checks (missing ports, unknown component owners, orphaned runnables)
- compare two document revisions and see what was added, removed, or changed
- review a full audit trail of every upload, query, export and comparison

Built as a Pilot Case Study for an Automotive Engineering AI Platform.

---

## Architecture

```
Browser
   │
   ▼
Streamlit UI  (frontend/)
   │  HTTP / REST (JSON)
   ▼
FastAPI backend  (backend/app/)
   │
   ├── ingestion.py          PDF parsing (position-aware), OCR fallback, section-aware chunking
   ├── entity_extraction.py  Rule-based extraction: components, ports, runnables, issues,
   │                         dependencies, consistency checks, revision diff (no LLM)
   ├── rag_pipeline.py       Local embeddings → ChromaDB → identifier-aware retrieval →
   │                         Gemini generation, grounded and cited
   ├── document_store.py     SQLite: documents, entities, chat history, audit log
   ├── schemas.py            Pydantic request/response contracts
   └── main.py               REST API (FastAPI routes)
```

**Why this split matters:** the frontend only ever talks to the backend over HTTP, so the
Streamlit UI could be swapped for React later without touching a single line of backend code.

---

## Tech Stack

| Layer          | Choice                                   | Why |
|----------------|-------------------------------------------|-----|
| LLM            | Gemini API (`gemini-flash-latest`)        | Free tier, no local GPU needed |
| Embeddings     | `sentence-transformers` (`all-MiniLM-L6-v2`) | Local, free, no API quota spent on embedding |
| Vector DB      | ChromaDB                                  | Local, persistent, file-based, cosine similarity |
| Structured DB  | SQLite                                    | Documents, entities, chat history, audit log |
| Backend API    | FastAPI                                   | Auto-generated docs at `/docs`, async-ready |
| Frontend       | Streamlit                                 | Fast to build, good for an engineering-tool pilot |

---

## Folder Structure

```
autosar-hld-assistant/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entrypoint, all routes
│   │   ├── config.py            # settings (paths, model names, env vars)
│   │   ├── ingestion.py         # PDF parsing + section-aware chunking
│   │   ├── entity_extraction.py # component/port/runnable/issue extraction, consistency, diff
│   │   ├── rag_pipeline.py      # embeddings, ChromaDB, Gemini generation
│   │   ├── schemas.py           # Pydantic request/response models
│   │   └── document_store.py    # SQLite persistence layer
│   ├── storage/                 # auto-created at runtime, gitignored
│   │   ├── chroma_db/
│   │   └── uploads/
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py          # fake embedder + fake Gemini fixtures
│   │   ├── test_api.py
│   │   └── test_entity_extraction.py
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── streamlit_app.py         # 5-tab UI: Chat, Explorer, Consistency, Compare, Audit
│   ├── api_client.py            # wraps every backend endpoint
│   ├── ui_components.py         # reusable UI pieces
│   ├── requirements.txt
│   └── .streamlit/
│       ├── config.toml
│       └── secrets.toml.example
│
├── data/
│   ├── Sample_AUTOSAR_HLD_BodyControlModule.pdf   # mock test document
│   └── generate_mock_hld.py                        # regenerates the sample PDF
│
├── .gitignore
└── README.md
```

---

## Setup

### 1. Get a free Gemini API key
Go to https://aistudio.google.com/apikey, sign in with a Google account, and generate a key.
You'll paste it into the running app (sidebar) — nothing needs to be hardcoded.

### 2. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests -q       # sanity check: should show "21 passed"
```

Optional: copy `.env.example` to `.env` if you want to set `GEMINI_API_KEY` or other
settings via environment variables instead of the UI.

### 3. Frontend

```bash
cd frontend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Running

**Terminal 1 — backend:**
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
Interactive API docs: http://localhost:8000/docs

**Terminal 2 — frontend:**
```bash
cd frontend
source venv/bin/activate
streamlit run streamlit_app.py
```
Opens at: http://localhost:8501

---

## Using It

1. Paste your Gemini API key into the sidebar and click **Configure**.
2. Upload `data/Sample_AUTOSAR_HLD_BodyControlModule.pdf` (included) or your own HLD PDF.
3. Explore the tabs:
   - **Chat & Q&A** — ask things like *"What ports does CentralLockingMgr have?"*
   - **Architecture Explorer** — browse extracted components/ports/runnables, generate a
     full component report, export as JSON/CSV
   - **Consistency Report** — see automated findings (e.g. components with no ports defined)
   - **Compare Revisions** — upload a second version of the same HLD and diff them
   - **Audit Log** — see everything that happened, with timestamps

---

## Design Notes

- **Grounded, not guessed:** if retrieval similarity is too low, the backend refuses to call
  the LLM and returns "insufficient information" instead of risking a hallucinated answer.
- **No LLM needed for structured facts:** components, ports, runnables and dependencies are
  extracted deterministically from the document's own tables via `entity_extraction.py`,
  so those facts are 100% traceable to source rows, not model output.
- **Duplicate detection:** re-uploading the same PDF (by content hash) reuses the existing
  document instead of re-indexing it.
- **Retry + backoff:** Gemini rate-limit errors (HTTP 429) are retried automatically with
  exponential backoff before surfacing an error to the user.

## Known Limitations (v1 pilot scope)

- OCR fallback for scanned PDFs requires `pytesseract` + the Tesseract binary (not installed
  by default — see the commented-out line in `backend/requirements.txt`).
- Single-user, single-machine SQLite — not built for concurrent multi-user production load.
- No authentication/role-based access control yet (flagged as a Phase-2 item in the
  original case study document).

## Next Steps

- Add OCR support for scanned HLDs
- Add role-based access control and per-project document isolation
- Extend entity extraction to HARA/TARA-specific tables (Case Studies 2 and 3)
- Swap Gemini for a locally hosted LLM if data-privacy requirements demand it
