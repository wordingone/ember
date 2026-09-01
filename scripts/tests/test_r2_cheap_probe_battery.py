# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for src/ember/governance/scripts/r2_cheap_probe_battery.py (issue #1435).

Production-shaped, small fixtures, NO GPU, NO training steps, and no real
3B checkpoint is ever loaded here -- checkpoint-binding integration tests
use `write_v3` (imported from tests/test_ember_restart_eval_checkpoint_
consumer_v3_contract.py, reused rather than reimplemented) to build a
structurally-valid but tiny v3 sparse-checkpoint fixture on disk.

Everything here proves the ADJUDICATION MACHINERY (F-03, R2-E4 chance
comparison, checkpoint binding, receipt shape, refusal discipline) is
correct. It does not and cannot prove anything about the actual R2 cheap
probes, because -- see r2_cheap_probe_battery.py's module docstring and
SPEC_DEFECTS -- the preregistration never defines any.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# The ci-nightly scripts/tests environment intentionally omits the heavyweight
# PyTorch dependency.  Preserve this module's real checkpoint-fixture coverage
# wherever PyTorch is installed, but do not let the optional dependency abort
# collection of every other scripts test.
pytest.importorskip("torch", reason="checkpoint fixture requires optional PyTorch")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "ember" / "governance" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import r2_cheap_probe_battery as battery  # noqa: E402
from test_ember_restart_eval_checkpoint_consumer_v3_contract import write_v3  # noqa: E402 -- reused, never reimplemented


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _item(item_id, index, correct_index=0, n_choices=3):
    return battery.ProbeItem(
        item_id=item_id,
        context_ids=(1, 2, index),
        choices=tuple((100 + c,) for c in range(n_choices)),
        correct_choice_index=correct_index,
    )


class _TableScorer:
    """Deterministic ProbeScorer over an explicit (context, choices) -> scores table."""

    def __init__(self, table):
        self._table = table

    def score_choices(self, context_ids, choice_id_lists):
        key = (tuple(context_ids), tuple(tuple(c) for c in choice_id_lists))
        return list(self._table[key])


def _always_correct_scorer(items):
    table = {}
    for item in items:
        row = [0.0] * len(item.choices)
        row[item.correct_choice_index] = 100.0
        table[(item.context_ids, item.choices)] = row
    return _TableScorer(table)


def _always_wrong_scorer(items):
    table = {}
    for item in items:
        row = [0.0] * len(item.choices)
        row[(item.correct_choice_index + 1) % len(item.choices)] = 100.0
        table[(item.context_ids, item.choices)] = row
    return _TableScorer(table)


def _probe(probe_id, n_items, *, metric_type="proportion", chance_rate=1.0 / 3.0, n_choices=3):
    items = tuple(_item(f"{probe_id}-{i}", i, correct_index=i % n_choices, n_choices=n_choices) for i in range(n_items))
    return battery.ProbeSpec(
        probe_id=probe_id, metric_id=f"{probe_id}.accuracy", metric_type=metric_type,
        chance_rate=chance_rate, source_note="test fixture", items=items,
    )


def _write_probe_manifest(tmp_path: Path, n_items: int = 4) -> tuple[Path, str]:
    doc = {
        "schema": battery.PROBE_MANIFEST_SCHEMA,
        "issue": "TEST-FIXTURE",
        "probes": [{
            "probe_id": "TEST_PROBE_1",
            "metric_id": "test_probe_1.accuracy",
            "metric_type": "proportion",
            "chance_rate": 0.5,
            "source_note": "test fixture",
            "items": [
                {
                    "item_id": f"TEST_PROBE_1-item-{i}",
                    "context_ids": [1, 2, i],
                    "choices": [[10], [11]],
                    "correct_choice_index": i % 2,
                }
                for i in range(n_items)
            ],
        }],
    }
    path = tmp_path / "probe-manifest.json"
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return path, battery._sha256_bytes(raw)


def _valid_checkpoint(tmp_path: Path, name: str) -> tuple[Path, Path]:
    root = tmp_path / name
    root.mkdir()
    manifest = write_v3(root)
    return manifest, root / "config.json"


# ---------------------------------------------------------------------------
# public contract
# ---------------------------------------------------------------------------

def test_public_contract():
    names = {
        "R2ProbeBatteryRefusal", "ProbeItem", "ProbeSpec", "ProbeScorer",
        "DEFAULT_PROBE_REGISTRY", "SPEC_DEFECTS", "load_probe_manifest",
        "verify_checkpoint", "score_probe", "one_sided_lower_wilson",
        "one_sided_lower_bootstrap", "adjudicate_r2e4_probe", "run_r2e4",
        "adjudicate_f03", "load_sigma_seed_receipt", "run_r2e3",
        "build_receipt", "write_receipt", "main",
        "R2_AUTHORITY_DOC", "R2_AUTHORITY_SCHEMA", "R2_AUTHORITY_DECISION_ID",
    }
    assert names.issubset(vars(battery))


def test_default_registry_requires_explicit_d04_bindings_and_old_defects_are_settled():
    assert battery.DEFAULT_PROBE_REGISTRY == ()
    assert battery.SPEC_DEFECTS == []
    assert {row["id"] for row in battery.HISTORICAL_SPEC_DEFECTS} == {
        "SPEC-DEFECT-1435-A", "SPEC-DEFECT-1435-B"
    }


def test_d04_authority_supersedes_d03_with_one_hash_pinned_text_manifest():
    authority_path = REPO_ROOT / battery.R2_AUTHORITY_DOC
    record = json.loads(authority_path.read_text(encoding="utf-8"))

    assert record["schema"] == battery.R2_AUTHORITY_SCHEMA
    assert record["issue"] == 1498
    assert record["supersedes"] == {
        "path": "docs/domains/governance/spec/ember02-r2-cheap-probe-amendment-v1.json",
        "sha256": "7e0e11b515987100ea9fc7bed9ad26094c2ea49dd27199cfdfc43ba21852ec9d",
    }

    decision = record["decision"]
    assert decision["id"] == battery.R2_AUTHORITY_DECISION_ID
    assert decision["registry_state"] == "HASH_PINNED_TEXT_AUTHORITY"
    assert decision["source_manifest"]["sha256"] == "b08073b505581bd4cc634f9ca5c3a872755de867db26dd83fe27406f858288a3"
    assert [(row["id"], row["items"]) for row in decision["defined_probes"]] == [
        ("mmlu-pro-10choice", 32), ("arc-challenge-4choice", 32)
    ]
    assert "no persisted or independently authored token manifest" in decision["r2_adapter"]["law"]


def test_d04_retains_t24_wilson_and_no_execution_credit():
    record = json.loads((REPO_ROOT / battery.R2_AUTHORITY_DOC).read_text(encoding="utf-8"))
    assert record["decision"]["proportion_probe_statistic"] == {
        "method": "wilson_one_sided_lower",
        "confidence_threshold_id": "T-24",
        "confidence": 0.95,
        "continuity_correction": False,
        "pass_predicate": "lower_bound > chance_rate",
    }

    assert "no model, capability, R1/R2 exit" in record["execution_boundary"]


# ---------------------------------------------------------------------------
# ProbeItem / ProbeSpec validation
# ---------------------------------------------------------------------------

def test_probe_item_rejects_too_few_choices():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_SPEC_INVALID"):
        battery.ProbeItem(item_id="x", context_ids=(1,), choices=((1,),), correct_choice_index=0)


def test_probe_item_rejects_out_of_range_correct_index():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_SPEC_INVALID"):
        battery.ProbeItem(item_id="x", context_ids=(1,), choices=((1,), (2,)), correct_choice_index=5)


def test_probe_item_rejects_empty_choice():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_SPEC_INVALID"):
        battery.ProbeItem(item_id="x", context_ids=(1,), choices=((1,), ()), correct_choice_index=0)


def test_probe_spec_rejects_bad_metric_type():
    item = _item("i", 0)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_SPEC_INVALID"):
        battery.ProbeSpec(probe_id="p", metric_id="m", metric_type="nonsense", chance_rate=0.5, source_note="", items=(item,))


def test_probe_spec_rejects_out_of_range_chance_rate():
    item = _item("i", 0)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_SPEC_INVALID"):
        battery.ProbeSpec(probe_id="p", metric_id="m", metric_type="proportion", chance_rate=1.5, source_note="", items=(item,))


def test_probe_spec_rejects_no_items():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_HAS_NO_ITEMS"):
        battery.ProbeSpec(probe_id="p", metric_id="m", metric_type="proportion", chance_rate=0.5, source_note="", items=())


def test_probe_spec_rejects_inconsistent_uniform_chance_rate():
    items = (_item("R2E4-RATE-0", 0, n_choices=2), _item("R2E4-RATE-1", 1, n_choices=2))
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHANCE_RATE_INCONSISTENT"):
        battery.ProbeSpec(
            probe_id="R2E4_RATE", metric_id="r2e4.rate", metric_type="proportion",
            chance_rate=0.25, source_note="test fixture", items=items,
        )


def test_probe_spec_rejects_mixed_choice_cardinality():
    items = (_item("R2E4-A", 0, n_choices=2), _item("R2E4-B", 1, n_choices=4))
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHANCE_RATE_INCONSISTENT"):
        battery.ProbeSpec(
            probe_id="R2E4_MIXED", metric_id="r2e4.mixed", metric_type="proportion",
            chance_rate=0.5, source_note="test fixture", items=items,
        )


# ---------------------------------------------------------------------------
# probe manifest loader
# ---------------------------------------------------------------------------

def test_load_probe_manifest_round_trip(tmp_path):
    path, sha = _write_probe_manifest(tmp_path, n_items=3)
    registry, meta = battery.load_probe_manifest(path, sha)
    assert len(registry) == 1
    assert registry[0].probe_id == "TEST_PROBE_1"
    assert len(registry[0].items) == 3
    assert meta == {"path": str(path), "sha256": sha, "schema": battery.PROBE_MANIFEST_SCHEMA, "issue": "TEST-FIXTURE", "probe_count": 1}


def test_load_probe_manifest_rejects_inconsistent_chance_rate(tmp_path):
    path, _ = _write_probe_manifest(tmp_path, n_items=2)
    doc = json.loads(path.read_text())
    doc["probes"][0]["chance_rate"] = 0.25
    raw = json.dumps(doc).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHANCE_RATE_INCONSISTENT"):
        battery.load_probe_manifest(path, battery._sha256_bytes(raw))


def test_load_probe_manifest_rejects_mixed_choice_cardinality(tmp_path):
    path, _ = _write_probe_manifest(tmp_path, n_items=2)
    doc = json.loads(path.read_text())
    doc["probes"][0]["items"][1]["choices"] = [[1], [2], [3], [4]]
    raw = json.dumps(doc).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHANCE_RATE_INCONSISTENT"):
        battery.load_probe_manifest(path, battery._sha256_bytes(raw))


def test_load_probe_manifest_sha_mismatch(tmp_path):
    path, sha = _write_probe_manifest(tmp_path)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_MANIFEST_SHA_MISMATCH"):
        battery.load_probe_manifest(path, "0" * 64)


def test_load_probe_manifest_missing_file(tmp_path):
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_MANIFEST_UNREADABLE"):
        battery.load_probe_manifest(tmp_path / "nope.json", "0" * 64)


def test_load_probe_manifest_bad_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(b"{not json")
    sha = battery._sha256_bytes(path.read_bytes())
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_MANIFEST_UNREADABLE"):
        battery.load_probe_manifest(path, sha)


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: d.__setitem__("extra", 1), "PROBE_MANIFEST_SCHEMA_INVALID"),
    (lambda d: d.pop("issue"), "PROBE_MANIFEST_SCHEMA_INVALID"),
    (lambda d: d.__setitem__("schema", "wrong/v0"), "PROBE_MANIFEST_SCHEMA_INVALID"),
    (lambda d: d.__setitem__("probes", []), "PROBE_MANIFEST_SCHEMA_INVALID"),
    (lambda d: d.__setitem__("probes", "not-a-list"), "PROBE_MANIFEST_SCHEMA_INVALID"),
])
def test_load_probe_manifest_schema_violations(tmp_path, mutate, expected):
    doc = {
        "schema": battery.PROBE_MANIFEST_SCHEMA, "issue": "TEST-FIXTURE",
        "probes": [{
            "probe_id": "P1", "metric_id": "p1.accuracy", "metric_type": "proportion",
            "chance_rate": 0.5, "source_note": "x",
            "items": [{"item_id": "i0", "context_ids": [1], "choices": [[1], [2]], "correct_choice_index": 0}],
        }],
    }
    mutate(doc)
    path = tmp_path / "manifest.json"
    raw = json.dumps(doc).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match=expected):
        battery.load_probe_manifest(path, battery._sha256_bytes(raw))


def test_load_probe_manifest_rejects_duplicate_probe_id(tmp_path):
    path, _ = _write_probe_manifest(tmp_path)
    doc = json.loads(path.read_text())
    doc["probes"].append(doc["probes"][0])
    raw = json.dumps(doc).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="duplicate probe_id"):
        battery.load_probe_manifest(path, battery._sha256_bytes(raw))


def test_load_probe_manifest_rejects_non_int_token_ids(tmp_path):
    doc = {
        "schema": battery.PROBE_MANIFEST_SCHEMA, "issue": "TEST-FIXTURE",
        "probes": [{
            "probe_id": "P1", "metric_id": "p1.accuracy", "metric_type": "proportion",
            "chance_rate": 0.5, "source_note": "x",
            "items": [{"item_id": "i0", "context_ids": [1.5], "choices": [[1], [2]], "correct_choice_index": 0}],
        }],
    }
    path = tmp_path / "manifest.json"
    raw = json.dumps(doc).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_MANIFEST_SCHEMA_INVALID"):
        battery.load_probe_manifest(path, battery._sha256_bytes(raw))


# ---------------------------------------------------------------------------
# confidence-bound primitives
# ---------------------------------------------------------------------------

def test_one_sided_lower_wilson_matches_power_module_two_sided_lo_at_one_sided_z():
    import power
    import statistics
    z = statistics.NormalDist().inv_cdf(0.95)
    expected_lo, _ = power.wilson(17, 20, z=z)
    assert battery.one_sided_lower_wilson(17, 20, 0.95) == pytest.approx(expected_lo)


def test_one_sided_lower_wilson_increases_with_more_successes():
    lo_low = battery.one_sided_lower_wilson(10, 30, 0.95)
    lo_high = battery.one_sided_lower_wilson(29, 30, 0.95)
    assert lo_high > lo_low


@pytest.mark.parametrize("n,successes", [(0, 0), (-1, 0)])
def test_one_sided_lower_wilson_rejects_bad_n(n, successes):
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CI_INPUT_INVALID"):
        battery.one_sided_lower_wilson(successes, n, 0.95)


def test_one_sided_lower_wilson_rejects_successes_out_of_range():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CI_INPUT_INVALID"):
        battery.one_sided_lower_wilson(11, 10, 0.95)


def test_one_sided_lower_bootstrap_is_deterministic_given_seed():
    scores = [0.1, 0.4, 0.9, 0.3, 0.7, 0.2, 0.55, 0.6]
    a = battery.one_sided_lower_bootstrap(scores, 0.95, resamples=500, seed=42)
    b = battery.one_sided_lower_bootstrap(scores, 0.95, resamples=500, seed=42)
    assert a == b


def test_one_sided_lower_bootstrap_constant_scores_collapse_to_that_constant():
    lower = battery.one_sided_lower_bootstrap([0.42] * 20, 0.95, resamples=300, seed=1)
    assert lower == pytest.approx(0.42, abs=1e-9)


def test_one_sided_lower_bootstrap_rejects_empty():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CI_INPUT_INVALID"):
        battery.one_sided_lower_bootstrap([], 0.95)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def test_score_probe_correct_predictions():
    probe = _probe("P", n_items=6)
    scorer = _always_correct_scorer(probe.items)
    results = battery.score_probe(scorer, probe)
    assert all(r["correct"] for r in results)


def test_score_probe_incorrect_predictions():
    probe = _probe("P", n_items=6)
    scorer = _always_wrong_scorer(probe.items)
    results = battery.score_probe(scorer, probe)
    assert not any(r["correct"] for r in results)


def test_score_probe_rejects_graded_metric_type():
    item = _item("i", 0)
    probe = battery.ProbeSpec(probe_id="p", metric_id="m", metric_type="graded", chance_rate=0.0, source_note="", items=(item,))
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="PROBE_METRIC_TYPE_UNSUPPORTED"):
        battery.score_probe(_TableScorer({}), probe)


def test_score_item_determinism_mismatch():
    item = _item("i", 0)

    class _Flip:
        def __init__(self):
            self.n = 0

        def score_choices(self, context_ids, choice_id_lists):
            self.n += 1
            return [float(self.n)] * len(choice_id_lists)

    with pytest.raises(battery.R2ProbeBatteryRefusal, match="DETERMINISM_MISMATCH"):
        battery._score_item(_Flip(), item)


def test_score_item_wrong_shape():
    item = _item("i", 0)

    class _Wrong:
        def score_choices(self, context_ids, choice_id_lists):
            return [0.0, 0.0]  # item has 3 choices

    with pytest.raises(battery.R2ProbeBatteryRefusal, match="SCORER_RETURNED_WRONG_SHAPE"):
        battery._score_item(_Wrong(), item)


def test_score_item_nonfinite():
    item = _item("i", 0)

    class _NaN:
        def score_choices(self, context_ids, choice_id_lists):
            return [float("inf")] * len(choice_id_lists)

    with pytest.raises(battery.R2ProbeBatteryRefusal, match="SCORER_RETURNED_NONFINITE"):
        battery._score_item(_NaN(), item)


# ---------------------------------------------------------------------------
# R2-E4 adjudication
# ---------------------------------------------------------------------------

def test_adjudicate_r2e4_probe_above_chance():
    probe = _probe("P", n_items=30, chance_rate=1.0 / 3.0)
    items = battery.score_probe(_always_correct_scorer(probe.items), probe)
    verdict = battery.adjudicate_r2e4_probe(probe, items)
    assert verdict["above_chance"] is True
    assert verdict["verdict"] == "R2E4_ABOVE_CHANCE"
    assert verdict["ci_method"] == "wilson_one_sided_lower"


def test_adjudicate_r2e4_probe_not_above_chance():
    probe = _probe("P", n_items=30, chance_rate=1.0 / 3.0)
    items = battery.score_probe(_always_wrong_scorer(probe.items), probe)
    verdict = battery.adjudicate_r2e4_probe(probe, items)
    assert verdict["above_chance"] is False
    assert verdict["verdict"] == "R2E4_NOT_ABOVE_CHANCE"


def test_run_r2e4_battery_undefined_on_empty_registry():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="BATTERY_UNDEFINED"):
        battery.run_r2e4(checkpoint_identity={"checkpoint_manifest_sha256": "a" * 64}, registry=(), scorer=_TableScorer({}))


def test_run_r2e4_checkpoint_unbound():
    probe = _probe("P", n_items=3)
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_UNBOUND"):
        battery.run_r2e4(checkpoint_identity={}, registry=(probe,), scorer=_always_correct_scorer(probe.items))


def test_run_r2e4_end_to_end():
    probe = _probe("P", n_items=30, chance_rate=1.0 / 3.0)
    identity = {"checkpoint_manifest_sha256": "b" * 64}
    result = battery.run_r2e4(checkpoint_identity=identity, registry=(probe,), scorer=_always_correct_scorer(probe.items))
    assert result["status"] == "ADJUDICATED"
    assert result["n_probes"] == 1
    assert result["all_probes_above_chance"] is True


# ---------------------------------------------------------------------------
# F-03 / R2-E3 adjudication
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta,sigma,expected", [
    (0.0, 0.1, "NO_SIGNAL"),
    (0.2, 0.1, "NO_SIGNAL"),          # exactly on the band (<=)
    (0.2 + 1e-9, 0.1, "POSITIVE_DELTA_NO_R2_CREDIT"),
    (-0.2 - 1e-9, 0.1, "F1_PIVOT"),
    (-0.2, 0.1, "NO_SIGNAL"),         # exactly on the band, negative side
])
def test_adjudicate_f03_boundaries(delta, sigma, expected):
    assert battery.adjudicate_f03(delta, sigma)["classification"] == expected


def test_adjudicate_f03_rejects_negative_sigma():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="SIGMA_SEED_INVALID"):
        battery.adjudicate_f03(0.1, -0.01)


def test_adjudicate_f03_rejects_nonfinite_sigma():
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="SIGMA_SEED_INVALID"):
        battery.adjudicate_f03(0.1, float("nan"))


def test_run_r2e3_battery_undefined():
    ck = {"checkpoint_manifest_sha256": "a" * 64}
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="BATTERY_UNDEFINED"):
        battery.run_r2e3(
            checkpoint_identity_a3=ck, checkpoint_identity_control=ck, registry=(),
            scorer_a3=_TableScorer({}), scorer_control=_TableScorer({}), sigma_seed_lookup={},
        )


def test_run_r2e3_sigma_seed_missing():
    probe = _probe("P", n_items=10)
    ck = {"checkpoint_manifest_sha256": "a" * 64}
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="SIGMA_SEED_MISSING"):
        battery.run_r2e3(
            checkpoint_identity_a3=ck, checkpoint_identity_control=ck, registry=(probe,),
            scorer_a3=_always_correct_scorer(probe.items), scorer_control=_always_wrong_scorer(probe.items),
            sigma_seed_lookup={},
        )


def test_run_r2e3_f1_pivot_when_control_beats_a3():
    probe = _probe("P", n_items=30)
    ck = {"checkpoint_manifest_sha256": "a" * 64}
    result = battery.run_r2e3(
        checkpoint_identity_a3=ck, checkpoint_identity_control=ck, registry=(probe,),
        scorer_a3=_always_wrong_scorer(probe.items), scorer_control=_always_correct_scorer(probe.items),
        sigma_seed_lookup={probe.metric_id: 0.01},
    )
    assert result["any_f1_pivot"] is True
    assert result["per_probe"][0]["classification"] == "F1_PIVOT"


def test_run_r2e3_positive_delta_no_credit_when_a3_beats_control():
    probe = _probe("P", n_items=30)
    ck = {"checkpoint_manifest_sha256": "a" * 64}
    result = battery.run_r2e3(
        checkpoint_identity_a3=ck, checkpoint_identity_control=ck, registry=(probe,),
        scorer_a3=_always_correct_scorer(probe.items), scorer_control=_always_wrong_scorer(probe.items),
        sigma_seed_lookup={probe.metric_id: 0.01},
    )
    assert result["any_f1_pivot"] is False
    assert result["per_probe"][0]["classification"] == "POSITIVE_DELTA_NO_R2_CREDIT"


def test_run_r2e3_checkpoint_unbound():
    probe = _probe("P", n_items=3)
    ck = {"checkpoint_manifest_sha256": "a" * 64}
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_UNBOUND"):
        battery.run_r2e3(
            checkpoint_identity_a3=ck, checkpoint_identity_control={}, registry=(probe,),
            scorer_a3=_always_correct_scorer(probe.items), scorer_control=_always_correct_scorer(probe.items),
            sigma_seed_lookup={probe.metric_id: 0.1},
        )


# ---------------------------------------------------------------------------
# sigma_seed receipt input contract
# ---------------------------------------------------------------------------

def test_load_sigma_seed_receipt_round_trip(tmp_path):
    path = tmp_path / "sigma.json"
    path.write_text(json.dumps({"sigma_seed": {"m1": 0.02, "m2": 0.01}}), encoding="utf-8")
    assert battery.load_sigma_seed_receipt(path) == {"m1": 0.02, "m2": 0.01}


@pytest.mark.parametrize("doc", [
    {"nope": {}},
    {"sigma_seed": {}},
    {"sigma_seed": "not-a-dict"},
    {"sigma_seed": {"m1": -0.1}},
    {"sigma_seed": {"m1": "not-a-number"}},
    {"sigma_seed": {"m1": True}},
    {"sigma_seed": {"m1": float("nan")}},
])
def test_load_sigma_seed_receipt_rejects_malformed(tmp_path, doc):
    path = tmp_path / "sigma.json"
    try:
        path.write_text(json.dumps(doc), encoding="utf-8")
    except ValueError:
        # NaN isn't valid JSON via json.dumps default; write it manually.
        path.write_text('{"sigma_seed": {"m1": NaN}}', encoding="utf-8")
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="SIGMA_SEED_RECEIPT_INVALID"):
        battery.load_sigma_seed_receipt(path)


def test_load_sigma_seed_receipt_unreadable(tmp_path):
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="SIGMA_SEED_RECEIPT_UNREADABLE"):
        battery.load_sigma_seed_receipt(tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# checkpoint binding -- fake verify_fn (isolation) + real v3 verifier (integration)
# ---------------------------------------------------------------------------

def test_verify_checkpoint_missing_manifest(tmp_path):
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_MANIFEST_MISSING"):
        battery.verify_checkpoint(tmp_path / "nope.json", tmp_path / "config.json")


def test_verify_checkpoint_missing_model_config(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_MODEL_CONFIG_MISSING"):
        battery.verify_checkpoint(manifest, tmp_path / "config.json")


def test_verify_checkpoint_wraps_verify_fn_exceptions(tmp_path):
    manifest = tmp_path / "manifest.json"
    config = tmp_path / "config.json"
    manifest.write_text("{}", encoding="utf-8")
    config.write_text("{}", encoding="utf-8")

    def _raises(m, c):
        raise ValueError("synthetic corruption")

    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_VERIFY_FAILED"):
        battery.verify_checkpoint(manifest, config, verify_fn=_raises)


def test_verify_checkpoint_refuses_unnamed_subject(tmp_path):
    manifest = tmp_path / "manifest.json"
    config = tmp_path / "config.json"
    manifest.write_text("{}", encoding="utf-8")
    config.write_text("{}", encoding="utf-8")

    def _unnamed(m, c):
        return {"goal_id": "EMBER-02"}

    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_VERIFY_FAILED"):
        battery.verify_checkpoint(manifest, config, verify_fn=_unnamed)


def test_verify_checkpoint_real_v3_integration(tmp_path):
    """Integration proof: a genuinely valid v3 sparse checkpoint (built by
    the SAME fixture helper the checkpoint consumer's own test suite uses)
    verifies end to end through THIS module's wrapper, with zero mocking."""
    manifest, config = _valid_checkpoint(tmp_path, "ckpt")
    identity = battery.verify_checkpoint(manifest, config)
    assert identity["checkpoint_manifest_sha256"]
    assert identity["result"] == "VERIFIED_CHECKPOINT_INPUT"
    assert identity["goal_id"] == "EMBER-02"


def test_verify_checkpoint_real_v3_integration_detects_tamper(tmp_path):
    manifest, config = _valid_checkpoint(tmp_path, "ckpt")
    doc = json.loads(manifest.read_text())
    doc["expert_checkpoint_sha256"]["tool"] = "0" * 64
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_VERIFY_FAILED"):
        battery.verify_checkpoint(manifest, config)


# ---------------------------------------------------------------------------
# receipts
# ---------------------------------------------------------------------------

def test_build_receipt_passes_schema_floor():
    import receipt_check
    receipt = battery.build_receipt(
        ticket="TEST-1435", exit_criterion="R2-E4",
        checkpoint={"checkpoint_manifest_sha256": "a" * 64},
        probe_manifest_meta=None, status="REFUSED", refusal_reason="BATTERY_UNDEFINED",
    )
    assert receipt_check.validate_receipt(receipt) == []
    assert receipt["invariant_sha256"] == receipt_check.INVARIANT_SHA256
    assert receipt["spec_defects"] == []
    assert receipt["issue_refs"] == ["#1435", "#1498"]
    assert receipt["r2_battery_authority"] == {
        "document": battery.R2_AUTHORITY_DOC,
        "schema": battery.R2_AUTHORITY_SCHEMA,
        "decision_id": battery.R2_AUTHORITY_DECISION_ID,
    }


def test_build_receipt_with_result():
    receipt = battery.build_receipt(
        ticket="TEST-1435", exit_criterion="R2-E4",
        checkpoint={"checkpoint_manifest_sha256": "a" * 64},
        probe_manifest_meta={"path": "x", "sha256": "b" * 64, "schema": battery.PROBE_MANIFEST_SCHEMA, "probe_count": 1},
        status="ADJUDICATED", result={"n_probes": 1},
    )
    assert receipt["result"] == {"n_probes": 1}
    assert "refusal_reason" not in receipt


def test_build_receipt_rejects_unnamed_subject_flat():
    # build_receipt must not trust its caller: called directly (bypassing
    # verify_checkpoint/_require_named_subject entirely) with a flat R2-E4-shaped
    # checkpoint block missing checkpoint_manifest_sha256, it must refuse rather
    # than emit a receipt that cannot name its subject.
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_UNBOUND"):
        battery.build_receipt(
            ticket="TEST-1435", exit_criterion="R2-E4",
            checkpoint={"arm": "A3"},
            probe_manifest_meta=None, status="REFUSED", refusal_reason="BATTERY_UNDEFINED",
        )


def test_build_receipt_rejects_unnamed_subject_in_arm_mapping():
    # The R2-E3-shaped checkpoint block is an arm-label -> identity mapping.
    # A subject missing its hash on EITHER arm must refuse -- this is the
    # per-subject iteration _iter_checkpoint_subjects exists to perform; a
    # single top-level _require_named_subject(checkpoint) call could not see
    # into this shape at all.
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_UNBOUND"):
        battery.build_receipt(
            ticket="TEST-1435", exit_criterion="R2-E3",
            checkpoint={
                "A3": {"checkpoint_manifest_sha256": "a" * 64, "arm": "A3"},
                "control": {"arm": "A2"},  # missing checkpoint_manifest_sha256
            },
            probe_manifest_meta=None, status="REFUSED", refusal_reason="BATTERY_UNDEFINED",
        )


def test_build_receipt_rejects_unrecognized_checkpoint_shape():
    # Neither a flat identity nor an arm-label mapping -- e.g. an empty dict --
    # must also refuse rather than silently pass validation.
    with pytest.raises(battery.R2ProbeBatteryRefusal, match="CHECKPOINT_UNBOUND"):
        battery.build_receipt(
            ticket="TEST-1435", exit_criterion="R2-E4",
            checkpoint={},
            probe_manifest_meta=None, status="REFUSED", refusal_reason="BATTERY_UNDEFINED",
        )


def test_write_receipt_round_trips(tmp_path):
    receipt = battery.build_receipt(
        ticket="TEST-1435", exit_criterion="R2-E3",
        checkpoint={"checkpoint_manifest_sha256": "a" * 64},
        probe_manifest_meta=None, status="REFUSED", refusal_reason="BATTERY_UNDEFINED",
    )
    out = tmp_path / "nested" / "receipt.json"
    battery.write_receipt(out, receipt)
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8")) == receipt


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_selftest_returns_zero():
    assert battery.main(["--selftest"]) == 0


def test_cli_r2e4_missing_checkpoint_files_refuses_no_receipt(tmp_path):
    out = tmp_path / "receipt.json"
    rc = battery.main([
        "--run-r2e4",
        "--checkpoint-manifest", str(tmp_path / "nope" / "manifest.json"),
        "--model-config", str(tmp_path / "nope" / "config.json"),
        "--out", str(out),
    ])
    assert rc == 3
    assert not out.exists()


def test_cli_r2e4_real_checkpoint_battery_undefined_writes_receipt(tmp_path):
    manifest, config = _valid_checkpoint(tmp_path, "ckpt")
    out = tmp_path / "receipt.json"
    rc = battery.main([
        "--run-r2e4",
        "--checkpoint-manifest", str(manifest),
        "--model-config", str(config),
        "--arm", "A3",
        "--out", str(out),
    ])
    assert rc == 3
    assert out.is_file()
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["status"] == "REFUSED"
    assert "BATTERY_UNDEFINED" in receipt["refusal_reason"]
    assert receipt["checkpoint"]["arm"] == "A3"
    assert receipt["checkpoint"]["checkpoint_manifest_sha256"]
    import receipt_check
    assert receipt_check.validate_receipt(receipt) == []


def test_cli_r2e4_legacy_token_manifest_is_superseded_by_single_text_authority(tmp_path):
    manifest, config = _valid_checkpoint(tmp_path, "ckpt")
    probe_path, probe_sha = _write_probe_manifest(tmp_path)
    out = tmp_path / "receipt.json"
    rc = battery.main([
        "--run-r2e4",
        "--checkpoint-manifest", str(manifest),
        "--model-config", str(config),
        "--probe-manifest", str(probe_path),
        "--probe-manifest-sha256", probe_sha,
        "--out", str(out),
    ])
    assert rc == 3
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert "PROBE_AUTHORITY_SUPERSEDED" in receipt["refusal_reason"]
    assert receipt["probe_manifest"]["probe_count"] == 0


def test_cli_r2e4_requires_out(tmp_path):
    # --out is checked before checkpoint verification (folded into the same
    # R2ProbeBatteryRefusal try/except as CHECKPOINT_* -- OUTPUT_PATH_REQUIRED
    # is not a special case), so nonexistent checkpoint paths here never mask
    # the refusal this test targets.
    rc = battery.main(["--run-r2e4", "--checkpoint-manifest", "x", "--model-config", "y"])
    assert rc == 3
    assert not (tmp_path / "receipt.json").exists()


def test_cli_r2e4_missing_required_args_is_argparse_error():
    with pytest.raises(SystemExit) as excinfo:
        battery.main(["--run-r2e4"])
    assert excinfo.value.code == 2


def test_cli_r2e3_requires_out():
    # Same OUTPUT_PATH_REQUIRED fold-in as r2e4, exercised on the r2e3 entrypoint.
    rc = battery.main([
        "--run-r2e3",
        "--checkpoint-manifest-a3", "x", "--model-config-a3", "y",
        "--checkpoint-manifest-control", "x", "--model-config-control", "y",
    ])
    assert rc == 3


def test_cli_r2e3_real_checkpoints_battery_undefined_writes_receipt(tmp_path):
    manifest_a3, config_a3 = _valid_checkpoint(tmp_path, "a3")
    manifest_ctrl, config_ctrl = _valid_checkpoint(tmp_path, "ctrl")
    out = tmp_path / "receipt.json"
    rc = battery.main([
        "--run-r2e3",
        "--checkpoint-manifest-a3", str(manifest_a3), "--model-config-a3", str(config_a3),
        "--checkpoint-manifest-control", str(manifest_ctrl), "--model-config-control", str(config_ctrl),
        "--control-arm", "A2",
        "--out", str(out),
    ])
    assert rc == 3
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["status"] == "REFUSED"
    assert "BATTERY_UNDEFINED" in receipt["refusal_reason"]
    assert receipt["checkpoint"]["A3"]["arm"] == "A3"
    assert receipt["checkpoint"]["control"]["arm"] == "A2"
    import receipt_check
    assert receipt_check.validate_receipt(receipt) == []


def test_cli_no_mode_prints_help_and_returns_1():
    assert battery.main([]) == 1


def test_cli_via_subprocess_selftest():
    """One real subprocess invocation, mirroring how a human/CI would
    actually run this -- proves the module also works as `python
    src/ember/governance/scripts/r2_cheap_probe_battery.py --selftest`, not just as an import."""
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "ember" / "governance" / "scripts" / "r2_cheap_probe_battery.py"), "--selftest"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "R2_CHEAP_PROBE_BATTERY_SELFTEST_PASS" in completed.stdout
