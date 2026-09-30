import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect():
    conn = sqlite3.connect(str(config.SQLITE_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# Schema
def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id       TEXT PRIMARY KEY,
                filename     TEXT NOT NULL,
                document_id  TEXT,
                title        TEXT,
                file_hash    TEXT NOT NULL,
                num_pages    INTEGER NOT NULL,
                num_chunks   INTEGER NOT NULL,
                num_entities INTEGER NOT NULL DEFAULT 0,
                ocr_pages    INTEGER NOT NULL DEFAULT 0,
                uploaded_at  TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'ready'
            );
            CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);

            CREATE TABLE IF NOT EXISTS entities (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id          TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                entity_type     TEXT NOT NULL,
                name            TEXT NOT NULL,
                attributes_json TEXT NOT NULL DEFAULT '{}',
                page            INTEGER,
                section         TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_entities_doc ON entities(doc_id, entity_type);

            CREATE TABLE IF NOT EXISTS chat_history (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id         TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                question       TEXT NOT NULL,
                answer         TEXT NOT NULL,
                confidence     TEXT NOT NULL,
                grounded       INTEGER NOT NULL,
                citations_json TEXT NOT NULL DEFAULT '[]',
                created_at     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_doc ON chat_history(doc_id);

            CREATE TABLE IF NOT EXISTS audit_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action    TEXT NOT NULL,
                doc_id    TEXT,
                detail    TEXT
            );
            """
        )


# Documents
def add_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    record = {
        "doc_id": doc["doc_id"],
        "filename": doc["filename"],
        "document_id": doc.get("document_id"),
        "title": doc.get("title"),
        "file_hash": doc["file_hash"],
        "num_pages": doc["num_pages"],
        "num_chunks": doc["num_chunks"],
        "num_entities": doc.get("num_entities", 0),
        "ocr_pages": doc.get("ocr_pages", 0),
        "uploaded_at": _now(),
        "status": doc.get("status", "ready"),
    }
    with _connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (doc_id, filename, document_id, title, file_hash, num_pages, num_chunks,
                num_entities, ocr_pages, uploaded_at, status)
               VALUES (:doc_id, :filename, :document_id, :title, :file_hash, :num_pages,
                       :num_chunks, :num_entities, :ocr_pages, :uploaded_at, :status)""",
            record,
        )
    return record


def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def find_document_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE file_hash = ? LIMIT 1", (file_hash,)
        ).fetchone()
    return dict(row) if row else None


def list_documents() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY uploaded_at DESC").fetchall()
    return [dict(r) for r in rows]


def count_documents() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]


def delete_document(doc_id: str) -> bool:
    """Deletes the document and (via ON DELETE CASCADE) its entities and chat history."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        return cur.rowcount > 0


# Entities
def add_entities(doc_id: str, entities: List[Dict[str, Any]]) -> int:
    rows = [
        (
            doc_id,
            e["entity_type"],
            e["name"],
            json.dumps(e.get("attributes", {}), ensure_ascii=False),
            e.get("page"),
            e.get("section"),
        )
        for e in entities
    ]
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO entities (doc_id, entity_type, name, attributes_json, page, section)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def get_entities(doc_id: str, entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    query = "SELECT * FROM entities WHERE doc_id = ?"
    params: List[Any] = [doc_id]
    if entity_type:
        query += " AND entity_type = ?"
        params.append(entity_type)
    query += " ORDER BY id"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "entity_type": r["entity_type"],
            "name": r["name"],
            "attributes": json.loads(r["attributes_json"]),
            "page": r["page"],
            "section": r["section"],
        }
        for r in rows
    ]


# Chat history
def add_chat(
    doc_id: str,
    question: str,
    answer: str,
    confidence: str,
    grounded: bool,
    citations: List[Dict[str, Any]],
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO chat_history
               (doc_id, question, answer, confidence, grounded, citations_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                question,
                answer,
                confidence,
                1 if grounded else 0,
                json.dumps(citations, ensure_ascii=False),
                _now(),
            ),
        )


def get_chat_history(doc_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_history WHERE doc_id = ? ORDER BY id DESC LIMIT ?",
            (doc_id, limit),
        ).fetchall()
    items = [
        {
            "id": r["id"],
            "question": r["question"],
            "answer": r["answer"],
            "confidence": r["confidence"],
            "grounded": bool(r["grounded"]),
            "citations": json.loads(r["citations_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return list(reversed(items))  # oldest first for display


# Audit log
def log_audit(action: str, doc_id: Optional[str] = None, detail: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, action, doc_id, detail) VALUES (?, ?, ?, ?)",
            (_now(), action, doc_id, detail),
        )


def get_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
