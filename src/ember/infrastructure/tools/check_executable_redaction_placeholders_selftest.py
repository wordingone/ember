#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU-only regressions for executable redaction-placeholder detection."""

from __future__ import annotations

import tempfile
from pathlib import Path

from check_executable_redaction_placeholders import scan_python_file


def _scan(source: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "candidate.py"
        path.write_text(source, encoding="utf-8", newline="\n")
        return scan_python_file(path, display_path="candidate.py")


def test_rejects_redacted_percent_format_operand() -> None:
    findings = _scan('value = "write %<local-path>" % "artifact.txt"\n')
    assert len(findings) == 1
    assert "candidate.py:1" in findings[0]
    assert "%<local-path>" in findings[0]


def test_accepts_inert_archival_text_and_valid_percent_format() -> None:
    findings = _scan(
        'incident = "the old source contained %<local-path>"\n'
        'value = "write %s" % "artifact.txt"\n'
    )
    assert findings == []


def test_rejects_redacted_format_string_method_operand() -> None:
    findings = _scan('value = "write {<local-path>}".format("artifact.txt")\n')
    assert len(findings) == 1
    assert "{<local-path>}" in findings[0]


if __name__ == "__main__":
    tests = (
        test_rejects_redacted_percent_format_operand,
        test_accepts_inert_archival_text_and_valid_percent_format,
        test_rejects_redacted_format_string_method_operand,
    )
    for test in tests:
        test()
    print(f"check_executable_redaction_placeholders_selftest: PASS ({len(tests)}/{len(tests)})")
