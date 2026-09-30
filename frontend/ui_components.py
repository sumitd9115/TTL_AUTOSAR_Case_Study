from typing import Any, Dict, List

import streamlit as st

CONFIDENCE_STYLE = {
    "high": {"emoji": "🟢", "label": "High confidence"},
    "medium": {"emoji": "🟡", "label": "Medium confidence"},
    "low": {"emoji": "🔴", "label": "Low confidence"},
}

SEVERITY_STYLE = {
    "error": {"emoji": "🔴", "label": "Error"},
    "warning": {"emoji": "🟠", "label": "Warning"},
    "info": {"emoji": "🔵", "label": "Info"},
}


def confidence_badge(confidence: str, grounded: bool) -> str:
    style = CONFIDENCE_STYLE.get(confidence, CONFIDENCE_STYLE["low"])
    if not grounded:
        return "⚪ Not grounded - insufficient evidence in document"
    return f"{style['emoji']} {style['label']}"


def render_citations(citations: List[Dict[str, Any]], key_prefix: str = "") -> None:
    """Render a list of citations as an expander with page/section/snippet/score."""
    if not citations:
        st.caption("No supporting sections were retrieved.")
        return
    with st.expander(f"📎 View {len(citations)} citation(s)"):
        for i, c in enumerate(citations, start=1):
            page = c.get("page", "?")
            section = c.get("section", "")
            score = c.get("score")
            score_text = f" · relevance {score:.2f}" if isinstance(score, (int, float)) else ""
            st.markdown(f"**{i}. Page {page}** · *{section}*{score_text}")
            snippet = c.get("snippet")
            if snippet:
                st.caption(snippet)
            if i < len(citations):
                st.divider()


def render_chat_turn(question: str, result: Dict[str, Any]) -> None:
    """Render one Q&A turn: question, answer, confidence badge, citations."""
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        st.write(result["answer"])
        st.caption(confidence_badge(result.get("confidence", "low"), result.get("grounded", False)))
        render_citations(result.get("citations", []))


def entity_type_icon(entity_type: str) -> str:
    return {
        "component": "🧩",
        "port": "🔌",
        "runnable": "⏱️",
        "issue": "⚠️",
        "dependency": "🔗",
        "reference": "📄",
        "revision": "🕓",
    }.get(entity_type, "•")


def render_entity_table(entities: List[Dict[str, Any]]) -> None:
    """Render entities as a flat table, expanding the attributes dict into columns."""
    if not entities:
        st.info("No entities of this type were found in the document.")
        return
    rows = []
    for e in entities:
        row = {"Name": e["name"], "Page": e.get("page"), "Section": e.get("section")}
        row.update(e.get("attributes", {}))
        rows.append(row)
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_consistency_findings(findings: List[Dict[str, Any]]) -> None:
    if not findings:
        st.success("No findings - the document passed all automated consistency checks.")
        return
    for f in findings:
        style = SEVERITY_STYLE.get(f["severity"], SEVERITY_STYLE["info"])
        st.markdown(f"{style['emoji']} **[{f['check']}]** {f['message']}")


def document_picker(documents: List[Dict[str, Any]], label: str, key: str, allow_empty: bool = True):
    """A selectbox mapping 'filename (doc_id)' -> doc_id. Returns None if no selection."""
    if not documents:
        st.info("No documents uploaded yet. Upload one from the Chat & Upload tab first.")
        return None
    options = {f"{d['filename']}  ·  {d['doc_id']}": d["doc_id"] for d in documents}
    labels = list(options.keys())
    if allow_empty:
        labels = ["-- select a document --"] + labels
    choice = st.selectbox(label, labels, key=key)
    if choice in (None, "-- select a document --"):
        return None
    return options[choice]


def status_pill(ok: bool, ok_text: str, bad_text: str) -> None:
    if ok:
        st.success(f"✅ {ok_text}")
    else:
        st.warning(f"⚠️ {bad_text}")
