import requests as _requests
import streamlit as st

import api_client as api
import ui_components as ui

st.set_page_config(page_title="AUTOSAR HLD Assistant", page_icon="🚗", layout="wide")

# Session state
defaults = {
    "gemini_configured": False,
    "active_doc_id": None,
    "active_doc_name": None,
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)


def refresh_documents():
    docs, err = api.list_documents()
    if err:
        st.session_state["_doc_list_error"] = err
        return []
    st.session_state["_doc_list_error"] = None
    return docs or []


# Sidebar: backend status, Gemini setup, document upload/selection
with st.sidebar:
    st.title("🚗 HLD Assistant")

    health, health_err = api.health()
    if health_err:
        st.error(f"Backend unreachable:\n\n{health_err}")
        st.stop()
    st.session_state["gemini_configured"] = health["gemini_configured"]

    st.caption(f"Backend v{health['version']} · {health['documents_indexed']} document(s) indexed")
    ui.status_pill(health["gemini_configured"], "Gemini configured", "Gemini not configured yet")

    st.divider()
    st.subheader("1. Configure Gemini")
    if not health["gemini_configured"]:
        api_key = st.text_input(
            "Gemini API key", type="password",
            help="Free key: https://aistudio.google.com/apikey",
        )
        if st.button("Configure", use_container_width=True, disabled=not api_key):
            with st.spinner("Validating key..."):
                _, err = api.configure_gemini(api_key)
            if err:
                st.error(err)
            else:
                st.success("Gemini configured.")
                st.rerun()
    else:
        st.caption(f"Model: `{health['llm_model']}`")

    st.divider()
    st.subheader("2. Upload a Document")
    uploaded_file = st.file_uploader("AUTOSAR HLD PDF", type=["pdf"], label_visibility="collapsed")
    if uploaded_file and st.button("Ingest Document", use_container_width=True, type="primary"):
        with st.spinner("Parsing, chunking and embedding... this can take a bit for large PDFs."):
            result, err = api.upload_document(uploaded_file.name, uploaded_file.getvalue())
        if err:
            st.error(err)
        else:
            st.session_state["active_doc_id"] = result["doc_id"]
            st.session_state["active_doc_name"] = result["filename"]
            tag = " (already ingested - reused existing copy)" if result.get("duplicate") else ""
            st.success(
                f"Ingested '{result['filename']}'{tag}\n\n"
                f"{result['num_pages']} pages · {result['num_chunks']} chunks · "
                f"{sum(result.get('entity_counts', {}).values())} entities extracted"
            )
            st.rerun()

    st.divider()
    st.subheader("3. Active Document")
    documents = refresh_documents()
    picked = ui.document_picker(documents, "Select a document to work with", key="doc_picker")
    if picked and picked != st.session_state["active_doc_id"]:
        st.session_state["active_doc_id"] = picked
        st.session_state["active_doc_name"] = next(
            (d["filename"] for d in documents if d["doc_id"] == picked), picked
        )
        st.rerun()

    if st.session_state["active_doc_id"]:
        active = next((d for d in documents if d["doc_id"] == st.session_state["active_doc_id"]), None)
        if active:
            st.info(
                f"**{active['filename']}**\n\n"
                f"`{active['doc_id']}` · {active['num_pages']} pages · "
                f"{active['num_entities']} entities"
                + (f"\n\nDocument ID: `{active['document_id']}`" if active.get("document_id") else "")
            )
            if st.button("🗑️ Delete this document", use_container_width=True):
                _, err = api.delete_document(active["doc_id"])
                if err:
                    st.error(err)
                else:
                    st.session_state["active_doc_id"] = None
                    st.rerun()

active_doc_id = st.session_state["active_doc_id"]

# Main area: tabs
st.title("AUTOSAR HLD Document Analysis Assistant")
st.caption(
    "Upload an AUTOSAR High-Level Design PDF, ask grounded questions, and review "
    "extracted architecture knowledge."
)

tab_chat, tab_explorer, tab_consistency, tab_compare, tab_audit = st.tabs(
    ["💬 Chat & Q&A", "🧩 Architecture Explorer", "✅ Consistency Report",
     "🔀 Compare Revisions", "🧾 Audit Log"]
)

# ---------------- Tab 1: Chat & Q&A ----------------
with tab_chat:
    if not active_doc_id:
        st.info("👈 Upload or select a document from the sidebar to start asking questions.")
    else:
        if not st.session_state["gemini_configured"]:
            st.warning("Configure your Gemini API key in the sidebar before asking questions.")

        history, err = api.get_chat_history(active_doc_id)
        if err:
            st.error(err)
        else:
            for turn in history:
                ui.render_chat_turn(turn["question"], turn)

        question = st.chat_input("Ask a question about this HLD document...")
        if question:
            with st.chat_message("user"):
                st.write(question)
            with st.chat_message("assistant"):
                with st.spinner("Retrieving relevant sections and generating an answer..."):
                    result, err = api.query_document(active_doc_id, question)
                if err:
                    st.error(err)
                else:
                    st.write(result["answer"])
                    st.caption(ui.confidence_badge(result["confidence"], result["grounded"]))
                    ui.render_citations(result["citations"])
                    st.rerun()

        with st.expander("💡 Try these example questions"):
            st.markdown(
                "- What components does CentralLockingMgr depend on?\n"
                "- What is the periodicity of the WindowLiftMgr runnable?\n"
                "- Summarize the auto-lock functional flow.\n"
                "- What known issues exist related to WindowLiftMgr?\n"
                "- What interfaces does LightingCtrl expose?"
            )

# ---------------- Tab 2: Architecture Explorer ----------------
with tab_explorer:
    if not active_doc_id:
        st.info("👈 Upload or select a document from the sidebar first.")
    else:
        entity_data, err = api.get_entities(active_doc_id)
        if err:
            st.error(err)
        else:
            counts = entity_data["counts"]
            cols = st.columns(max(len(counts), 1))
            for col, (etype, count) in zip(cols, counts.items()):
                col.metric(f"{ui.entity_type_icon(etype)} {etype.capitalize()}", count)

            st.divider()
            entity_types = ["All"] + sorted(counts.keys())
            chosen_type = st.radio("Filter by type", entity_types, horizontal=True)
            filtered = (
                entity_data["entities"]
                if chosen_type == "All"
                else [e for e in entity_data["entities"] if e["entity_type"] == chosen_type]
            )
            ui.render_entity_table(filtered)

            st.divider()
            st.subheader("📋 Component Report")
            component_names = sorted(
                {e["name"] for e in entity_data["entities"] if e["entity_type"] == "component"}
            )
            if not component_names:
                st.caption("No components were extracted from this document.")
            else:
                chosen_component = st.selectbox("Choose a component", component_names)
                if st.button("Generate Report", type="primary"):
                    if not st.session_state["gemini_configured"]:
                        st.warning("Configure your Gemini API key in the sidebar first.")
                    else:
                        with st.spinner(f"Assembling report for {chosen_component}..."):
                            report, err = api.get_component_report(active_doc_id, chosen_component)
                        if err:
                            st.error(err)
                        else:
                            st.markdown(report["report"])
                            with st.expander("🔍 Structured facts (extracted from tables, no LLM)"):
                                st.json(report["structured_facts"])
                            ui.render_citations(report["citations"])

            st.divider()
            st.subheader("⬇️ Export")
            ecol1, ecol2 = st.columns(2)
            with ecol1:
                export_json, err = api.export_document(active_doc_id, "json")
                if not err:
                    import json as _json
                    st.download_button(
                        "Download full export (JSON)",
                        data=_json.dumps(export_json, indent=2).encode(),
                        file_name=f"{active_doc_id}_export.json",
                        mime="application/json",
                        use_container_width=True,
                    )
            with ecol2:
                try:
                    csv_resp = _requests.get(
                        f"{api.BACKEND_URL}/documents/{active_doc_id}/export",
                        params={"format": "csv"},
                        timeout=api.DEFAULT_TIMEOUT,
                    )
                    st.download_button(
                        "Download entities (CSV)",
                        data=csv_resp.content,
                        file_name=f"{active_doc_id}_entities.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                except Exception as exc:
                    st.caption(f"CSV export unavailable: {exc}")

# ---------------- Tab 3: Consistency Report ----------------
with tab_consistency:
    if not active_doc_id:
        st.info("👈 Upload or select a document from the sidebar first.")
    else:
        report, err = api.get_consistency_report(active_doc_id)
        if err:
            st.error(err)
        else:
            summary = report["summary"]
            c1, c2, c3 = st.columns(3)
            c1.metric("🔴 Errors", summary.get("error", 0))
            c2.metric("🟠 Warnings", summary.get("warning", 0))
            c3.metric("🔵 Info", summary.get("info", 0))
            st.divider()
            ui.render_consistency_findings(report["findings"])
            st.caption(
                "These checks are deterministic (no LLM) - they compare component, port, "
                "runnable and dependency tables against each other for gaps and mismatches. "
                "Always confirm findings against the source document before acting on them."
            )

# ---------------- Tab 4: Compare Revisions ----------------
with tab_compare:
    st.caption("Compare the extracted architecture knowledge between two uploaded document revisions.")
    documents = refresh_documents()
    col1, col2 = st.columns(2)
    with col1:
        doc_a = ui.document_picker(documents, "Baseline (older) document", key="compare_a")
    with col2:
        doc_b = ui.document_picker(documents, "New (updated) document", key="compare_b")

    if doc_a and doc_b and doc_a == doc_b:
        st.warning("Choose two different documents to compare.")
    elif doc_a and doc_b and st.button("Compare", type="primary"):
        with st.spinner("Comparing entity sets..."):
            diff, err = api.compare_documents(doc_a, doc_b)
        if err:
            st.error(err)
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("➕ Added", len(diff["added"]))
            c2.metric("➖ Removed", len(diff["removed"]))
            c3.metric("✏️ Changed", len(diff["changed"]))
            st.caption(f"{diff['unchanged_count']} entities are identical between both documents.")

            if diff["added"]:
                st.subheader("➕ Added")
                ui.render_entity_table(diff["added"])
            if diff["removed"]:
                st.subheader("➖ Removed")
                ui.render_entity_table(diff["removed"])
            if diff["changed"]:
                st.subheader("✏️ Changed")
                for c in diff["changed"]:
                    st.markdown(f"**{ui.entity_type_icon(c['entity_type'])} {c['name']}** ({c['entity_type']})")
                    for attr, values in c["differences"].items():
                        st.markdown(f"- `{attr}`: `{values['a']}` → `{values['b']}`")
            if not (diff["added"] or diff["removed"] or diff["changed"]):
                st.success("No differences found between these two documents.")

# ---------------- Tab 5: Audit Log ----------------
with tab_audit:
    st.caption("Every upload, query, export, comparison and configuration change, for traceability.")
    limit = st.slider("Number of entries to show", 10, 500, 100, step=10)
    entries, err = api.get_audit_log(limit)
    if err:
        st.error(err)
    elif not entries:
        st.info("No activity recorded yet.")
    else:
        rows = [
            {
                "Timestamp": e["timestamp"],
                "Action": e["action"],
                "Document": e.get("doc_id") or "-",
                "Detail": e.get("detail") or "",
            }
            for e in entries
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
