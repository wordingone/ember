# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The secrets/variables listing records an UNSUPPORTED non-reading on HTTP 403."""
from __future__ import annotations

import unittest
from typing import Any

from src.ember.governance.scripts.github import snapshot


class _FakeGh(snapshot.Gh):
    def __init__(self, answers: dict[str, Any]) -> None:
        super().__init__(["gh"], "owner/repo")
        self.answers = answers

    def _run(self, args: list[str], *, allow_missing: bool = False) -> Any:
        answer = self.answers[args[-1]]
        if isinstance(answer, tuple):
            returncode, stderr = answer
            if not allow_missing:
                raise snapshot.SnapshotError(stderr)
            return {"unavailable": True, "returncode": returncode, "stderr": stderr}
        return answer


FORBIDDEN = (1, "gh: Resource not accessible by integration (HTTP 403)")


class NamesOrUnsupportedTest(unittest.TestCase):
    def test_readable_listing_returns_sorted_names(self) -> None:
        gh = _FakeGh(
            {"repos/owner/repo/actions/secrets": {"secrets": [{"name": "B"}, {"name": "A"}]}}
        )
        self.assertEqual(gh.names_or_unsupported("actions/secrets", "secrets"), ["A", "B"])

    def test_http_403_is_unsupported_not_zero(self) -> None:
        gh = _FakeGh({"repos/owner/repo/actions/secrets": FORBIDDEN})
        value = gh.names_or_unsupported("actions/secrets", "secrets")
        self.assertIsInstance(value, dict)
        self.assertEqual(value["status"], "UNSUPPORTED")
        self.assertIn("HTTP 403", value["reason"])
        self.assertNotEqual(value, [])

    def test_other_failure_still_raises(self) -> None:
        gh = _FakeGh(
            {"repos/owner/repo/actions/secrets": (1, "gh: Not Found (HTTP 404)")}
        )
        with self.assertRaises(snapshot.SnapshotError):
            gh.names_or_unsupported("actions/secrets", "secrets")

    def test_rate_limit_403_still_raises(self) -> None:
        gh = _FakeGh(
            {
                "repos/owner/repo/actions/secrets": (
                    1,
                    "gh: API rate limit exceeded for installation (HTTP 403)",
                )
            }
        )
        with self.assertRaises(snapshot.SnapshotError):
            gh.names_or_unsupported("actions/secrets", "secrets")

    def test_missing_envelope_raises(self) -> None:
        gh = _FakeGh({"repos/owner/repo/actions/secrets": {"total_count": 0}})
        with self.assertRaises(snapshot.SnapshotError):
            gh.names_or_unsupported("actions/secrets", "secrets")


if __name__ == "__main__":
    unittest.main()
