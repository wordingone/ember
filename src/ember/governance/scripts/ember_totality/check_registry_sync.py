#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Registry sync selftest — verify ORDER == conditions-v1.md registry.

This is a self-enforcing test that catches the #293 defect class
(C-INV added to registry but not to ORDER) before the board runs.

Returns: GREEN if ORDER ids == registry ids, RED otherwise.
Always exits 0 for aggregation.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
CONDITIONS_SPEC_PATH = os.path.join(REPO_ROOT, "docs", "spec", "conditions-v1.md")
SPEC_PY_PATH = os.path.join(HERE, "ember_totality_spec.py")

# Registry-doc bullet matcher: "- **C-EFF — ..." / "- **C(−1) — ..." /
# "- **C-MANIFEST.** ..." (rollups use "." not an em-dash after the id).
REGISTRY_BULLET_RE = re.compile(
    r"^- \*\*(C\([−-]?1\)|C-[A-Z0-9]+|C[0-9]+)(?=[ .])", re.MULTILINE
)

ORDER_RE = re.compile(
    r'ORDER = \[\s*(.*?)\s*\]',
    re.DOTALL
)

FILENAME_ID_RE = re.compile(
    r'FILENAME_ID = \{\s*(.*?)\s*\}',
    re.DOTALL
)

NON_PROBE_TEST_FILES_RE = re.compile(
    r'NON_PROBE_TEST_FILES = \{\s*(.*?)\s*\}',
    re.DOTALL,
)

def _normalize_id(cid):
    """Canonicalize the C(-1) unicode-minus vs ascii-hyphen spelling."""
    return cid.replace("−", "-")

def parse_registry_ids(spec_path):
    """Return the ordered list of condition ids declared by conditions-v1.md."""
    try:
        with open(spec_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        raise RuntimeError(f"Cannot read registry: {exc}")
    ids = [_normalize_id(m.group(1)) for m in REGISTRY_BULLET_RE.finditer(text)]
    if not ids:
        raise RuntimeError("No condition ids found in registry")
    return ids

def parse_order_from_spec(spec_py_path):
    """Extract ORDER list from ember_totality_spec.py source."""
    try:
        with open(spec_py_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        raise RuntimeError(f"Cannot read spec: {exc}")

    m = ORDER_RE.search(text)
    if not m:
        raise RuntimeError("Cannot find ORDER = [...] in spec")

    order_text = m.group(1)
    # Extract quoted strings
    ids = re.findall(r'"([^"]+)"', order_text)
    return ids

def parse_filename_id_from_spec(spec_py_path):
    """Extract FILENAME_ID dict from ember_totality_spec.py source."""
    try:
        with open(spec_py_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        raise RuntimeError(f"Cannot read spec: {exc}")

    m = FILENAME_ID_RE.search(text)
    if not m:
        raise RuntimeError("Cannot find FILENAME_ID = {...} in spec")

    filename_id_text = m.group(1)
    # Extract mappings: "filename": "id",
    mappings = {}
    for match in re.finditer(r'"([^"]+)":\s*"([^"]+)"', filename_id_text):
        filename, cid = match.groups()
        mappings[filename] = cid
    return mappings


def parse_non_probe_tests_from_spec(spec_py_path):
    """Extract the exact closed non-probe test allowlist from the runner."""
    with open(spec_py_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    match = NON_PROBE_TEST_FILES_RE.search(text)
    if not match:
        raise RuntimeError("Cannot find NON_PROBE_TEST_FILES = {...} in spec")
    return set(re.findall(r'"([^"]+\.py)"', match.group(1)))

try:
    registry_ids = parse_registry_ids(CONDITIONS_SPEC_PATH)
    registry_set = set(registry_ids)

    order_ids = parse_order_from_spec(SPEC_PY_PATH)
    runner_set = set(order_ids)

    # Check 1: ORDER ids == registry ids
    if runner_set != registry_set:
        missing = sorted(registry_set - runner_set)
        extra = sorted(runner_set - registry_set)
        print(f"RED ORDER != registry ids: missing {missing}, extra {extra}")
        sys.exit(0)

    # Check 2: FILENAME_ID coverage (every probe file should have a mapping)
    all_test_files = {n for n in os.listdir(HERE)
                      if n.startswith("test_") and n.endswith(".py")}
    filename_id = parse_filename_id_from_spec(SPEC_PY_PATH)
    non_probe_tests = parse_non_probe_tests_from_spec(SPEC_PY_PATH)
    discovered = all_test_files - non_probe_tests

    unregistered = sorted(discovered - set(filename_id))
    missing_files = sorted(set(filename_id) - discovered)
    unmapped_ids = sorted(set(filename_id.values()) - runner_set)
    missing_non_probes = sorted(non_probe_tests - all_test_files)
    overlap = sorted(non_probe_tests & set(filename_id))

    if unregistered or missing_files or unmapped_ids or missing_non_probes or overlap:
        detail = []
        if unregistered:
            detail.append(f"unregistered_files={unregistered}")
        if missing_files:
            detail.append(f"missing_files={missing_files}")
        if unmapped_ids:
            detail.append(f"unmapped_ids={unmapped_ids}")
        if missing_non_probes:
            detail.append(f"missing_non_probes={missing_non_probes}")
        if overlap:
            detail.append(f"probe_non_probe_overlap={overlap}")
        print(f"RED FILENAME_ID drift: {', '.join(detail)}")
        sys.exit(0)

    print(f"GREEN Registry sync OK: {len(order_ids)} conditions, all mapped")
    sys.exit(0)

except Exception as exc:
    print(f"RED Registry sync check failed: {type(exc).__name__}: {exc}")
    sys.exit(0)
