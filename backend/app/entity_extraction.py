import csv
import io
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

# (entity_type, required header slugs, header slug that holds the entity name)
TABLE_SIGNATURES: List[Tuple[str, set, str]] = [
    ("component", {"component_name", "component_id"}, "component_name"),
    ("port", {"port_name", "direction"}, "port_name"),
    ("runnable", {"runnable_name", "owning_swc"}, "runnable_name"),
    ("issue", {"id", "description", "status"}, "id"),
    ("reference", {"doc_id", "title", "version"}, "doc_id"),
    ("revision", {"version", "date", "author"}, "version"),
]

# "3.1 CentralLockingMgr Ports" -> CentralLockingMgr
PORT_SECTION_PATTERN = re.compile(r"^\d+(?:\.\d+)*\.?\s+([A-Za-z0-9_]+)\s+Ports?\b", re.IGNORECASE)


def _slug(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")


def _classify(header_slugs: List[str]):
    slugs = set(header_slugs)
    for entity_type, required, name_col in TABLE_SIGNATURES:
        if required.issubset(slugs):
            return entity_type, name_col
    return None, None

# Table -> entities
def extract_entities(structured_tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    for table in structured_tables:
        rows = table["rows"]
        if len(rows) < 2:
            continue
        header_slugs = [_slug(h) for h in rows[0]]
        entity_type, name_col = _classify(header_slugs)
        if not entity_type:
            continue

        owner = None
        if entity_type == "port":
            match = PORT_SECTION_PATTERN.match(table["section"] or "")
            owner = match.group(1) if match else None

        for row in rows[1:]:
            record = {
                header_slugs[i]: row[i] for i in range(min(len(header_slugs), len(row)))
            }
            name = (record.get(name_col) or "").strip()
            if not name:
                continue
            attributes = {k: v for k, v in record.items() if k != name_col and v != ""}
            if entity_type == "port":
                attributes["owner_component"] = owner
            entities.append(
                {
                    "entity_type": entity_type,
                    "name": name,
                    "attributes": attributes,
                    "page": table["page"],
                    "section": table["section"],
                }
            )
    return entities

# Prose -> dependencie
def extract_dependencies(
    chunks: List[Dict[str, Any]], component_names: List[str]
) -> List[Dict[str, Any]]:
    """
    Finds sentences such as "X depends on Y for ..." where X and Y are known
    component names. For each "depends on" the subject is the closest component
    named before it and the targets are the components named after it.
    """
    if not component_names:
        return []
    ordered = sorted(set(component_names), key=len, reverse=True)
    name_regex = re.compile(r"\b(" + "|".join(re.escape(n) for n in ordered) + r")\b")
    found: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for chunk in chunks:
        if chunk.get("chunk_type") != "text":
            continue
        text = re.sub(r"\[Section:[^\]]*\]", " ", chunk["text"])
        text = re.sub(r"\s+", " ", text)
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            markers = [m.start() for m in re.finditer(r"\bdepends?\s+on\b", sentence)]
            if not markers:
                continue
            names = [(m.start(), m.group(1)) for m in name_regex.finditer(sentence)]
            for i, marker in enumerate(markers):
                end = markers[i + 1] if i + 1 < len(markers) else len(sentence)
                subjects = [n for pos, n in names if pos < marker]
                targets = [n for pos, n in names if marker < pos < end]
                if not subjects:
                    continue
                source = subjects[-1]
                for target in targets:
                    if target == source or (source, target) in found:
                        continue
                    found[(source, target)] = {
                        "entity_type": "dependency",
                        "name": f"{source} -> {target}",
                        "attributes": {
                            "source": source,
                            "target": target,
                            "relation": "depends_on",
                            "evidence": sentence[:300],
                        },
                        "page": chunk["page"],
                        "section": chunk["section"],
                    }
    return list(found.values())

# Consistency / completeness check
def run_consistency_checks(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic checks that surface potential mismatches for engineer review."""
    findings: List[Dict[str, Any]] = []

    def add(severity, check, message, entity=None):
        findings.append(
            {"severity": severity, "check": check, "message": message, "entity": entity}
        )

    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in entities:
        by_type[e["entity_type"]].append(e)

    components = by_type["component"]
    component_names = {c["name"] for c in components}

    # Duplicate component names / IDs
    for label, values in (
        ("name", [c["name"] for c in components]),
        ("component_id", [c["attributes"].get("component_id") for c in components]),
    ):
        for value, count in Counter(v for v in values if v).items():
            if count > 1:
                add("error", "duplicate_component", f"Duplicate component {label} '{value}' appears {count} times.", value)

    ports_by_owner = defaultdict(list)
    for p in by_type["port"]:
        owner = p["attributes"].get("owner_component")
        if not owner:
            add("warning", "port_without_owner", f"Port '{p['name']}' (page {p['page']}) could not be linked to a component from its section heading.", p["name"])
        elif owner not in component_names:
            add("error", "port_unknown_owner", f"Port '{p['name']}' belongs to '{owner}', which is not in the component inventory.", p["name"])
        else:
            ports_by_owner[owner].append(p)

    runnable_owners = set()
    for r in by_type["runnable"]:
        owner = r["attributes"].get("owning_swc")
        runnable_owners.add(owner)
        if owner and owner not in component_names:
            add("error", "runnable_unknown_swc", f"Runnable '{r['name']}' is owned by '{owner}', which is not in the component inventory.", r["name"])

    for c in components:
        if not ports_by_owner.get(c["name"]):
            add("warning", "component_without_ports", f"Component '{c['name']}' has no ports defined in the document.", c["name"])
        if c["name"] not in runnable_owners:
            add("warning", "component_without_runnables", f"Component '{c['name']}' has no runnable entities defined.", c["name"])

    for d in by_type["dependency"]:
        for role in ("source", "target"):
            comp = d["attributes"].get(role)
            if comp and comp not in component_names:
                add("error", "dependency_unknown_component", f"Dependency '{d['name']}' references unknown component '{comp}'.", d["name"])

    for issue in by_type["issue"]:
        status = (issue["attributes"].get("status") or "").lower()
        if status in {"open", "in progress", "pending", ""}:
            add("info", "open_issue", f"{issue['name']} ({issue['attributes'].get('status', 'unknown')}): {issue['attributes'].get('description', '')}", issue["name"])

    if not components:
        add("warning", "no_components_found", "No component inventory table was recognised. Check that the document has a table with 'Component Name' and 'Component ID' columns.")

    return findings

# Revision compariso
def compare_entity_sets(
    entities_a: List[Dict[str, Any]], entities_b: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Compare two documents' entities. Key = (entity_type, name); page/section are ignored."""
    def index(entities):
        return {(e["entity_type"], e["name"]): e for e in entities}

    a, b = index(entities_a), index(entities_b)
    added = [b[k] for k in b if k not in a]
    removed = [a[k] for k in a if k not in b]
    changed, unchanged = [], 0
    for key in a.keys() & b.keys():
        attrs_a, attrs_b = a[key]["attributes"], b[key]["attributes"]
        diffs = {
            attr: {"a": attrs_a.get(attr), "b": attrs_b.get(attr)}
            for attr in set(attrs_a) | set(attrs_b)
            if attrs_a.get(attr) != attrs_b.get(attr)
        }
        if diffs:
            changed.append({"entity_type": key[0], "name": key[1], "differences": diffs})
        else:
            unchanged += 1
    return {"added": added, "removed": removed, "changed": changed, "unchanged_count": unchanged}

# Expor
def entities_to_csv(entities: List[Dict[str, Any]]) -> str:
    import json

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["entity_type", "name", "page", "section", "attributes_json"])
    for e in entities:
        writer.writerow(
            [e["entity_type"], e["name"], e.get("page"), e.get("section"),
             json.dumps(e["attributes"], ensure_ascii=False)]
        )
    return buffer.getvalue()


def count_by_type(entities: List[Dict[str, Any]]) -> Dict[str, int]:
    return dict(Counter(e["entity_type"] for e in entities))
