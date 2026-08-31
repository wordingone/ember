# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_inference_training_translation.py"
HEADER = (
    "| ID | Inference technique | Inference benefit | Training analog | "
    "Field maturity | Ember status | Candidate experiment |"
)
REQUIRED_TECHNIQUES = (
    "post-training quantization",
    "speculative decoding",
    "frozen low-bit residency",
    "mixture-of-experts partial activation",
    "kv-cache reduction",
    "pruning",
    "serving distillation",
    "ternary inference",
)


def _valid_table() -> str:
    techniques = list(REQUIRED_TECHNIQUES) + [
        "low-rank adaptation",
        "low-rank gradient projection",
        "activation checkpointing",
        "optimizer-state quantization",
        "sequence parallelism",
        "flash attention",
        "state-space recurrence",
        "adaptive computation",
    ]
    rows = [
        f"| T{index:02d} | {technique} | Benefit {index} | Analog {index} | "
        f"ESTABLISHED [S{index:02d}] | GAP | Experiment {index} |"
        for index, technique in enumerate(techniques, start=1)
    ]
    sources = [
        f"- [S{index:02d}] https://arxiv.org/abs/{2000 + index:04d}.00001"
        for index in range(1, len(techniques) + 1)
    ]
    return (
        "# Inference-to-training translation\n\n"
        f"{HEADER}\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n## Sources\n\n"
        + "\n".join(sources)
        + "\n"
    )


def _write_fixture(root: Path, table: str | None = None) -> None:
    (root / "docs" / "design").mkdir(parents=True)
    (root / "docs" / "design" / "inference-to-training-translation-v1.md").write_text(
        table or _valid_table(), encoding="utf-8"
    )
    link = "docs/domains/governance/design/inference-to-training-translation-v1.md"
    (root / "docs" / "design" / "sota-stack-floor-spec.md").write_text(link, encoding="utf-8")
    (root / "docs" / "design" / "sota-stack-floor.md").write_text(link, encoding="utf-8")
    (root / "docs" / "design" / "scale-architecture-frontier-20260703.md").write_text(
        f"## 6. Training translation\n\n{link}\n\nC-SCALE(ii)\n",
        encoding="utf-8",
    )


class TranslationCheckerTests(unittest.TestCase):
    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(CHECKER), "--root", str(root), "--json"],
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_valid_contract_passes_with_machine_readable_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            result = self._run(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["row_count"], 16)
            self.assertEqual(receipt["resolved_citation_count"], 16)

    def test_fewer_than_fifteen_rows_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines = _valid_table().splitlines()
            rows = [line for line in lines if line.startswith("| T")]
            table = "\n".join(line for line in lines if line not in rows[-2:]) + "\n"
            _write_fixture(root, table)
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("at least 15", result.stderr)

    def test_unresolved_field_maturity_citation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = _valid_table().replace("ESTABLISHED [S01]", "ESTABLISHED [S99]", 1)
            _write_fixture(root, table)
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("S99", result.stderr)

    def test_missing_integration_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            (root / "docs" / "design" / "sota-stack-floor.md").write_text(
                "# Missing canonical translation link\n", encoding="utf-8"
            )
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sota-stack-floor.md", result.stderr)

    def test_current_repository_satisfies_issue_55_contract(self) -> None:
        result = self._run(REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
