from app import entity_extraction as ee


def test_extract_entities_from_component_and_port_tables():
    tables = [
        {"page": 1, "section": "2.1 Component Overview", "rows": [
            ["Component Name", "Component ID", "Type"],
            ["Alpha", "SWC-1", "Application SWC"]]},
        {"page": 2, "section": "3.1 Alpha Ports", "rows": [
            ["Port Name", "Direction", "Interface Type"],
            ["PPort_X", "Provided", "Sender-Receiver"]]},
    ]
    entities = ee.extract_entities(tables)
    assert [e["entity_type"] for e in entities] == ["component", "port"]
    assert entities[1]["attributes"]["owner_component"] == "Alpha"


def test_dependency_extraction_uses_closest_subject():
    chunks = [{"chunk_type": "text", "page": 2, "section": "2.2",
               "text": "[Section: 2.2]\nAlpha depends on Beta for speed. Gamma depends on Beta for state."}]
    deps = ee.extract_dependencies(chunks, ["Alpha", "Beta", "Gamma"])
    assert {d["name"] for d in deps} == {"Alpha -> Beta", "Gamma -> Beta"}


def test_consistency_flags_unknown_owner_and_missing_ports():
    entities = [
        {"entity_type": "component", "name": "Alpha", "attributes": {"component_id": "1"}, "page": 1, "section": ""},
        {"entity_type": "port", "name": "P", "attributes": {"owner_component": "Ghost"}, "page": 2, "section": ""},
    ]
    checks = {f["check"] for f in ee.run_consistency_checks(entities)}
    assert {"port_unknown_owner", "component_without_ports", "component_without_runnables"} <= checks


def test_compare_detects_added_removed_changed():
    a = [{"entity_type": "component", "name": "Alpha", "attributes": {"type": "old"}},
         {"entity_type": "component", "name": "Gone", "attributes": {}}]
    b = [{"entity_type": "component", "name": "Alpha", "attributes": {"type": "new"}},
         {"entity_type": "component", "name": "Fresh", "attributes": {}}]
    diff = ee.compare_entity_sets(a, b)
    assert [e["name"] for e in diff["added"]] == ["Fresh"]
    assert [e["name"] for e in diff["removed"]] == ["Gone"]
    assert diff["changed"][0]["differences"]["type"] == {"a": "old", "b": "new"}
