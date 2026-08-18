# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arxiv_fetch
import arxiv_paperlist_select as selector


CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(
    arxiv_id: str,
    *,
    license_url: str = CC0,
    categories: str = "cs.LG",
    created: str = "2025-01-02",
    title: str = "A benchmark for robust learning",
    abstract: str = "Evaluation and dataset methods.",
) -> str:
    return f"""<record>
  <header><identifier>oai:arXiv.org:{arxiv_id}</identifier><datestamp>{created}</datestamp></header>
  <metadata><arXiv xmlns="http://arxiv.org/OAI/arXiv/">
    <id>{arxiv_id}</id><created>{created}</created><title>{title}</title>
    <categories>{categories}</categories><license>{license_url}</license>
    <abstract>{abstract}</abstract>
  </arXiv></metadata>
</record>"""


def _page(records: list[str]) -> bytes:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<OAI-PMH xmlns=\"http://www.openarchives.org/OAI/2.0/\"><ListRecords>"
        + "".join(records)
        + "</ListRecords></OAI-PMH>"
    ).encode()


def _write_spec(root: Path, **overrides: object) -> tuple[Path, str]:
    exclusion = root / "prior-list.txt"
    exclusion.write_text("2501.00005\n", encoding="utf-8")
    spec: dict[str, object] = {
        "schema": "ember-arxiv-paperlist-selection-v1",
        "as_of": "2026-08-18T00:00:00Z",
        "license_url": CC0,
        "categories": ["cs.AI", "cs.LG"],
        "category_mode": "any",
        "date_range": {"from": "2024-01-01", "through": "2026-12-31"},
        "text_filter": {"pattern": "benchmark|dataset", "mode": "search", "case_sensitive": False},
        "exclusions": [{"path": str(exclusion), "sha256": _sha256(exclusion.read_bytes())}],
        "selection_label": "fixture-ml-ai-cc0",
    }
    spec.update(overrides)
    path = root / "selection-spec.json"
    raw = (json.dumps(spec, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return path, _sha256(raw)


class ArxivPaperlistSelectTests(unittest.TestCase):
    def test_selects_closed_predicate_and_composes_with_fetch_list_reader(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_page([
                _record("2501.00001", categories="cs.LG stat.ML"),
                _record("2501.00002", categories="cs.DS"),
                _record("2501.00003", created="2023-12-31"),
                _record("2501.00004", title="Unrelated paper", abstract="No thematic token."),
                _record("2501.00005", categories="cs.AI"),
            ]))
            spec, spec_sha = _write_spec(root)
            output = root / "out"

            manifest = selector.produce_selection(
                pages_dir=pages,
                spec_path=spec,
                spec_sha256=spec_sha,
                output_dir=output,
            )

            paper_list = output / "paper-list.txt"
            self.assertEqual(arxiv_fetch.read_paper_list(paper_list), ["2501.00001"])
            self.assertEqual(manifest["counts"]["parsed"], 5)
            self.assertEqual(manifest["counts"]["accepted"], 1)
            self.assertEqual(sum(manifest["counts"]["rejected_by_reason"].values()), 4)
            self.assertEqual(manifest["selection"]["text_filter"], {
                "case_sensitive": False,
                "mode": "search",
                "pattern": "benchmark|dataset",
            })
            self.assertEqual(manifest["outputs"]["paper_list_sha256"], _sha256(paper_list.read_bytes()))
            self.assertEqual(selector.verify_selection(output), manifest)

    def test_exact_license_url_variant_is_rejected_and_counted_separately(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_page([
                _record("2501.00001"),
                _record("2501.00002", license_url=CC0.rstrip("/")),
            ]))
            spec, spec_sha = _write_spec(root, exclusions=[])
            manifest = selector.produce_selection(
                pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=root / "out"
            )
            self.assertEqual(manifest["counts"]["accepted"], 1)
            self.assertEqual(manifest["counts"]["rejected_by_reason"]["license_url_variant"], 1)

    def test_rejected_reason_accounting_is_exhaustive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_page([
                _record("2501.00001"),
                _record("2501.00002", license_url="http://arxiv.org/licenses/nonexclusive-distrib/1.0/"),
                _record("2501.00003", categories="math.LO"),
                _record("2501.00004", created="2020-01-01"),
                _record("2501.00005"),
            ]))
            spec, spec_sha = _write_spec(root)
            manifest = selector.produce_selection(
                pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=root / "out"
            )
            counts = manifest["counts"]
            self.assertEqual(counts["accepted"] + sum(counts["rejected_by_reason"].values()), counts["parsed"])
            self.assertEqual(set(counts["rejected_by_reason"]), {
                "category_mismatch", "date_outside_range", "excluded_by_bound_list", "license_mismatch"
            })

    def test_refuses_unknown_spec_key_versioned_id_and_duplicate_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_page([_record("2501.00001")]))
            spec, spec_sha = _write_spec(root, unexpected=True)
            with self.assertRaisesRegex(selector.SelectionRefusal, "spec schema is not closed"):
                selector.produce_selection(pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=root / "unknown")

            spec, spec_sha = _write_spec(root, exclusions=[])
            (pages / "000000.xml").write_bytes(_page([_record("2501.00001v2")]))
            with self.assertRaisesRegex(selector.SelectionRefusal, "version suffix"):
                selector.produce_selection(pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=root / "version")

            (pages / "000000.xml").write_bytes(_page([_record("2501.00001"), _record("2501.00001")]))
            with self.assertRaisesRegex(selector.SelectionRefusal, "duplicate arXiv id"):
                selector.produce_selection(pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=root / "duplicate")

    def test_refuses_output_overwrite_and_drift_on_verify(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_page([_record("2501.00001")]))
            spec, spec_sha = _write_spec(root, exclusions=[])
            output = root / "out"
            selector.produce_selection(pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=output)
            with self.assertRaisesRegex(selector.SelectionRefusal, "output already exists"):
                selector.produce_selection(pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=output)
            (output / "paper-list.txt").write_text("2501.99999\n", encoding="utf-8")
            with self.assertRaisesRegex(selector.SelectionRefusal, "paper list changed"):
                selector.verify_selection(output)

    def test_refuses_spec_drift_and_empty_selection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_page([_record("2501.00001", categories="math.LO")]))
            spec, spec_sha = _write_spec(root, exclusions=[])
            with self.assertRaisesRegex(selector.SelectionRefusal, "produced no paper IDs"):
                selector.produce_selection(
                    pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=root / "empty"
                )
            spec.write_bytes(spec.read_bytes() + b" ")
            with self.assertRaisesRegex(selector.SelectionRefusal, "spec bytes do not match"):
                selector.produce_selection(
                    pages_dir=pages, spec_path=spec, spec_sha256=spec_sha, output_dir=root / "drift"
                )


if __name__ == "__main__":
    unittest.main()
