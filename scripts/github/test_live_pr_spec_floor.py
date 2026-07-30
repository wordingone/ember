# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Trusted live-PR integration tests for the ember-cli spec floor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.github.live_pr_policy import validate_live_pull_request
from scripts.github.test_live_pr_policy import human_pr


def _roots(parent: Path) -> tuple[Path, Path]:
    base = parent / "base"
    subject = parent / "subject"
    for root in (base, subject):
        (root / "tools" / "ember-cli" / "specs").mkdir(parents=True)
        (root / "tools" / "ember-cli" / "src" / "services").mkdir(parents=True)
        (root / "tools" / "ember-cli" / "specs" / "open.md").write_text(
            "# Open spec\n\nStatus: OPEN\n",
            encoding="utf-8",
        )
    return base, subject


class LivePullRequestSpecFloorTests(unittest.TestCase):
    def test_added_component_without_changed_bound_spec_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base, subject = _roots(Path(tmp))
            component = "tools/ember-cli/src/services/new-service.ts"
            (subject / component).write_text("export {};\n", encoding="utf-8")
            snapshot = human_pr()
            snapshot["changed_files"] = [component]

            self.assertEqual(
                [f"spec-floor:added-component-unbound:{component}"],
                validate_live_pull_request(
                    snapshot,
                    base_root=base,
                    subject_root=subject,
                ),
            )

    def test_added_component_with_exact_changed_consumer_spec_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base, subject = _roots(Path(tmp))
            component = "tools/ember-cli/src/services/new-service.ts"
            spec = "tools/ember-cli/specs/new-service.md"
            (subject / component).write_text("export {};\n", encoding="utf-8")
            (subject / spec).write_text(
                "# New service\n\n"
                "Status: SHIPPED\n"
                f"Consumer: `{component}`\n",
                encoding="utf-8",
            )
            snapshot = human_pr()
            snapshot["changed_files"] = [component, spec]

            self.assertEqual(
                [],
                validate_live_pull_request(
                    snapshot,
                    base_root=base,
                    subject_root=subject,
                ),
            )

    def test_missing_subject_root_fails_when_base_root_is_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base, _subject = _roots(Path(tmp))

            self.assertEqual(
                ["spec-floor:subject-root-required"],
                validate_live_pull_request(human_pr(), base_root=base),
            )


if __name__ == "__main__":
    unittest.main()
