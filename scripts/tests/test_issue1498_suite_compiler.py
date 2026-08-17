#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

# The ci-nightly scripts/tests environment intentionally omits NumPy. Preserve
# the real suite-compiler coverage where it is installed without aborting
# collection of every other scripts test.
pytest.importorskip(
    "numpy", reason="suite compiler requires optional NumPy", exc_type=ImportError
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from r1_cheap_probe_suite import (  # noqa: E402
    SELECTION_DOMAINS,
    SuiteRefusal,
    build_source_manifest,
    compile_r2_registry,
    load_source_manifest,
    publish_source_manifest,
)
from r2_cheap_probe_battery import (  # noqa: E402
    R2ProbeBatteryRefusal,
    _cli_load_registry,
    load_compiled_source_suite,
)


def test_selection_domains_match_the_approved_authority_bytes() -> None:
    assert SELECTION_DOMAINS == {
        "MMLU-Pro": "ember02-r1-r2-cheap-probe-v1\0MMLU-Pro\0",
        "ARC-Challenge": "ember02-r1-r2-cheap-probe-v1\0ARC-Challenge\0",
    }


def _raw(rows: list[dict]) -> bytes:
    return b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _effective(raw: bytes, excluded: set[int]) -> str:
    lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    retained = [line for index, line in enumerate(lines) if index not in excluded]
    return _sha(("\n".join(retained) + "\n").encode("utf-8"))


def _mmlu(index: int, *, choices: int = 10) -> dict:
    letters = "ABCDEFGHIJ"
    return {
        "question_id": 1000 + index,
        "question": f"mmlu question {index}",
        "options": [f"option {letter}" for letter in letters[:choices]],
        "answer": letters[index % choices],
        "answer_index": index % choices,
        "cot_content": "",
        "category": "fixture",
        "src": "fixture",
    }


def _arc(index: int) -> dict:
    letters = list("ABCD")
    return {
        "id": f"arc-{index}",
        "question": f"arc question {index}",
        "choices": {"text": [f"choice {letter}" for letter in letters], "label": letters},
        "answerKey": letters[index % 4],
    }


def _exclusions(*, mmlu_index: int) -> bytes:
    return _raw([{
        "schema": "a1-freeze-exclusion-amendment/v1",
        "exclusions": {"items": [{
            "dataset": "MMLU-Pro",
            "dataset_line": mmlu_index,
            "native_id": {"question_id": 1000 + mmlu_index},
        }]},
        "post_exclusion_suite_b": {"contaminated_items_remaining": 0},
    }])


def test_selection_is_closed_deterministic_and_exclusion_bound(tmp_path: Path) -> None:
    mmlu_raw = _raw([*[_mmlu(i) for i in range(39)], _mmlu(39, choices=9)])
    arc_raw = _raw([_arc(i) for i in range(36)])
    exclusion_raw = _exclusions(mmlu_index=3)
    manifest = build_source_manifest(
        mmlu_raw=mmlu_raw,
        arc_raw=arc_raw,
        exclusion_raw=exclusion_raw,
        expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
        expected_effective_sha256s={
            "MMLU-Pro": _effective(mmlu_raw, {3}),
            "ARC-Challenge": _effective(arc_raw, set()),
        },
        expected_exclusion_sha256=_sha(exclusion_raw),
    )

    assert [row["dataset"] for row in manifest["tasks"]].count("MMLU-Pro") == 32
    assert [row["dataset"] for row in manifest["tasks"]].count("ARC-Challenge") == 32
    assert manifest["probes"] == [
        {
            "probe_id": "mmlu-pro-10choice",
            "dataset": "MMLU-Pro",
            "metric_type": "proportion",
            "judge": "exact_choice_label_v1",
            "cardinality": 10,
            "chance_rate": 0.1,
            "n_items": 32,
        },
        {
            "probe_id": "arc-challenge-4choice",
            "dataset": "ARC-Challenge",
            "metric_type": "proportion",
            "judge": "exact_choice_label_v1",
            "cardinality": 4,
            "chance_rate": 0.25,
            "n_items": 32,
        },
    ]
    assert all(len(row["choices"]) == (10 if row["dataset"] == "MMLU-Pro" else 4) for row in manifest["tasks"])
    assert "mmlu-pro:1003" not in {row["row_id"] for row in manifest["tasks"]}
    assert manifest == build_source_manifest(
        mmlu_raw=mmlu_raw,
        arc_raw=arc_raw,
        exclusion_raw=exclusion_raw,
        expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
        expected_effective_sha256s={
            "MMLU-Pro": _effective(mmlu_raw, {3}),
            "ARC-Challenge": _effective(arc_raw, set()),
        },
        expected_exclusion_sha256=_sha(exclusion_raw),
    )

    canonical = ROOT / "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json"
    loaded = load_source_manifest(canonical, _sha(canonical.read_bytes()))
    assert len(loaded["tasks"]) == 64


def test_source_and_exclusion_tamper_refuse() -> None:
    mmlu_raw = _raw([_mmlu(i) for i in range(33)])
    arc_raw = _raw([_arc(i) for i in range(33)])
    exclusion_raw = _exclusions(mmlu_index=0)
    with pytest.raises(SuiteRefusal, match="SOURCE_SHA_MISMATCH"):
        build_source_manifest(
            mmlu_raw=mmlu_raw + b" ",
            arc_raw=arc_raw,
            exclusion_raw=exclusion_raw,
            expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
            expected_effective_sha256s={
                "MMLU-Pro": _effective(mmlu_raw, {0}),
                "ARC-Challenge": _effective(arc_raw, set()),
            },
            expected_exclusion_sha256=_sha(exclusion_raw),
        )

    wrong_identity = json.loads(exclusion_raw)
    wrong_identity["exclusions"]["items"][0]["native_id"] = {"question_id": 999999}
    wrong_identity_raw = _raw([wrong_identity])
    with pytest.raises(SuiteRefusal, match="EXCLUSION_IDENTITY_MISMATCH"):
        build_source_manifest(
            mmlu_raw=mmlu_raw,
            arc_raw=arc_raw,
            exclusion_raw=wrong_identity_raw,
            expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
            expected_effective_sha256s={
                "MMLU-Pro": _effective(mmlu_raw, {0}),
                "ARC-Challenge": _effective(arc_raw, set()),
            },
            expected_exclusion_sha256=_sha(wrong_identity_raw),
        )
    with pytest.raises(SuiteRefusal, match="EXCLUSION_SHA_MISMATCH"):
        build_source_manifest(
            mmlu_raw=mmlu_raw,
            arc_raw=arc_raw,
            exclusion_raw=exclusion_raw + b" ",
            expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
            expected_effective_sha256s={
                "MMLU-Pro": _effective(mmlu_raw, {0}),
                "ARC-Challenge": _effective(arc_raw, set()),
            },
            expected_exclusion_sha256=_sha(exclusion_raw),
        )

    with pytest.raises(SuiteRefusal, match="EFFECTIVE_SHA_MISMATCH"):
        build_source_manifest(
            mmlu_raw=mmlu_raw,
            arc_raw=arc_raw,
            exclusion_raw=exclusion_raw,
            expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
            expected_effective_sha256s={"MMLU-Pro": "0" * 64, "ARC-Challenge": _effective(arc_raw, set())},
            expected_exclusion_sha256=_sha(exclusion_raw),
        )


def test_malformed_uniform_cardinality_row_refuses() -> None:
    rows = [_mmlu(i) for i in range(34)]
    rows[33].pop("question")
    mmlu_raw = _raw(rows)
    arc_raw = _raw([_arc(i) for i in range(33)])
    exclusion_raw = _exclusions(mmlu_index=0)
    with pytest.raises(SuiteRefusal, match="SOURCE_SCHEMA_INVALID"):
        build_source_manifest(
            mmlu_raw=mmlu_raw,
            arc_raw=arc_raw,
            exclusion_raw=exclusion_raw,
            expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
            expected_effective_sha256s={
                "MMLU-Pro": _effective(mmlu_raw, {0}),
                "ARC-Challenge": _effective(arc_raw, set()),
            },
            expected_exclusion_sha256=_sha(exclusion_raw),
        )


def test_manifest_binds_effective_selection_exclusion_policy_and_t24() -> None:
    mmlu_raw = _raw([_mmlu(i) for i in range(33)])
    arc_raw = _raw([_arc(i) for i in range(33)])
    exclusion_raw = _exclusions(mmlu_index=0)
    manifest = build_source_manifest(
        mmlu_raw=mmlu_raw,
        arc_raw=arc_raw,
        exclusion_raw=exclusion_raw,
        expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
        expected_effective_sha256s={
            "MMLU-Pro": _effective(mmlu_raw, {0}),
            "ARC-Challenge": _effective(arc_raw, set()),
        },
        expected_exclusion_sha256=_sha(exclusion_raw),
    )

    assert manifest["selection"]["algorithm"] == "lowest-sha256(selection-domain||raw-row-bytes)/v1"
    assert set(manifest["selection"]["domains"]) == {"MMLU-Pro", "ARC-Challenge"}
    assert all("effective_rows_sha256" in manifest["sources"][name] for name in ("MMLU-Pro", "ARC-Challenge"))
    assert manifest["exclusions"]["receipt_sha256"] == _sha(exclusion_raw)
    assert len(manifest["exclusions"]["identity_rows_sha256"]) == 64
    assert len(manifest["policy_sha256"]) == 64
    assert manifest["thresholds"] == {
        "method": "one-sided-wilson-no-continuity-correction",
        "confidence_level": 0.95,
        "strictly_exceeds_chance": True,
        "minimum_correct": {"MMLU-Pro": 6, "ARC-Challenge": 13},
    }
    assert all(len(row["selection_sha256"]) == 64 for row in manifest["tasks"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["selection"]["domains"].update({"MMLU-Pro": "foreign"}),
        lambda value: value["sources"]["MMLU-Pro"].update(effective_rows_sha256="0" * 64),
        lambda value: value["exclusions"].update(identity_rows_sha256="0" * 64),
        lambda value: value.update(policy_sha256="0" * 64),
        lambda value: value["thresholds"]["minimum_correct"].update({"MMLU-Pro": 5}),
        lambda value: value["tasks"][0].update(selection_sha256="0" * 64),
    ],
)
def test_frozen_authority_refuses_every_bound_surface_tamper(tmp_path: Path, mutation) -> None:
    value = deepcopy(json.loads((ROOT / "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json").read_text()))
    mutation(value)
    path = tmp_path / "tampered.json"
    path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())
    with pytest.raises(SuiteRefusal, match="SUITE_SHA_MISMATCH"):
        load_source_manifest(path, _sha(path.read_bytes()))


class _Tokenizer:
    def encode(self, text: str):
        class Encoded:
            ids = list(text.encode("utf-8"))
        return Encoded()


def test_r2_compilation_is_tokenizer_and_compiler_bound() -> None:
    mmlu_raw = _raw([_mmlu(i) for i in range(33)])
    arc_raw = _raw([_arc(i) for i in range(33)])
    exclusion_raw = _exclusions(mmlu_index=0)
    manifest = build_source_manifest(
        mmlu_raw=mmlu_raw,
        arc_raw=arc_raw,
        exclusion_raw=exclusion_raw,
        expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
        expected_effective_sha256s={
            "MMLU-Pro": _effective(mmlu_raw, {0}),
            "ARC-Challenge": _effective(arc_raw, set()),
        },
        expected_exclusion_sha256=_sha(exclusion_raw),
    )
    compiled, binding = compile_r2_registry(
        manifest,
        source_manifest_sha256="a" * 64,
        tokenizer=_Tokenizer(),
        tokenizer_sha256="b" * 64,
        compiler_sha256="c" * 64,
    )
    assert [probe["probe_id"] for probe in compiled] == ["mmlu-pro-10choice", "arc-challenge-4choice"]
    assert [probe["chance_rate"] for probe in compiled] == [0.1, 0.25]
    assert binding == {
        "source_manifest_sha256": "a" * 64,
        "tokenizer_sha256": "b" * 64,
        "compiler_sha256": "c" * 64,
        "compiled_registry_sha256": binding["compiled_registry_sha256"],
    }
    changed, changed_binding = compile_r2_registry(
        manifest,
        source_manifest_sha256="a" * 64,
        tokenizer=_Tokenizer(),
        tokenizer_sha256="d" * 64,
        compiler_sha256="c" * 64,
    )
    assert changed == compiled
    assert changed_binding["compiled_registry_sha256"] != binding["compiled_registry_sha256"]


def test_real_r2_adapter_rederives_single_authority_and_refuses_hash_tamper() -> None:
    suite = ROOT / "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json"
    tokenizer = ROOT / "tokenizer/tokenizer.json"
    compiler = ROOT / "scripts/r1_cheap_probe_suite.py"
    suite_sha, tokenizer_sha, compiler_sha = (_sha(path.read_bytes()) for path in (suite, tokenizer, compiler))
    registry, meta = load_compiled_source_suite(
        suite, suite_sha, tokenizer, tokenizer_sha, compiler_sha
    )
    assert [probe.probe_id for probe in registry] == ["mmlu-pro-10choice", "arc-challenge-4choice"]
    assert [len(probe.items) for probe in registry] == [32, 32]
    assert meta["source_manifest_sha256"] == suite_sha
    assert meta["tokenizer_sha256"] == tokenizer_sha
    assert meta["compiler_sha256"] == compiler_sha
    assert len(meta["compiled_registry_sha256"]) == 64

    cli_registry, cli_meta = _cli_load_registry(SimpleNamespace(
        source_suite=str(suite),
        source_suite_sha256=suite_sha,
        tokenizer=str(tokenizer),
        tokenizer_sha256=tokenizer_sha,
        compiler_sha256=compiler_sha,
        probe_manifest=None,
        probe_manifest_sha256=None,
    ))
    assert cli_registry == registry
    assert cli_meta == meta

    for values, reason in (
        ((suite, "0" * 64, tokenizer, tokenizer_sha, compiler_sha), "SOURCE_SUITE_COMPILE_FAILED"),
        ((suite, suite_sha, tokenizer, "0" * 64, compiler_sha), "TOKENIZER_SHA_MISMATCH"),
        ((suite, suite_sha, tokenizer, tokenizer_sha, "0" * 64), "COMPILER_SHA_MISMATCH"),
    ):
        with pytest.raises(R2ProbeBatteryRefusal, match=reason):
            load_compiled_source_suite(*values)


def test_manifest_publish_is_atomic_and_check_mode_detects_drift(tmp_path: Path) -> None:
    mmlu_raw = _raw([_mmlu(i) for i in range(33)])
    arc_raw = _raw([_arc(i) for i in range(33)])
    exclusion_raw = _exclusions(mmlu_index=0)
    manifest = build_source_manifest(
        mmlu_raw=mmlu_raw,
        arc_raw=arc_raw,
        exclusion_raw=exclusion_raw,
        expected_source_sha256s={"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)},
        expected_effective_sha256s={
            "MMLU-Pro": _effective(mmlu_raw, {0}),
            "ARC-Challenge": _effective(arc_raw, set()),
        },
        expected_exclusion_sha256=_sha(exclusion_raw),
    )
    output = tmp_path / "suite.json"
    publish_source_manifest(manifest, output, check=False)
    publish_source_manifest(manifest, output, check=True)
    output.write_bytes(b"{}\n")
    with pytest.raises(SuiteRefusal, match="SUITE_OUTPUT_DRIFT"):
        publish_source_manifest(manifest, output, check=True)
    assert output.read_bytes() == b"{}\n"


def test_d04_superseding_amendment_binds_single_authority_and_consumers() -> None:
    amendment_path = ROOT / "docs/spec/ember02-r2-cheap-probe-amendment-v2.json"
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    suite_path = ROOT / amendment["decision"]["source_manifest"]["path"]
    implementations = amendment["decision"]["implementations"]

    assert amendment["issue"] == 1498
    assert amendment["supersedes"] == {
        "path": "docs/spec/ember02-r2-cheap-probe-amendment-v1.json",
        "sha256": _sha((ROOT / "docs/spec/ember02-r2-cheap-probe-amendment-v1.json").read_bytes()),
    }
    assert amendment["decision"]["id"] == "D-04"
    assert amendment["decision"]["registry_state"] == "HASH_PINNED_TEXT_AUTHORITY"
    assert amendment["decision"]["source_manifest"] == {
        "path": "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json",
        "sha256": _sha(suite_path.read_bytes()),
        "schema": "ember02-r1-r2-cheap-probe-suite/v1",
        "rows": 64,
    }
    assert implementations == {
        "compiler": {
            "path": "scripts/r1_cheap_probe_suite.py",
            "sha256": _sha((ROOT / "scripts/r1_cheap_probe_suite.py").read_bytes()),
        },
        "r1_runner": {
            "path": "scripts/r1_frozen_eval_runner.py",
            "sha256": _sha((ROOT / "scripts/r1_frozen_eval_runner.py").read_bytes()),
        },
        "r2_consumer": {
            "path": "scripts/r2_cheap_probe_battery.py",
            "sha256": _sha((ROOT / "scripts/r2_cheap_probe_battery.py").read_bytes()),
        },
        "owned_server": {
            "path": "tools/ember-restart-3b/serve_owned_openai.py",
            "sha256": _sha((ROOT / "tools/ember-restart-3b/serve_owned_openai.py").read_bytes()),
        },
    }
    assert amendment["decision"]["defined_probes"] == [
        {
            "id": "mmlu-pro-10choice",
            "items": 32,
            "cardinality": 10,
            "chance_rate": 0.1,
            "minimum_correct_at_t24": 6,
        },
        {
            "id": "arc-challenge-4choice",
            "items": 32,
            "cardinality": 4,
            "chance_rate": 0.25,
            "minimum_correct_at_t24": 13,
        },
    ]
    assert amendment["decision"]["advancement_credit"] is False
    assert amendment["decision"]["r3_funding_allowed"] is False
