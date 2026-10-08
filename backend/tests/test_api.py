"""End-to-end API tests (fake embedder + fake Gemini). Tests run in file order and share one uploaded document."""
import pytest

STATE = {}


def test_health_before_configuration(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["gemini_configured"] is False


def test_rejects_non_pdf_extension(client):
    r = client.post("/documents/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_rejects_fake_pdf_without_magic_bytes(client):
    r = client.post("/documents/upload", files={"file": ("fake.pdf", b"not really a pdf", "application/pdf")})
    assert r.status_code == 400


def test_upload_sample_hld(client, sample_pdf_bytes):
    r = client.post("/documents/upload", files={"file": ("Sample.pdf", sample_pdf_bytes, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    STATE["doc_id"] = body["doc_id"]
    assert body["document_id"] == "HLD-BCM-2026-v3.2"
    assert body["num_pages"] >= 5 and body["duplicate"] is False
    assert body["entity_counts"]["component"] == 6
    assert body["entity_counts"]["port"] == 11
    assert body["entity_counts"]["runnable"] == 8
    assert body["entity_counts"]["dependency"] == 3
    assert body["entity_counts"]["issue"] == 3


def test_duplicate_upload_reuses_document(client, sample_pdf_bytes):
    r = client.post("/documents/upload", files={"file": ("Copy.pdf", sample_pdf_bytes, "application/pdf")})
    assert r.status_code == 200
    assert r.json()["duplicate"] is True and r.json()["doc_id"] == STATE["doc_id"]


def test_entities_filter(client):
    r = client.get(f"/documents/{STATE['doc_id']}/entities", params={"entity_type": "component"})
    body = r.json()
    assert body["total"] == 6
    assert "CentralLockingMgr" in {e["name"] for e in body["entities"]}


def test_consistency_report(client):
    body = client.get(f"/documents/{STATE['doc_id']}/consistency").json()
    assert body["summary"]["error"] == 0
    assert body["summary"]["warning"] == 3   # WiperCtrl, BCM_DiagMgr, VehicleStateMonitor have no ports
    assert body["summary"]["info"] == 3      # three open issues


def test_query_requires_gemini_configuration(client):
    r = client.post("/query", json={"doc_id": STATE["doc_id"], "question": "What ports does CentralLockingMgr have?"})
    assert r.status_code == 400


def test_configure_validates_input_and_succeeds(client, fake_gemini):
    assert client.post("/configure", json={"gemini_api_key": "short"}).status_code == 422
    r = client.post("/configure", json={"gemini_api_key": "AIza-fake-key-for-testing"})
    assert r.status_code == 200 and r.json()["status"] == "configured"


def test_grounded_query_returns_relevant_citations(client, fake_gemini):
    r = client.post("/query", json={"doc_id": STATE["doc_id"], "question": "What ports does CentralLockingMgr have?"})
    body = r.json()
    assert r.status_code == 200 and body["grounded"] is True
    assert body["answer"].startswith("FAKE-LLM")
    assert any("CentralLockingMgr Ports" in c["section"] for c in body["citations"])


def test_irrelevant_query_is_refused_without_calling_llm(client, fake_gemini):
    r = client.post("/query", json={"doc_id": STATE["doc_id"], "question": "Explain quantum chromodynamics gluon confinement"})
    body = r.json()
    assert body["grounded"] is False and body["confidence"] == "low"
    assert "do not contain enough information" in body["answer"]


def test_query_unknown_document_404(client):
    assert client.post("/query", json={"doc_id": "nope", "question": "anything?"}).status_code == 404


def test_component_report(client, fake_gemini):
    r = client.get(f"/documents/{STATE['doc_id']}/components/centrallockingmgr/report")
    body = r.json()
    assert r.status_code == 200 and body["component"] == "CentralLockingMgr"
    assert len(body["structured_facts"]["ports"]) == 4
    assert body["structured_facts"]["depends_on"] == ["VehicleStateMonitor"]
    assert client.get(f"/documents/{STATE['doc_id']}/components/Ghost/report").status_code == 404


def test_export_csv_and_json(client):
    csv_resp = client.get(f"/documents/{STATE['doc_id']}/export", params={"format": "csv"})
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert csv_resp.text.splitlines()[0] == "entity_type,name,page,section,attributes_json"
    json_resp = client.get(f"/documents/{STATE['doc_id']}/export").json()
    assert json_resp["entity_counts"]["port"] == 11


def test_compare_document_with_itself_has_no_differences(client):
    r = client.post("/compare", json={"doc_id_a": STATE["doc_id"], "doc_id_b": STATE["doc_id"]})
    body = r.json()
    assert body["added"] == [] and body["removed"] == [] and body["changed"] == []
    assert body["unchanged_count"] > 0


def test_history_and_audit_trail(client):
    history = client.get(f"/documents/{STATE['doc_id']}/history").json()
    assert len(history) == 2 and history[0]["question"].startswith("What ports")
    actions = {a["action"] for a in client.get("/audit").json()}
    assert {"upload", "query", "configure", "export", "compare", "component_report"} <= actions


def test_delete_document(client):
    assert client.delete(f"/documents/{STATE['doc_id']}").status_code == 200
    assert client.get(f"/documents/{STATE['doc_id']}").status_code == 404
    assert client.get("/documents").json() == []