from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from . import config


# System
class ConfigureRequest(BaseModel):
    gemini_api_key: str = Field(..., min_length=10, description="Google Gemini API key")


class ConfigureResponse(BaseModel):
    status: str
    model: str


class HealthResponse(BaseModel):
    status: str
    version: str
    gemini_configured: bool
    embedding_model: str
    llm_model: str
    documents_indexed: int


# Documents
class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    document_id: Optional[str] = None   # e.g. HLD-BCM-2026-v3.2 parsed from the PDF
    title: Optional[str] = None
    file_hash: str
    num_pages: int
    num_chunks: int
    num_entities: int
    ocr_pages: int = 0
    uploaded_at: str
    status: str = "ready"


class UploadResponse(DocumentInfo):
    duplicate: bool = False
    entity_counts: Dict[str, int] = {}


# Query / Q&A
class QueryRequest(BaseModel):
    doc_id: str
    question: str = Field(..., min_length=3, max_length=1000)
    top_k: int = Field(default=config.DEFAULT_TOP_K, ge=1, le=15)


class Citation(BaseModel):
    page: Optional[int] = None
    section: str
    score: float
    snippet: str


class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence: Literal["high", "medium", "low"]
    grounded: bool  # False when evidence was too weak and the LLM was not called
    latency_ms: int


class ChatHistoryItem(BaseModel):
    id: int
    question: str
    answer: str
    confidence: str
    grounded: bool
    citations: List[Dict[str, Any]]
    created_at: str


# Structured architecture knowledge
class EntityItem(BaseModel):
    entity_type: str  # component | port | runnable | issue | dependency | reference | revision
    name: str
    attributes: Dict[str, Any] = {}
    page: Optional[int] = None
    section: Optional[str] = None


class EntityListResponse(BaseModel):
    doc_id: str
    total: int
    counts: Dict[str, int]
    entities: List[EntityItem]


class ConsistencyFinding(BaseModel):
    severity: Literal["error", "warning", "info"]
    check: str
    message: str
    entity: Optional[str] = None


class ConsistencyReport(BaseModel):
    doc_id: str
    summary: Dict[str, int]
    findings: List[ConsistencyFinding]


class ComponentReport(BaseModel):
    doc_id: str
    component: str
    report: str
    structured_facts: Dict[str, Any]
    citations: List[Citation]


# Revision comparison
class CompareRequest(BaseModel):
    doc_id_a: str = Field(..., description="Baseline / older document")
    doc_id_b: str = Field(..., description="Newer document")


class EntityChange(BaseModel):
    entity_type: str
    name: str
    differences: Dict[str, Dict[str, Any]]  # attribute -> {"a": ..., "b": ...}


class CompareResponse(BaseModel):
    doc_a: str
    doc_b: str
    added: List[EntityItem]
    removed: List[EntityItem]
    changed: List[EntityChange]
    unchanged_count: int


# Audit
class AuditItem(BaseModel):
    id: int
    timestamp: str
    action: str
    doc_id: Optional[str] = None
    detail: Optional[str] = None
