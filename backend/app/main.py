import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from . import config, document_store, entity_extraction, ingestion, rag_pipeline, schemas

# Logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(config.LOG_FILE_PATH, encoding="utf-8")],
)
logger = logging.getLogger("app.main")


# App lifecycle
@asynccontextmanager
async def lifespan(_app: FastAPI):
    document_store.init_db()
    if config.GEMINI_API_KEY_ENV:
        try:
            rag_pipeline.configure_gemini(config.GEMINI_API_KEY_ENV, validate=False)
            logger.info("Gemini configured from environment variable.")
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not configure Gemini from environment: %s", exc)
    logger.info("%s v%s started", config.APP_NAME, config.APP_VERSION)
    yield


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Error handling: domain errors -> proper HTTP status codes
@app.exception_handler(rag_pipeline.LLMNotConfiguredError)
async def _not_configured_handler(_request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(rag_pipeline.LLMConfigError)
async def _config_error_handler(_request, exc):
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(rag_pipeline.LLMGenerationError)
async def _generation_error_handler(_request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


def _require_document(doc_id: str) -> dict:
    doc = document_store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")
    return doc


# System
@app.get("/health", response_model=schemas.HealthResponse, tags=["system"])
def health():
    return schemas.HealthResponse(
        status="ok",
        version=config.APP_VERSION,
        gemini_configured=rag_pipeline.is_gemini_configured(),
        embedding_model=config.EMBEDDING_MODEL_NAME,
        llm_model=config.GEMINI_MODEL_NAME,
        documents_indexed=document_store.count_documents(),
    )


@app.post("/configure", response_model=schemas.ConfigureResponse, tags=["system"])
def configure(req: schemas.ConfigureRequest):
    """Set (and validate) the Gemini API key for this backend process."""
    rag_pipeline.configure_gemini(req.gemini_api_key.strip(), validate=True)
    document_store.log_audit("configure", detail="Gemini API key configured")
    return schemas.ConfigureResponse(status="configured", model=config.GEMINI_MODEL_NAME)


# Documents
def _read_upload_with_limit(file: UploadFile, destination: Path) -> None:
    """Stream the upload to disk while enforcing the size limit and PDF magic bytes."""
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    first_block = True
    with open(destination, "wb") as out:
        while True:
            block = file.file.read(1024 * 1024)
            if not block:
                break
            if first_block:
                if not block.startswith(b"%PDF"):
                    raise HTTPException(status_code=400, detail="File is not a valid PDF.")
                first_block = False
            written += len(block)
            if written > limit:
                raise HTTPException(
                    status_code=413, detail=f"File exceeds the {config.MAX_UPLOAD_MB} MB limit."
                )
            out.write(block)
    if written == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")


@app.post("/documents/upload", response_model=schemas.UploadResponse, tags=["documents"])
def upload_document(file: UploadFile = File(...)):
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    doc_id = uuid.uuid4().hex[:8]
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    save_path = config.UPLOADS_DIR / f"{doc_id}_{safe_name}"

    try:
        _read_upload_with_limit(file, save_path)

        # Duplicate detection: same bytes => reuse the existing document
        file_hash = ingestion.compute_file_hash(str(save_path))
        existing = document_store.find_document_by_hash(file_hash)
        if existing:
            save_path.unlink(missing_ok=True)
            counts = entity_extraction.count_by_type(document_store.get_entities(existing["doc_id"]))
            logger.info("Duplicate upload of %s -> reusing %s", filename, existing["doc_id"])
            return schemas.UploadResponse(**existing, duplicate=True, entity_counts=counts)

        # 1) Parse
        pages = ingestion.extract_pdf_content(str(save_path))
        if not any(p["lines"] or p["tables"] for p in pages):
            raise HTTPException(
                status_code=422,
                detail="No extractable text found. If this is a scanned PDF, install Tesseract OCR and pytesseract.",
            )
        metadata = ingestion.extract_document_metadata(pages)

        # 2) Chunk + structured knowledge
        chunks, structured_tables = ingestion.build_chunks(pages)
        entities = entity_extraction.extract_entities(structured_tables)
        component_names = [e["name"] for e in entities if e["entity_type"] == "component"]
        entities += entity_extraction.extract_dependencies(chunks, component_names)

        # 3) Embed + store
        num_chunks = rag_pipeline.index_chunks(doc_id, chunks)

        # 4) Persist metadata
        record = document_store.add_document(
            {
                "doc_id": doc_id,
                "filename": filename,
                "document_id": metadata["document_id"],
                "title": metadata["title"],
                "file_hash": file_hash,
                "num_pages": len(pages),
                "num_chunks": num_chunks,
                "num_entities": len(entities),
                "ocr_pages": sum(1 for p in pages if p["ocr_used"]),
            }
        )
        if entities:
            document_store.add_entities(doc_id, entities)
        document_store.log_audit("upload", doc_id, f"{filename}: {num_chunks} chunks, {len(entities)} entities")
        logger.info("Ingested %s as %s (%d pages, %d chunks, %d entities)", filename, doc_id, len(pages), num_chunks, len(entities))

        return schemas.UploadResponse(
            **record, duplicate=False, entity_counts=entity_extraction.count_by_type(entities)
        )

    except HTTPException:
        save_path.unlink(missing_ok=True)
        rag_pipeline.delete_collection(doc_id)
        raise
    except Exception as exc:
        logger.exception("Ingestion failed for %s", filename)
        save_path.unlink(missing_ok=True)
        rag_pipeline.delete_collection(doc_id)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc


@app.get("/documents", response_model=List[schemas.DocumentInfo], tags=["documents"])
def list_documents():
    return document_store.list_documents()


@app.get("/documents/{doc_id}", response_model=schemas.DocumentInfo, tags=["documents"])
def get_document(doc_id: str):
    return _require_document(doc_id)


@app.delete("/documents/{doc_id}", tags=["documents"])
def delete_document(doc_id: str):
    doc = _require_document(doc_id)
    rag_pipeline.delete_collection(doc_id)
    document_store.delete_document(doc_id)
    for path in config.UPLOADS_DIR.glob(f"{doc_id}_*"):
        path.unlink(missing_ok=True)
    document_store.log_audit("delete", doc_id, doc["filename"])
    return {"status": "deleted", "doc_id": doc_id}


# Structured architecture knowledge
@app.get("/documents/{doc_id}/entities", response_model=schemas.EntityListResponse, tags=["architecture"])
def get_entities(doc_id: str, entity_type: Optional[str] = Query(default=None)):
    _require_document(doc_id)
    all_entities = document_store.get_entities(doc_id)
    selected = [e for e in all_entities if not entity_type or e["entity_type"] == entity_type]
    return schemas.EntityListResponse(
        doc_id=doc_id,
        total=len(selected),
        counts=entity_extraction.count_by_type(all_entities),
        entities=selected,
    )


@app.get("/documents/{doc_id}/consistency", response_model=schemas.ConsistencyReport, tags=["architecture"])
def consistency_report(doc_id: str):
    _require_document(doc_id)
    findings = entity_extraction.run_consistency_checks(document_store.get_entities(doc_id))
    summary = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        summary[f["severity"]] += 1
    return schemas.ConsistencyReport(doc_id=doc_id, summary=summary, findings=findings)


@app.get(
    "/documents/{doc_id}/components/{component}/report",
    response_model=schemas.ComponentReport,
    tags=["architecture"],
)
def component_report(doc_id: str, component: str):
    _require_document(doc_id)
    entities = document_store.get_entities(doc_id)
    known = {e["name"].lower(): e["name"] for e in entities if e["entity_type"] == "component"}
    if component.lower() not in known:
        raise HTTPException(
            status_code=404,
            detail=f"Component '{component}' not found. Known components: {sorted(known.values())}",
        )
    canonical = known[component.lower()]
    result = rag_pipeline.generate_component_report(doc_id, canonical, entities)
    document_store.log_audit("component_report", doc_id, canonical)
    return schemas.ComponentReport(doc_id=doc_id, component=canonical, **result)


@app.get("/documents/{doc_id}/export", tags=["architecture"])
def export_document(doc_id: str, format: str = Query(default="json", pattern="^(json|csv)$")):
    doc = _require_document(doc_id)
    entities = document_store.get_entities(doc_id)
    document_store.log_audit("export", doc_id, format)
    if format == "csv":
        return Response(
            content=entity_extraction.entities_to_csv(entities),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{doc_id}_entities.csv"'},
        )
    return {
        "document": doc,
        "entity_counts": entity_extraction.count_by_type(entities),
        "entities": entities,
        "consistency_findings": entity_extraction.run_consistency_checks(entities),
    }


# Q&A
@app.post("/query", response_model=schemas.QueryResponse, tags=["qa"])
def query_document(req: schemas.QueryRequest):
    _require_document(req.doc_id)
    result = rag_pipeline.answer_question(req.doc_id, req.question, top_k=req.top_k)
    document_store.add_chat(
        req.doc_id, req.question, result["answer"], result["confidence"], result["grounded"], result["citations"]
    )
    document_store.log_audit("query", req.doc_id, req.question[:200])
    return result


@app.get("/documents/{doc_id}/history", response_model=List[schemas.ChatHistoryItem], tags=["qa"])
def chat_history(doc_id: str, limit: int = Query(default=50, ge=1, le=500)):
    _require_document(doc_id)
    return document_store.get_chat_history(doc_id, limit)


# Revision comparison
@app.post("/compare", response_model=schemas.CompareResponse, tags=["architecture"])
def compare_documents(req: schemas.CompareRequest):
    doc_a, doc_b = _require_document(req.doc_id_a), _require_document(req.doc_id_b)
    diff = entity_extraction.compare_entity_sets(
        document_store.get_entities(req.doc_id_a), document_store.get_entities(req.doc_id_b)
    )
    document_store.log_audit("compare", req.doc_id_a, f"vs {req.doc_id_b}")
    return schemas.CompareResponse(doc_a=doc_a["filename"], doc_b=doc_b["filename"], **diff)


# Audit
@app.get("/audit", response_model=List[schemas.AuditItem], tags=["system"])
def audit_log(limit: int = Query(default=100, ge=1, le=1000)):
    return document_store.get_audit_log(limit)
