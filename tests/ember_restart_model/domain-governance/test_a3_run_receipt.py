# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real-path closure tests for the R1-E8 A3-arm run receipt producer.

The happy-path test mints a receipt from real fixture artifacts and passes it,
unmocked, through BOTH real downstream consumers: src/ember/governance/scripts/r1_e8_validator.py's own
`_validate_run`, and certified_train_launch.py's matched-A3 verification reached
through its public entrypoint `validate_certified_request` against a real valid A1
launch bundle (the hand-built matched-a3-run.json swapped for the minted one).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest

DOMAIN_TESTS = Path(__file__).resolve().parent
LEGACY_TESTS = DOMAIN_TESTS.parent
for test_root in (str(DOMAIN_TESTS), str(LEGACY_TESTS)):
    if test_root not in sys.path:
        sys.path.insert(0, test_root)
import test_a1_certified_launch as a1_authority_fixtures  # noqa: E402
_launch_fixtures_spec = importlib.util.spec_from_file_location(
    "issue898_a3_certified_train_launch_fixtures",
    DOMAIN_TESTS / "test_certified_train_launch.py",
)
assert _launch_fixtures_spec is not None and _launch_fixtures_spec.loader is not None
launch_fixtures = importlib.util.module_from_spec(_launch_fixtures_spec)
_launch_fixtures_spec.loader.exec_module(launch_fixtures)


ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
SCRIPTS = ROOT / "src" / "ember" / "governance" / "scripts"
THRESHOLDS_PATH = (
    ROOT
    / "docs"
    / "domains"
    / "governance"
    / "spec"
    / "ember02-preregistration-thresholds-v1.json"
)
T06 = Decimal("0.95")
RUN_ID = "a3-fixture-run-0001"


def _load_module(name: str, path: Path, *, sys_path_dir: Path | None = None):
    inserted = None
    if sys_path_dir is not None and str(sys_path_dir) not in sys.path:
        inserted = str(sys_path_dir)
        sys.path.insert(0, inserted)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted is not None:
            sys.path.remove(inserted)


def _load_producer():
    return _load_module("a3_run_receipt_under_test", TOOLS / "a3_run_receipt.py", sys_path_dir=TOOLS)


def _load_validator():
    return _load_module("r1_e8_validator_under_test", SCRIPTS / "r1_e8_validator.py")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _comparison_authority(root: Path) -> Path:
    path = root / "comparison-authority.json"
    _write_json(
        path,
        {
            "schema_version": "ember-a1-comparison-authority-v1",
            "comparison_id": "r1-e8-a1-vs-a3-fixture",
            "matched_a3_run": {"path": "matched-a3-run.json", "sha256": "0" * 64},
            "token_shards_receipt_sha256": "1" * 64,
            "shard_sequence_sha256": "2" * 64,
            "tokenizer_sha256": "3" * 64,
            "seed": 91,
            "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
            "schedule_sha256": "4" * 64,
            "genesis_authority_sha256": "5" * 64,
        },
    )
    return path


def _certificate(root: Path, *, public_master_sha: str = "a" * 40) -> Path:
    path = root / "certificate.json"
    _write_json(path, {"schema_version": "fixture-certificate-v1", "public_master_sha": public_master_sha})
    return path


def _run_spec(root: Path) -> Path:
    path = root / "run-spec.json"
    _write_json(path, {"note": "A3 certified run spec fixture", "seed": 91})
    return path


def _architecture_manifest(root: Path, **overrides: object) -> Path:
    doc = {
        "schema_version": "ember-a3-architecture-manifest-v1",
        "tier": "A3",
        "mechanism": "role-prior-sparse",
        "architecture_revision": "ember-sparse-3b-v2",
        "parameter_count": 3_839_161_856,
        "active_parameter_count": 1_020_589_568,
        "contains_router_or_experts": True,
        "optimizer": {
            "kind": "AdamW",
            "full_state": True,
            "cpu_offload": False,
            "covered_parameter_count": 3_839_161_856,
        },
    }
    doc.update(overrides)
    path = root / "architecture-manifest.json"
    _write_json(path, doc)
    return path


def _telemetry(root: Path, *, run_id: str = RUN_ID) -> Path:
    """The real frozen `train_step` envelope
    (`{"ts":..., "kind":"train_step", "source":"ember-restart-3b", "payload":
    {"run_id":..., "step":int, ...}}`) -- the ONLY shape the real A1/A3
    producers (`a1_execution.py`, `run_vertical_slice.py`) ever emit. A flat
    top-level `{"run_id":..., "step":...}` row, as this fixture wrote before
    issue #1464's second residual, is never produced by any real run and no
    longer satisfies `_require_run_stepped`."""
    path = root / "a3-telemetry.jsonl"
    rows = [
        {
            "ts": "2026-08-21T16:49:00.000000Z",
            "kind": "train_step",
            "source": "ember-restart-3b",
            "payload": {"run_id": run_id, "step": 1, "tokens": 8, "loss": "1.234500000000"},
        },
        {
            "ts": "2026-08-21T16:49:01.000000Z",
            "kind": "train_step",
            "source": "ember-restart-3b",
            "payload": {"run_id": run_id, "step": 2, "tokens": 8, "loss": "1.100000000000"},
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    return path


def _energy_receipt(root: Path, *, captured: int = 96, intended: int = 100) -> Path:
    coverage = Decimal(captured) / Decimal(intended)
    doc = {
        "schema_version": "ember-energy-proxy-run-v1",
        "result": "MEASURED",
        "executed": True,
        "training_launched": True,
        "intended_samples": intended,
        "captured_samples": captured,
        "t06_coverage_floor": "0.95",
        "coverage_meets_t06": coverage >= T06,
        "energy": {"sample_coverage_fraction": format(coverage, "f")},
    }
    path = root / "a3-energy-proxy.json"
    _write_json(path, doc)
    return path


def _checkpoint_receipt(root: Path, *, corrupt_sha: bool = False) -> Path:
    checkpoint_dir = root / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoint_dir / "a3-checkpoint.bin"
    checkpoint_file.write_bytes(b"fixture checkpoint payload bytes" * 4)
    real_sha = hashlib.sha256(checkpoint_file.read_bytes()).hexdigest()
    declared_sha = ("f" * 64) if corrupt_sha else real_sha
    path = root / "a3-checkpoint-receipt.json"
    _write_json(
        path,
        {
            "schema_version": "ember-a3-checkpoint-receipt-v1",
            "checkpoint_path": "checkpoints/a3-checkpoint.bin",
            "checkpoint_sha256": declared_sha,
        },
    )
    return path


def _valid_kwargs(root: Path, output_path: Path) -> dict[str, object]:
    return {
        "output_path": output_path,
        "telemetry_path": _telemetry(root),
        "run_id": RUN_ID,
        "energy_receipt_path": _energy_receipt(root),
        "thresholds_path": THRESHOLDS_PATH,
        "checkpoint_receipt_path": _checkpoint_receipt(root),
        "comparison_authority_path": _comparison_authority(root),
        "certificate_path": _certificate(root),
        "run_spec_path": _run_spec(root),
        "architecture_manifest_path": _architecture_manifest(root),
    }


def test_mint_a3_run_receipt_passes_both_real_downstream_consumers() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        output_path = root / "matched-a3-run.json"
        result = module.mint_a3_run_receipt(**_valid_kwargs(root, output_path))
        assert result == output_path

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        assert doc["schema_version"] == "ember02-r1-e8-run-v1"
        assert doc["arm_id"] == "A3"
        assert doc["status"] == "TERMINAL"
        assert doc["source_commit"] == "a" * 40
        assert doc["checkpoint_sha256"] == hashlib.sha256(
            (root / "checkpoints" / "a3-checkpoint.bin").read_bytes()
        ).hexdigest()
        unsigned = {key: value for key, value in doc.items() if key != "receipt_sha256"}
        # Self-digest convention: compact JSON, no trailing newline, ensure_ascii
        # False -- matching src/ember/governance/scripts/r1_e8_validator.py's `_self_digest` exactly
        # (see fix(training): align matched-A3 self-digest convention, #1464).
        assert doc["receipt_sha256"] == hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        # Real consumer 1 (bare check): src/ember/governance/scripts/r1_e8_validator.py's own
        # _validate_run, unmocked. Does not check digest format on its own.
        validator = _load_validator()
        validator._validate_run(doc, arm="A3", tier=None, t06=T06)  # must not raise


def test_one_minted_a3_receipt_passes_both_full_real_pipelines_unmocked() -> None:
    """The closure test the digest-convention gap demanded.

    A SINGLE minted A3 receipt, unmocked, real fixture artifacts throughout,
    must satisfy BOTH real full pipelines that actually reopen and
    self-digest a matched A3 run receipt in production:

      (a) src/ember/governance/scripts/r1_e8_validator.py's `_reopen_ref(..., self_digest=True)`,
          the exact call `validate_e8` makes on the a3_run reference -- NOT
          the bare `_validate_run`, which never checks digest format.
      (b) certified_train_launch.py's matched-A3 verification, reached
          through its public entrypoint `validate_certified_request`.

    Before fix(training): align matched-A3 self-digest convention (#1464),
    no single receipt_sha256 could satisfy both: (a) requires compact JSON
    hashed with no trailing newline (r1_e8_validator._self_digest), (b)
    required compact JSON hashed WITH one (certified_train_launch's own
    `_canonical_bytes`, now scoped away from this check into a dedicated
    `_matched_a3_self_digest_sha256` matching (a)'s convention).
    """
    module = _load_producer()
    validator = _load_validator()
    launch_module = launch_fixtures.load_module()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        paths = launch_fixtures.write_valid_bundle(root / "launch")
        authority = a1_authority_fixtures._install_valid_a1_authority(paths)
        comparison_path = authority["comparison_path"]
        matched_path = comparison_path.parent / "matched-a3-run.json"
        matched_path.unlink()

        # Mint the ONE receipt every downstream check below reopens as-is,
        # bound to the launch bundle's REAL comparison authority and
        # certificate (not the generic fixture ones) so the identity and
        # source_commit agree with what certified_train_launch.py itself
        # independently recomputes in check (b) below.
        module.mint_a3_run_receipt(
            **{
                **_valid_kwargs(root / "mint", matched_path),
                "comparison_authority_path": comparison_path,
                "certificate_path": paths["certificate"],
            }
        )

        # (a) src/ember/governance/scripts/r1_e8_validator.py's real self-digest-checking reopen.
        minted_sha256 = hashlib.sha256(matched_path.read_bytes()).hexdigest()
        doc, digest = validator._reopen_ref(
            matched_path.parent,
            {"path": matched_path.name, "sha256": minted_sha256},
            "A3_RUN_INVALID",
        )  # self_digest=True by default -- must not raise
        assert digest == minted_sha256
        assert doc["arm_id"] == "A3"

        # (b) certified_train_launch.py's real matched-A3 verification via its
        # public entrypoint. The comparison authority's back-reference and
        # every hash bound over it are refreshed to the real minted bytes,
        # exactly as a real authoring pipeline would after minting this
        # receipt -- the matched-a3-run.json file itself is never rewritten.
        comparison_doc = json.loads(comparison_path.read_text(encoding="utf-8"))
        comparison_doc["matched_a3_run"]["sha256"] = minted_sha256
        _write_json(comparison_path, comparison_doc)
        run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
        run_spec["a1_comparison_authority_sha256"] = hashlib.sha256(
            comparison_path.read_bytes()
        ).hexdigest()
        launch_fixtures.write_json(paths["run_spec"], run_spec)
        launch_fixtures._write_custody_sidecars(paths)
        with mock.patch.object(launch_module, "read_current_master", return_value=launch_fixtures.SHA):
            launch = launch_module.validate_certified_request(
                paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
            )  # must not raise
        assert launch.a1_family == a1_authority_fixtures.A1_FAMILY


def test_mint_refuses_to_overwrite_an_existing_receipt() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        output_path = root / "matched-a3-run.json"
        module.mint_a3_run_receipt(**_valid_kwargs(root, output_path))
        with pytest.raises(FileExistsError):
            module.mint_a3_run_receipt(**_valid_kwargs(root, output_path))


def test_mint_refuses_when_telemetry_names_no_stepped_row_for_run_id() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        kwargs = _valid_kwargs(root, root / "matched-a3-run.json")
        kwargs["telemetry_path"] = _telemetry(root, run_id="a-different-run")
        with pytest.raises(module.A3ReceiptRefused, match="telemetry names no stepped row"):
            module.mint_a3_run_receipt(**kwargs)


def test_require_run_stepped_reads_the_real_envelope_shape(tmp_path: Path) -> None:
    """Issue #1464's second residual: the real producers write the frozen
    `train_step` envelope, never a flat top-level `{run_id, step}` row.
    `_require_run_stepped` must find the step evidence inside `payload`."""
    module = _load_producer()
    telemetry_path = tmp_path / "a3-telemetry.jsonl"
    rows = [
        {"ts": "2026-08-21T16:49:00Z", "kind": "train_step", "source": "ember-restart-3b",
         "payload": {"run_id": "envelope-run", "step": 1, "tokens": 8}},
    ]
    telemetry_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")

    module._require_run_stepped(telemetry_path, "envelope-run")  # must not raise


def test_require_run_stepped_refuses_a_flat_row_with_no_envelope(tmp_path: Path) -> None:
    """RED regression for the pre-fix defect: a flat top-level
    `{"run_id":..., "step":...}` row -- the old fixture shape, never emitted
    by any real producer -- no longer satisfies the gate. Envelope-only is
    correct because the ONLY real producer emits envelopes."""
    module = _load_producer()
    telemetry_path = tmp_path / "a3-telemetry.jsonl"
    rows = [{"run_id": "flat-run", "step": 1, "tokens": 8}]
    telemetry_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(module.A3ReceiptRefused, match="telemetry names no stepped row"):
        module._require_run_stepped(telemetry_path, "flat-run")


def test_require_run_stepped_skips_non_train_step_envelopes_without_refusing(tmp_path: Path) -> None:
    """A well-formed row that is simply a different event kind, a different
    source, another run's payload, or a non-object payload is not a
    structural defect -- it just does not count. Refusal is reserved for
    unparseable JSON and non-object rows."""
    module = _load_producer()
    telemetry_path = tmp_path / "a3-telemetry.jsonl"
    rows = [
        {"ts": "t", "kind": "checkpoint_saved", "source": "ember-restart-3b",
         "payload": {"run_id": "run-x", "step": 1}},
        {"ts": "t", "kind": "train_step", "source": "some-other-source",
         "payload": {"run_id": "run-x", "step": 1}},
        {"ts": "t", "kind": "train_step", "source": "ember-restart-3b",
         "payload": "not-an-object"},
        {"ts": "t", "kind": "train_step", "source": "ember-restart-3b",
         "payload": {"run_id": "a-different-run", "step": 1}},
        {"ts": "t", "kind": "train_step", "source": "ember-restart-3b",
         "payload": {"run_id": "run-x", "step": 1}},
    ]
    telemetry_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")

    module._require_run_stepped(telemetry_path, "run-x")  # must not raise (last row matches)


def test_require_run_stepped_excludes_bool_step(tmp_path: Path) -> None:
    """`bool` is an `int` subclass in Python, so a naive `isinstance(step,
    int)` check would let `step: true` count as a positive step. The gate
    must use `type(step) is not int` (matching
    `a1_e8_evidence.derive_liveness_series`) so a bool payload never counts
    as step evidence."""
    module = _load_producer()
    telemetry_path = tmp_path / "a3-telemetry.jsonl"
    rows = [
        {"ts": "t", "kind": "train_step", "source": "ember-restart-3b",
         "payload": {"run_id": "bool-run", "step": True}},
    ]
    telemetry_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(module.A3ReceiptRefused, match="telemetry names no stepped row"):
        module._require_run_stepped(telemetry_path, "bool-run")


def test_require_run_stepped_still_refuses_unparseable_and_non_object_rows(tmp_path: Path) -> None:
    """The existing structural refusals are unchanged by the envelope fix."""
    module = _load_producer()

    unparseable = tmp_path / "unparseable.jsonl"
    unparseable.write_text("{not valid json\n", encoding="utf-8")
    with pytest.raises(module.A3ReceiptRefused, match="unparseable row"):
        module._require_run_stepped(unparseable, "run-x")

    non_object = tmp_path / "non-object.jsonl"
    non_object.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(module.A3ReceiptRefused, match="is not an object"):
        module._require_run_stepped(non_object, "run-x")


def test_mint_refuses_when_energy_coverage_is_below_t06() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        kwargs = _valid_kwargs(root, root / "matched-a3-run.json")
        kwargs["energy_receipt_path"] = _energy_receipt(root, captured=80, intended=100)
        with pytest.raises(module.A3ReceiptRefused, match="below the T-06 floor"):
            module.mint_a3_run_receipt(**kwargs)


def test_mint_refuses_when_checkpoint_sha256_disagrees_with_real_bytes() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        kwargs = _valid_kwargs(root, root / "matched-a3-run.json")
        kwargs["checkpoint_receipt_path"] = _checkpoint_receipt(root, corrupt_sha=True)
        with pytest.raises(module.A3ReceiptRefused, match="disagrees with the real checkpoint bytes"):
            module.mint_a3_run_receipt(**kwargs)


def test_mint_refuses_when_comparison_authority_is_missing_an_identity_key() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        kwargs = _valid_kwargs(root, root / "matched-a3-run.json")
        comparison_path = kwargs["comparison_authority_path"]
        doc = json.loads(comparison_path.read_text(encoding="utf-8"))
        del doc["genesis_authority_sha256"]
        _write_json(comparison_path, doc)
        with pytest.raises(module.A3ReceiptRefused, match="missing identity keys"):
            module.mint_a3_run_receipt(**kwargs)


def test_mint_refuses_when_certificate_public_master_sha_is_not_a_git_sha() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        kwargs = _valid_kwargs(root, root / "matched-a3-run.json")
        kwargs["certificate_path"] = _certificate(root, public_master_sha="not-a-git-sha")
        with pytest.raises(module.A3ReceiptRefused, match="public_master_sha must be a lowercase 40-hex"):
            module.mint_a3_run_receipt(**kwargs)


def test_mint_refuses_when_architecture_optimizer_coverage_is_inconsistent() -> None:
    module = _load_producer()
    with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
        root = Path(directory)
        kwargs = _valid_kwargs(root, root / "matched-a3-run.json")
        kwargs["architecture_manifest_path"] = _architecture_manifest(
            root,
            optimizer={
                "kind": "AdamW", "full_state": True, "cpu_offload": False,
                "covered_parameter_count": 1,
            },
        )
        with pytest.raises(module.A3ReceiptRefused, match="optimizer block is invalid"):
            module.mint_a3_run_receipt(**kwargs)
