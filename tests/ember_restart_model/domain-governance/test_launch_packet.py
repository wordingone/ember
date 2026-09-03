# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the EMBER-01 cond7 launch-packet readiness runner.

Each implemented preflight gets a PASS case and a FAIL-CLOSED negative case.
No GPU, no training; pure config arithmetic + on-disk path checks.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[3] / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "launch_packet.py"
_spec = importlib.util.spec_from_file_location("launch_packet", _MODULE_PATH)
lp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lp)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "ember-restart-3b.json"

# The architecture's own expert declaration, read from the model module rather than
# copied here, so a change to the roster moves the expectation with it.
_TOOLS_DIRECTORY = Path(__file__).resolve().parents[3] / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
if str(_TOOLS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIRECTORY))
from repository_layout import resolve_repository_authority  # noqa: E402

_MODEL_PATH = Path(__file__).resolve().parents[3] / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "model.py"
_model_spec = importlib.util.spec_from_file_location("ember_restart_model_decl", _MODEL_PATH)
_model_mod = importlib.util.module_from_spec(_model_spec)
# Register before exec: model.py defines dataclasses, and dataclasses resolves a
# field's type by looking its module up in sys.modules -- an unregistered module
# makes that lookup return None and collection dies in dataclasses._is_type.
sys.modules[_model_spec.name] = _model_mod
_model_spec.loader.exec_module(_model_mod)
_EXPERT_NAMES = _model_mod.EXPERT_NAMES


@pytest.fixture
def cfg() -> dict:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def root() -> Path:
    return _CONFIG_PATH.resolve().parent.parent


@pytest.fixture(autouse=True)
def _redirect_launch_packet_receipts(tmp_path, monkeypatch, root):
    """#1341: every call into lp.run()/lp.main() in this suite must write its
    transient packet.jsonl receipt under pytest's own tmp_path, never into the
    tracked repo tree -- regardless of whether a test calls lp.run() directly
    (positional config-path only, no receipt_root kwarg) or exercises the CLI
    entry point. Autouse + env-var (not a per-call kwarg) so this holds for
    every test in the file, present and future, without each one opting in.

    Also the regression guard the issue asks for: assert the real
    receipts/ember-01-launch-packet/ dir gains no new subdirectory across this
    test's run. A few tests intentionally write/clean up individual fixture
    FILES directly under that dir (see the stream-receipt tests below) -- this
    only polices the timestamped-directory byproduct class the issue is about.
    """
    env_var = lp.RECEIPT_ROOT_ENV
    monkeypatch.setenv(env_var, str(tmp_path))
    real_packet_root = root / "receipts" / "ember-01-launch-packet"
    before = {p for p in real_packet_root.iterdir() if p.is_dir()} if real_packet_root.is_dir() else set()
    yield
    after = {p for p in real_packet_root.iterdir() if p.is_dir()} if real_packet_root.is_dir() else set()
    new_dirs = after - before
    assert not new_dirs, (
        f"suite run left new receipt dirs in the tracked tree: {new_dirs} "
        f"(env var {env_var} should have redirected these under {tmp_path})"
    )


# ---- no-sub-3B ------------------------------------------------------------

def test_no_sub_3b_pass_real_config(cfg, root):
    r = lp.preflight_no_sub_3b(cfg, root)
    assert r["status"] == "pass"
    assert r["computed_total_parameters"] >= 3_000_000_000
    # Independent recompute must match the contract's stated total exactly.
    assert r["matches_stated"] is True


def test_no_sub_3b_fail_closed_small_model(cfg, root):
    small = copy.deepcopy(cfg)
    small["model"]["hidden_size"] = 256   # collapses param count well below 3e9
    small["model"]["layers"] = 2
    r = lp.preflight_no_sub_3b(small, root)
    assert r["status"] == "fail"
    assert r["computed_total_parameters"] < 3_000_000_000


def test_no_sub_3b_fail_closed_missing_field(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["model"]["hidden_size"]
    r = lp.preflight_no_sub_3b(broken, root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()


# ---- resource -------------------------------------------------------------

def test_resource_pass_real_config(cfg, root):
    r = lp.preflight_resource(cfg, root)
    assert r["status"] == "pass"
    assert r["peak_gpu_mem_gib"] <= 24.0


def test_resource_fail_closed_over_ceiling(cfg, root):
    huge = copy.deepcopy(cfg)
    # Inflate the runtime reserve past the 24 GiB ceiling; every term still present.
    huge["training"]["memory"]["runtime_reserve_gib"] = 64
    r = lp.preflight_resource(huge, root)
    assert r["status"] == "fail"
    assert r["peak_gpu_mem_gib"] > 24.0


def test_resource_fail_closed_missing_term(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["training"]["memory"]["parameter_bytes"]
    r = lp.preflight_resource(broken, root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()


# ---- storage --------------------------------------------------------------

def test_storage_pass_real_config(cfg, root):
    r = lp.preflight_storage(cfg, root)
    assert r["status"] == "pass"
    assert r["free_disk_gib"] >= r["checkpoint_floor_gib"]
    assert all(p["exists"] for p in r["checked_paths"])


def test_storage_fail_closed_missing_corpus(cfg, root, tmp_path):
    # Point the runner at a repo root with NO data files -> declared paths absent.
    empty_root = tmp_path
    (empty_root / "configs").mkdir()
    r = lp.preflight_storage(cfg, empty_root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()
    assert any(not p["exists"] for p in r["checked_paths"])


def test_storage_fail_closed_uncomputable_floor(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["checkpoints"]["serialization"]["model_parameter_bytes"]
    r = lp.preflight_storage(broken, root)
    assert r["status"] == "fail"


# ---- recovery ---------------------------------------------------------------
# Real save -> simulate-kill -> resume round trip on a tiny CPU shape,
# exercising the REAL checkpoint_artifacts + pretrain machinery (no GPU).

def test_recovery_pass_real_roundtrip(cfg, root):
    r = lp.preflight_recovery(cfg, root)
    assert r["status"] == "pass", r
    # A checkpoint carries three fixed-role shards -- shared_model, optimizer_state
    # and replay_state -- plus exactly one shard per declared expert
    # (checkpoint_artifacts.py builds the list in that order). The literal this
    # replaces said 6, which was a three-expert count; the decoder has declared
    # four experts since the sparse routed rewrite, so the receipt has produced 7
    # for longer than this assertion has been in the tree. Deriving from the
    # architecture declaration also makes the assertion fail if a fixed role is
    # dropped or an expert shard is skipped, which a literal cannot see.
    assert r["checkpoint_shards"] == 3 + len(_EXPERT_NAMES)
    assert r["data_cursor"]["global_step"] == 4


def test_recovery_fail_closed_broken_import(cfg, tmp_path):
    # A repo root with no src/ember/infrastructure/tools/ember-restart-3b/ package and no configs/ --
    # the round-trip cannot run (module caching in-process may still resolve
    # the real trainer modules, but the real config file it must sha256 is
    # absent) -> fail closed, never a silent pass.
    empty_root = tmp_path
    r = lp.preflight_recovery(cfg, empty_root)
    assert r["status"] == "fail"
    assert r["reason"]


def test_recovery_fail_closed_tampered_checkpoint(cfg, root, monkeypatch):
    # Corrupt the checkpoint's replay state after write, before load, by
    # patching load_checkpoint_artifacts to simulate a shard hash mismatch --
    # the round-trip must fail closed, never silently accept divergent state.
    import importlib
    import sys as _sys
    tools_dir = str(root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b")
    if tools_dir not in _sys.path:
        _sys.path.insert(0, tools_dir)
    checkpoint_artifacts = importlib.import_module("checkpoint_artifacts")

    def _tampering_load(*_args, **_kwargs):
        raise ValueError("checkpoint expert shard hash mismatch: tool")

    monkeypatch.setattr(checkpoint_artifacts, "load_checkpoint_artifacts", _tampering_load)
    r = lp.preflight_recovery(cfg, root)
    assert r["status"] == "fail"
    assert "round-trip raised" in r["reason"]


# ---- clean-genesis ----------------------------------------------------------

def test_clean_genesis_pass_real_config(cfg, root):
    r = lp.preflight_clean_genesis(cfg, root)
    assert r["status"] == "pass", r
    assert r["lineage"]["borrowed_weights"] is False
    assert "identical state_dict" in r["dynamic_proof"]


def test_clean_genesis_fail_closed_borrowed_weights(cfg, root):
    tainted = copy.deepcopy(cfg)
    tainted["lineage"]["borrowed_weights"] = True
    r = lp.preflight_clean_genesis(tainted, root)
    assert r["status"] == "fail"
    assert "borrowed_weights" in r["reason"]


def test_clean_genesis_fail_closed_non_random_init(cfg, root):
    tainted = copy.deepcopy(cfg)
    tainted["lineage"]["initialization"] = "checkpoint-restore"
    r = lp.preflight_clean_genesis(tainted, root)
    assert r["status"] == "fail"
    assert "initialization" in r["reason"]


def test_clean_genesis_fail_closed_parent_checkpoint_set(cfg, root):
    tainted = copy.deepcopy(cfg)
    tainted["lineage"]["parent_checkpoint"] = "receipts/ember-restart-3b/some-prior-run"
    r = lp.preflight_clean_genesis(tainted, root)
    assert r["status"] == "fail"
    assert "parent_checkpoint" in r["reason"]


def test_clean_genesis_fail_closed_missing_lineage(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["lineage"]
    r = lp.preflight_clean_genesis(broken, root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()


def test_clean_genesis_fail_closed_borrowed_loading_in_source(cfg, root, tmp_path, monkeypatch):
    # A model.py whose UnifiedDecoder body references a borrowed-weight load
    # call must fail closed even if the config lineage block is clean.
    fake_root = tmp_path
    fake_tools = fake_root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
    fake_tools.mkdir(parents=True)
    (fake_tools / "model.py").write_text(
        "class UnifiedDecoder:\n    def __init__(self):\n        self.load_state_dict({})\n",
        encoding="utf-8",
    )
    r = lp.preflight_clean_genesis(cfg, fake_root)
    assert r["status"] == "fail"
    assert "load_state_dict" in r["reason"]


# ---- identity-manifest (cond3 GAP-3) ---------------------------------------
# The launch path must round-trip the declared model/experiment identity
# manifest through the REAL cond3 validator (validate_identity.validate_manifest)
# and cross-check its architecture/tokenizer/corpus hashes against the actual
# on-disk launch inputs -- fail-closed on absent/mismatched identity.

def test_identity_manifest_pass_real_config_corpus_artifact_joined(cfg, root):
    # cond3 corpus-join cure: the real manifest's data.corpus_id and the real
    # config's expected_input_artifact_id both now name the same admitted
    # executable input, "owned-four-domain-production-rung-v1" -- the
    # production_rung.py ARTIFACT_ID and input-identity.json artifact_id --
    # never the legacy "owned-pretrain-v1" family label, which carried no
    # top-level artifact_id/data_class/receipt authority of its own. The
    # preflight must PASS on the unmodified real config/manifest, with no
    # copy or field substitution required to reach agreement.
    assert cfg["training"]["expected_input_artifact_id"] == "owned-four-domain-production-rung-v1"
    r = lp.preflight_identity_manifest(cfg, root)
    assert r["status"] == "pass", r
    assert r["corpus_sha256"] == "26b4c4fbc1fe89de84726578e644019e9c901c06df2b97f0031969b88abe31f1"


def test_identity_manifest_pass_when_corpus_and_artifact_ids_aligned(cfg, root):
    # The intended path (C1): when the two identifiers agree, the preflight
    # passes and carries forward the closed digests over the real
    # architecture/tokenizer/corpus/stream-receipt bytes -- everything
    # named_launch_command needs to emit a resolved (non-placeholder) command.
    aligned = copy.deepcopy(cfg)
    aligned["training"]["expected_input_artifact_id"] = "owned-four-domain-production-rung-v1"
    r = lp.preflight_identity_manifest(aligned, root)
    assert r["status"] == "pass", r
    assert r["disposition"] == "OWNED_CANDIDATE"
    assert len(r["architecture_sha256"]) == 64
    assert len(r["tokenizer_sha256"]) == 64
    assert len(r["corpus_sha256"]) == 64
    assert len(r["stream_receipt_sha256"]) == 64
    assert r["stream_receipt_path"] == aligned["training"]["stream_receipt"]


def test_identity_manifest_fail_closed_corpus_artifact_id_drift(cfg, root):
    # The negative case the cure's check exists for: if the two identifiers
    # DID disagree, the preflight must fail closed and name both values --
    # never silently pass, and never silently prefer one over the other.
    drifted = copy.deepcopy(cfg)
    drifted["training"]["expected_input_artifact_id"] = "owned-pretrain-v1"
    r = lp.preflight_identity_manifest(drifted, root)
    assert r["status"] == "fail", r
    assert "does not match" in r["reason"]
    assert "owned-pretrain-v1" in r["reason"]
    assert "owned-four-domain-production-rung-v1" in r["reason"]


def test_identity_manifest_fail_closed_missing_config_field(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["training"]["identity_manifest"]
    r = lp.preflight_identity_manifest(broken, root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()


def test_identity_manifest_fail_closed_absent_manifest(cfg, root, tmp_path):
    # A repo root with no manifest file at the declared path -> absent identity,
    # never a silent pass.
    empty_root = tmp_path
    r = lp.preflight_identity_manifest(cfg, empty_root)
    assert r["status"] == "fail"
    assert "absent" in r["reason"].lower()


def test_identity_manifest_fail_closed_schema_invalid(cfg, root, tmp_path):
    # A manifest that fails validate_identity's own schema/structural checks
    # (missing required top-level keys) must fail closed, never silently pass.
    manifest_rel = cfg["training"]["identity_manifest"]
    real_manifest = (root / manifest_rel).read_text(encoding="utf-8")
    broken_payload = json.loads(real_manifest)
    del broken_payload["provenance"]
    dest = tmp_path / manifest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(broken_payload), encoding="utf-8")
    # Mirror the real architecture/tokenizer/corpus files so we reach the
    # validator call (not an earlier absent-file fail).
    import shutil
    for rel in (
        "configs/ember-restart-3b.json",
        resolve_repository_authority(root, "tokenizer").relative_path,
        f"data/ember-restart-3b/{broken_payload['data']['corpus_id']}.json",
    ):
        src = root / rel
        d = tmp_path / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d)
    r = lp.preflight_identity_manifest(cfg, tmp_path)
    assert r["status"] == "fail"
    assert "failed validation" in r["reason"]


def test_identity_manifest_fail_closed_architecture_hash_drift(cfg, root, tmp_path):
    # Tamper the declared architecture.sha256 so it no longer matches the real
    # config bytes -> must fail closed as a drift/mismatch, never silently pass.
    manifest_rel = cfg["training"]["identity_manifest"]
    payload = json.loads((root / manifest_rel).read_text(encoding="utf-8"))
    payload["architecture"]["sha256"] = "0" * 64
    dest = tmp_path / manifest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload), encoding="utf-8")
    import shutil
    for rel in (
        "configs/ember-restart-3b.json",
        resolve_repository_authority(root, "tokenizer").relative_path,
        f"data/ember-restart-3b/{payload['data']['corpus_id']}.json",
    ):
        src = root / rel
        d = tmp_path / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d)
    r = lp.preflight_identity_manifest(cfg, tmp_path)
    assert r["status"] == "fail"
    assert "architecture.sha256 drift" in r["reason"]


def test_identity_manifest_fail_closed_tokenizer_hash_drift(cfg, root, tmp_path):
    manifest_rel = cfg["training"]["identity_manifest"]
    payload = json.loads((root / manifest_rel).read_text(encoding="utf-8"))
    payload["tokenizer"]["sha256"] = "1" * 64
    dest = tmp_path / manifest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload), encoding="utf-8")
    import shutil
    for rel in (
        "configs/ember-restart-3b.json",
        resolve_repository_authority(root, "tokenizer").relative_path,
        f"data/ember-restart-3b/{payload['data']['corpus_id']}.json",
    ):
        src = root / rel
        d = tmp_path / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d)
    r = lp.preflight_identity_manifest(cfg, tmp_path)
    assert r["status"] == "fail"
    assert "tokenizer.sha256 drift" in r["reason"]


def test_identity_manifest_fail_closed_owned_admitted_at_pretrain_launch(cfg, root, tmp_path):
    # OWNED_ADMITTED would claim a checkpoint has been admitted -- impossible
    # at a clean-genesis pre-training launch. Must fail closed.
    manifest_rel = cfg["training"]["identity_manifest"]
    payload = json.loads((root / manifest_rel).read_text(encoding="utf-8"))
    payload["identity"]["disposition"] = "OWNED_ADMITTED"
    dest = tmp_path / manifest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload), encoding="utf-8")
    import shutil
    for rel in (
        "configs/ember-restart-3b.json",
        resolve_repository_authority(root, "tokenizer").relative_path,
        f"data/ember-restart-3b/{payload['data']['corpus_id']}.json",
    ):
        src = root / rel
        d = tmp_path / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d)
    r = lp.preflight_identity_manifest(cfg, tmp_path)
    assert r["status"] == "fail"


# ---- stream-receipt binding (#1091 B1-B5) -----------------------------------
# The identity preflight must bind to the ACTUAL stream receipt this launch
# will consume (config.training.stream_receipt), not merely to a sibling
# corpus-description artifact -- fail-closed on every skip path.

def test_stream_receipt_fail_closed_missing_config_field(cfg, root):
    broken = copy.deepcopy(cfg)
    broken["training"]["expected_input_artifact_id"] = "owned-four-domain-production-rung-v1"  # align, isolate this field
    del broken["training"]["stream_receipt"]
    r = lp.preflight_identity_manifest(broken, root)
    assert r["status"] == "fail"
    assert "stream-receipt binding" in r["reason"]


def test_stream_receipt_fail_closed_absent_file(cfg, root):
    aligned = copy.deepcopy(cfg)
    aligned["training"]["expected_input_artifact_id"] = "owned-four-domain-production-rung-v1"
    aligned["training"]["stream_receipt"] = "receipts/does-not-exist.json"
    r = lp.preflight_identity_manifest(aligned, root)
    assert r["status"] == "fail"
    assert "declared stream receipt is absent" in r["reason"]


def test_stream_receipt_fail_closed_wrong_ticket(cfg, root):
    aligned = copy.deepcopy(cfg)
    aligned["training"]["expected_input_artifact_id"] = "owned-four-domain-production-rung-v1"
    # stream_receipt must resolve under the real repo root (preflight_storage-
    # style paths are always root-relative), so write the bad fixture there
    # rather than under pytest's tmp_path, and always clean it up after.
    bad_rel = "receipts/ember-01-launch-packet/_test-bad-ticket-receipt.json"
    bad_path = root / bad_rel
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text(json.dumps({"ticket": "SOMETHING-ELSE"}), encoding="utf-8")
    try:
        aligned["training"]["stream_receipt"] = bad_rel
        r = lp.preflight_identity_manifest(aligned, root)
        assert r["status"] == "fail"
        assert "does not declare TOKEN-SHARDS-V0" in r["reason"]
    finally:
        bad_path.unlink()


def test_stream_receipt_fail_closed_unreadable_json(cfg, root, tmp_path):
    aligned = copy.deepcopy(cfg)
    aligned["training"]["expected_input_artifact_id"] = "owned-four-domain-production-rung-v1"
    bad_rel = "receipts/ember-01-launch-packet/_test-unreadable-receipt.json"
    bad_path = root / bad_rel
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{not valid json", encoding="utf-8")
    try:
        aligned["training"]["stream_receipt"] = bad_rel
        r = lp.preflight_identity_manifest(aligned, root)
        assert r["status"] == "fail"
        assert "unreadable" in r["reason"]
    finally:
        bad_path.unlink()


def test_stream_receipt_sha256_matches_real_bytes(cfg, root):
    aligned = copy.deepcopy(cfg)
    aligned["training"]["expected_input_artifact_id"] = "owned-four-domain-production-rung-v1"
    r = lp.preflight_identity_manifest(aligned, root)
    assert r["status"] == "pass", r
    import hashlib
    real_bytes = (root / aligned["training"]["stream_receipt"]).read_bytes()
    assert r["stream_receipt_sha256"] == hashlib.sha256(real_bytes).hexdigest()


# ---- overall exit ------------------------------------------------------------

def test_all_six_implemented_no_deferred(cfg, root):
    assert lp.DEFERRED == []
    assert len(lp.IMPLEMENTED) == 6


def test_run_exits_zero_real_config_corpus_artifact_id_joined(root):
    # cond3 corpus-join cure: the real manifest and the real config now name
    # the same admitted executable input artifact, so the unmodified real
    # config reaches rc == 0 through the real run()/CLI entry point -- the
    # #1091 C6 disagreement this test used to pin as expected is resolved.
    rc = lp.run(_CONFIG_PATH)
    assert rc == 0


def test_run_exits_nonzero_when_corpus_and_artifact_ids_drift(root, tmp_path, monkeypatch):
    # The negative case: point run() at a config that is a byte-for-byte copy
    # of the real one except the one field forced back to the legacy,
    # non-admitted artifact id -- the packet must refuse and name exactly the
    # identity-manifest preflight, never silently pass.
    real_bytes = _CONFIG_PATH.read_text(encoding="utf-8")
    real_cfg = json.loads(real_bytes)
    real_cfg["training"]["expected_input_artifact_id"] = "owned-pretrain-v1"
    drifted_config_path = _CONFIG_PATH.parent / "_test-drifted-ember-restart-3b.json"
    drifted_config_path.write_text(json.dumps(real_cfg), encoding="utf-8")
    try:
        rc = lp.run(drifted_config_path)
    finally:
        drifted_config_path.unlink()
    assert rc == 1


def test_named_command_is_truthful_no_placeholder(cfg, root):
    aligned = copy.deepcopy(cfg)
    aligned["training"]["expected_input_artifact_id"] = "owned-four-domain-production-rung-v1"
    identity = lp.preflight_identity_manifest(aligned, root)
    assert identity["status"] == "pass", identity
    cmd = lp.named_launch_command(aligned, identity)
    assert "run_vertical_slice.py" in cmd["command"]
    assert "semantic" in cmd["command"]
    assert "run_semantic" in cmd["library_entrypoint"]
    # The historical sub-3B trainer is EXECUTION-DENIED (historical_only);
    # the named command must never point at it, and the note must say why.
    assert "timeshare_pretrain.py" not in cmd["command"]
    assert "historical_only" in cmd["note"]
    # #1091 B2: --receipt and the three --expected-*-sha256 arguments are
    # RESOLVED real values, never the old literal <angle-bracket> placeholders.
    assert "<manifest-bound-stream-receipt.json>" not in cmd["command"]
    assert f"--receipt {identity['stream_receipt_path']}" in cmd["command"]
    assert f"--expected-receipt-sha256 {identity['stream_receipt_sha256']}" in cmd["command"]
    assert f"--expected-tokenizer-sha256 {identity['tokenizer_sha256']}" in cmd["command"]
    assert f"--expected-architecture-sha256 {identity['architecture_sha256']}" in cmd["command"]


# ---- cond3 unresolved identity (GAP-3) --------------------------------------
# checkpoint.byte_sha256 and evaluation.subject_checkpoint_sha256 both widened to
# sha256OrUnresolved. The mismatch check between them was a raw `!=`, so on a
# clean-genesis pre-birth manifest it compared two unresolved OBJECTS -- which
# differ exactly when their `reason` prose differs. The verdict was a function of
# an English sentence: identical reasons passed, honest per-field reasons failed.

def _identity_manifest():
    import json as _json
    from pathlib import Path as _Path
    root = _Path(__file__).resolve().parents[3]
    return _json.loads(
        (root / "data/ember-restart-3b/cond3-identity-manifest.json").read_text(encoding="utf-8")
    )


def test_unresolved_pair_is_not_a_subject_checkpoint_mismatch():
    import copy as _copy, sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / "scripts"))
    from ember_01_identity.validate_identity import validate_manifest

    payload = _identity_manifest()
    # The two reasons are deliberately DIFFERENT -- an honest manifest states why
    # each field is unresolved, and equality of prose must not decide identity.
    assert payload["checkpoint"]["byte_sha256"]["reason"] != \
        payload["evaluation"]["subject_checkpoint_sha256"]["reason"]
    validate_manifest(_copy.deepcopy(payload))  # raises on any finding


def test_resolved_mismatch_is_still_caught():
    import copy as _copy, pytest as _pytest, sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / "scripts"))
    from ember_01_identity.validate_identity import validate_manifest, IdentityValidationError

    payload = _copy.deepcopy(_identity_manifest())
    payload["checkpoint"]["byte_sha256"] = "11" * 32
    payload["evaluation"]["subject_checkpoint_sha256"] = "22" * 32
    payload["unresolved"] = [
        p for p in payload["unresolved"]
        if p not in ("checkpoint.byte_sha256", "evaluation.subject_checkpoint_sha256")
    ]
    with _pytest.raises(IdentityValidationError) as excinfo:
        validate_manifest(payload)
    codes = {f.get("code") for f in excinfo.value.findings}
    assert "evaluation.subject_checkpoint_mismatch" in codes


def test_require_resolved_rejects_every_unresolved_identity_path():
    import copy as _copy, pytest as _pytest, sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / "scripts"))
    from ember_01_identity.validate_identity import validate_manifest, IdentityValidationError

    with _pytest.raises(IdentityValidationError) as excinfo:
        validate_manifest(_copy.deepcopy(_identity_manifest()), require_resolved=True)
    paths = {f.get("detail") for f in excinfo.value.findings if f.get("code") == "field.unresolved"}
    for required in (
        "checkpoint.byte_sha256",
        "checkpoint.tensors[0].sha256",
        "evaluation.subject_checkpoint_sha256",
    ):
        assert required in paths, required
