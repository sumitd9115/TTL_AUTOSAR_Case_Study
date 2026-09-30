from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

try:
    BACKEND_URL = st.secrets["BACKEND_URL"]
except Exception:
    BACKEND_URL = "http://localhost:8000"

DEFAULT_TIMEOUT = 30
UPLOAD_TIMEOUT = 120     # PDF parsing + embedding can take longer
QUERY_TIMEOUT = 90       # Gemini generation can be slow, especially on retries

Result = Tuple[Optional[Any], Optional[str]]


def _handle(response: requests.Response) -> Result:
    """Turn a requests.Response into (data, None) or (None, error_message)."""
    if response.status_code < 400:
        try:
            return response.json(), None
        except ValueError:
            return response.text, None
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text or f"HTTP {response.status_code}"
    return None, str(detail)


def _get(path: str, params: Optional[dict] = None, timeout: int = DEFAULT_TIMEOUT) -> Result:
    try:
        return _handle(requests.get(f"{BACKEND_URL}{path}", params=params, timeout=timeout))
    except requests.exceptions.ConnectionError:
        return None, f"Cannot reach backend at {BACKEND_URL}. Is `uvicorn app.main:app` running?"
    except requests.exceptions.Timeout:
        return None, "Request timed out. The backend may be busy - try again."


def _post(path: str, json_body: Optional[dict] = None, files=None, timeout: int = DEFAULT_TIMEOUT) -> Result:
    try:
        return _handle(requests.post(f"{BACKEND_URL}{path}", json=json_body, files=files, timeout=timeout))
    except requests.exceptions.ConnectionError:
        return None, f"Cannot reach backend at {BACKEND_URL}. Is `uvicorn app.main:app` running?"
    except requests.exceptions.Timeout:
        return None, "Request timed out. The backend may be busy - try again."


def _delete(path: str, timeout: int = DEFAULT_TIMEOUT) -> Result:
    try:
        return _handle(requests.delete(f"{BACKEND_URL}{path}", timeout=timeout))
    except requests.exceptions.ConnectionError:
        return None, f"Cannot reach backend at {BACKEND_URL}. Is `uvicorn app.main:app` running?"
    except requests.exceptions.Timeout:
        return None, "Request timed out."


# System
def health() -> Result:
    return _get("/health")


def configure_gemini(api_key: str) -> Result:
    return _post("/configure", json_body={"gemini_api_key": api_key})


def get_audit_log(limit: int = 100) -> Result:
    return _get("/audit", params={"limit": limit})


# Documents
def upload_document(filename: str, file_bytes: bytes) -> Result:
    files = {"file": (filename, file_bytes, "application/pdf")}
    return _post("/documents/upload", files=files, timeout=UPLOAD_TIMEOUT)


def list_documents() -> Result:
    return _get("/documents")


def get_document(doc_id: str) -> Result:
    return _get(f"/documents/{doc_id}")


def delete_document(doc_id: str) -> Result:
    return _delete(f"/documents/{doc_id}")


# Architecture knowledge
def get_entities(doc_id: str, entity_type: Optional[str] = None) -> Result:
    params = {"entity_type": entity_type} if entity_type else None
    return _get(f"/documents/{doc_id}/entities", params=params)


def get_consistency_report(doc_id: str) -> Result:
    return _get(f"/documents/{doc_id}/consistency")


def get_component_report(doc_id: str, component: str) -> Result:
    return _get(f"/documents/{doc_id}/components/{component}/report", timeout=QUERY_TIMEOUT)


def export_document(doc_id: str, fmt: str = "json") -> Result:
    return _get(f"/documents/{doc_id}/export", params={"format": fmt})


def compare_documents(doc_id_a: str, doc_id_b: str) -> Result:
    return _post("/compare", json_body={"doc_id_a": doc_id_a, "doc_id_b": doc_id_b})


# Q&A
def query_document(doc_id: str, question: str, top_k: int = 5) -> Result:
    return _post(
        "/query",
        json_body={"doc_id": doc_id, "question": question, "top_k": top_k},
        timeout=QUERY_TIMEOUT,
    )


def get_chat_history(doc_id: str, limit: int = 50) -> Result:
    return _get(f"/documents/{doc_id}/history", params={"limit": limit})
