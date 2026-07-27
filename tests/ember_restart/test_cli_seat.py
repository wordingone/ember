# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from test_admission import test_owned_admission_binds_sufficient_pretraining_evals_and_cli
from test_contract import REPO_ROOT, _write_json

# cond3 seat-chain bridge wiring (state/specs/cond3-seat-bridge-spec.md): the
# in-process axis-6 production-reach test imports the resolver module
# directly (not just via subprocess) so it can spy on the exact call the
# PRODUCTION default path makes into seat_identity_bridge.derive_seat_identity.
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ember_restart"))
import cli_seat  # noqa: E402  (path must be inserted first)

RESOLVER = REPO_ROOT / "scripts" / "ember_restart" / "cli_seat.py"
CERT_FIXTURE_PATH = (
    REPO_ROOT / "tools" / "ember-cli" / "src" / "commands" / "__fixtures__" / "model-identity" / "manifest.json"
)


def _write_cert_manifest(tmp_path: Path, cert: dict, name: str = "cert-manifest.json") -> tuple[Path, str]:
    path = tmp_path / name
    data = json.dumps(cert, indent=2).encode("utf-8")
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


# NOTE (rework 2026-07-25): an earlier draft of this file carried
# _matching_cert / _single_shard_admission_manifest helpers meant to reach a
# GREEN (or a cert-cross-check REFUSE) through the real cli_seat.py
# production path with a single-shard checkpoint. They were removed:
# contract.py's own _verify_architecture unconditionally requires exactly
# the vision/audio/reasoning/tool expert banks, each bound to its own
# checkpoint shard (contract.py: "architecture.expert_banks: requires
# exactly vision/audio/reasoning/tool banks") -- so every manifest that can
# pass Stage 1 (OWNED_ADMITTED) admission is structurally multi-shard, and
# this rework's bridge refuses every multi-shard checkpoint outright (the
# schema/contract gap -- see
# test_resolver_derives_owned_identity_from_cert_bridge_but_refuses_
# unadmitted_cert below). No single-shard manifest can reach OWNED_ADMITTED
# through the real production path at all under the current schema; that is
# the ruling-request finding, not a gap in test coverage. The cert-content
# / OWNED_ADMITTED-gap / cert-cross-check behaviors these helpers targeted
# are verified directly against the bridge (bypassing contract.py Stage 1,
# which is legitimate there since the bridge is unit-tested independently)
# in scripts/ember_restart/test_seat_identity_bridge.py.


def _approval(manifest: Path) -> Path:
    registry = manifest.parent / "trusted-verifiers.json"
    approval = manifest.parent / "trusted-registry-approval.json"
    _write_json(
        approval,
        {
            "schema_version": "ember-trusted-verifier-registry-approval-v1",
            "trusted_verifier_registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
        },
    )
    return approval


def _resolve(
    manifest: Path,
    approval: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    approval = approval or _approval(manifest)
    return subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            str(manifest),
            "--trusted-verifier-registry",
            str(manifest.parent / "trusted-verifiers.json"),
            "--trusted-verifier-registry-approval",
            str(approval),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_main_temporarily_accepts_internal_server_call_without_approval(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    observed: list[tuple[Path, Path, Path | None]] = []

    def resolver(manifest: Path, registry: Path, approval: Path | None):
        observed.append((manifest, registry, approval))
        return {"valid": False, "seat": None, "errors": ["transition probe"]}

    monkeypatch.setattr(cli_seat, "resolve_owned_seat", resolver)
    result = cli_seat.main([
        str(tmp_path / "run.json"),
        "--trusted-verifier-registry", str(tmp_path / "registry.json"),
    ])
    assert result == 1
    assert observed == [(tmp_path / "run.json", tmp_path / "registry.json", None)]
    assert json.loads(capsys.readouterr().out)["errors"] == ["transition probe"]


def test_resolver_derives_owned_identity_from_cert_bridge_but_refuses_unadmitted_cert(tmp_path: Path):
    """cond3 wiring (state/specs/cond3-seat-bridge-spec.md): the resolver no
    longer trusts the run manifest's own checkpoint/model-config/tokenizer
    hashes as an independent identity authority (goal line 95) -- it derives
    them from the referenced cert manifest via seat_identity_bridge, fail-
    closed.

    REWORK FINDING (2026-07-25, supersedes this test's pre-rework body):
    the STANDARD production admission fixture
    (test_owned_admission_binds_sufficient_pretraining_evals_and_cli) is
    genuinely 5-shard (1 model shard + 4 mandatory expert-bank shards --
    contract.py._verify_architecture requires exactly the
    vision/audio/reasoning/tool banks unconditionally, each bound to its own
    checkpoint shard). Under the corrected bridge this is refused at
    checkpoint resolution (Step 1.5, schema/contract gap) BEFORE the cert is
    ever cross-checked -- so the downstream "OWNED_ADMITTED gap" this test
    used to document is no longer independently reachable through the real
    production path at all: contract.py's own architecture contract makes
    every manifest that can pass Stage 1 admission multi-shard, and the
    corrected bridge refuses every multi-shard checkpoint. That downstream
    OWNED_ADMITTED gap is still real and still verified directly against the
    bridge in scripts/ember_restart/test_seat_identity_bridge.py (which
    calls derive_seat_identity directly, bypassing contract.py Stage 1) --
    it is simply no longer observable end-to-end through cli_seat.py for
    any manifest shaped the way real production data is shaped. See the
    rework report's ruling-request section for the schema-gap writeup this
    implies.

    The cert content is irrelevant here (checkpoint resolution refuses
    before the cert is cross-checked against anything) -- the checked-in
    model-identity fixture is used unmodified.
    """
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cert = json.loads(CERT_FIXTURE_PATH.read_text(encoding="utf-8"))
    cert_path, digest = _write_cert_manifest(tmp_path, cert)
    manifest["cert_manifest_path"] = cert_path.name
    manifest["cert_manifest_digest"] = digest
    _write_json(manifest_path, manifest)

    result = _resolve(manifest_path)
    assert result.returncode != 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["seat"] is None
    assert any(
        "checkpoint index names 5 shards" in error and "schema/contract gap" in error
        for error in payload["errors"]
    ), payload["errors"]


def test_axis6_production_path_reaches_seat_identity_bridge(tmp_path: Path, monkeypatch):
    """Consumer-graph DEFAULT path (7-axis map, axis 6): resolve_owned_seat
    (the production entrypoint owned-seat-loader.ts spawns) must REACH
    seat_identity_bridge.derive_seat_identity -- a call-count/observable-
    effect assertion against the real function, not a unit test of the
    bridge module alone. derive_seat_identity is replaced with a spy so this
    also proves WHAT it is called with: the manifest's own model-config/
    tokenizer sha256 and the resolved checkpoint-manifest (index) path are
    handed through as bridge INPUT (cross-check material / checkpoint-byte
    resolution input), never consumed directly as final identity truth.

    checkpointSha256 (manifest["checkpoint"]["sha256"], the checkpoint INDEX
    JSON's own self-consistency digest) is asserted ABSENT from the bridge
    call -- passing it as a checkpoint-byte cross-check is the exact defect
    state/failure-classes/semantic-validation-without-bytes-2026-07-25.md
    names (field reinterpretation: the index's digest reported as if it
    named the checkpoint bytes). The bridge derives the real checkpoint-byte
    identity itself from checkpointPath (Step 5, resolve_checkpoint_byte_identity).
    """
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    calls: list[tuple[dict, Path]] = []

    def _spy(seat_config, *, repo_root):
        calls.append((dict(seat_config), repo_root))
        return {"valid": False, "seat": None, "errors": ["spy: refused by design"]}

    monkeypatch.setattr(cli_seat, "derive_seat_identity", _spy)
    result = cli_seat.resolve_owned_seat(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        _approval(manifest_path),
    )

    assert len(calls) == 1, "production default path did not reach derive_seat_identity exactly once"
    seat_config, repo_root = calls[0]
    assert "checkpointSha256" not in seat_config, (
        "the checkpoint INDEX digest must never be passed as checkpoint-byte "
        "identity material -- resolve_checkpoint_byte_identity derives it"
    )
    assert seat_config["modelConfigSha256"] == manifest["architecture"]["model_config"]["sha256"]
    assert seat_config["tokenizerSha256"] == manifest["tokenizer"]["sha256"]
    assert seat_config["checkpointPath"] == str(
        (manifest_path.resolve().parent / manifest["checkpoint"]["manifest_path"]).resolve()
    )
    assert repo_root == cli_seat.REPO_ROOT
    # The bridge's REFUSE propagates as the resolver's own REFUSE -- proving
    # there is no fallback to the old independent-derivation path.
    assert result == {"valid": False, "seat": None, "errors": ["spy: refused by design"]}


def test_missing_shard_refused_through_production_path_naming_the_path(tmp_path: Path):
    """Acceptance item 2 (cond3-1038-rework-2026-07-25): a checkpoint shard
    a manifest names but that is not actually present on disk is REFUSED
    through the REAL production path, naming the missing path -- not a
    silent pass, not a generic error.

    This is caught by contract.py's OWN Stage-1 file-existence check
    (_verify_checkpoint -> _verify_file), before the manifest can even reach
    OWNED_ADMITTED / the bridge -- which is correct and sufficient for this
    acceptance item (it does not require a bridge-owned reason, unlike item
    1). The bridge's OWN missing-shard handling (a single-shard index whose
    one shard is absent) is separately covered directly against
    derive_seat_identity in
    scripts/ember_restart/test_seat_identity_bridge.py::
    test_missing_shard_refused_naming_the_path -- contract.py's mandatory
    4-expert-bank architecture requirement (contract.py's
    _verify_architecture, "requires exactly vision/audio/reasoning/tool
    banks") means every manifest that can pass Stage 1 admission is
    multi-shard, so the bridge's own single-shard missing-file path is never
    reachable through cli_seat.py for a real manifest -- the same schema
    gap test_resolver_derives_owned_identity_from_cert_bridge_but_refuses_
    unadmitted_cert documents.
    """
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint_index_path = tmp_path / manifest["checkpoint"]["manifest_path"]
    index = json.loads(checkpoint_index_path.read_text(encoding="utf-8"))
    missing_shard_path = tmp_path / index["shards"][0]["path"]
    missing_shard_path.unlink()

    result = _resolve(manifest_path)
    assert result.returncode != 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["seat"] is None
    assert any(
        "checkpoint.shards[0]" in error and "does not exist" in error
        for error in payload["errors"]
    ), payload["errors"]


def test_resolver_rejects_candidate_and_tampered_serving_bytes(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "CHECKPOINT_CANDIDATE"
    _write_json(manifest_path, manifest)
    candidate = _resolve(manifest_path)
    assert candidate.returncode != 0
    assert json.loads(candidate.stdout)["seat"] is None

    manifest["stage"] = "OWNED_ADMITTED"
    serving_path = tmp_path / manifest["cli"]["serving_manifest_path"]
    serving_path.write_text("{}", encoding="utf-8")
    _write_json(manifest_path, manifest)
    tampered = _resolve(manifest_path)
    assert tampered.returncode != 0
    assert "content hash mismatch" in tampered.stdout


def test_shard_tamper_with_unchanged_index_json_refused_through_production_path(tmp_path: Path):
    """THE discriminating test for the cond3-1038 defect class
    (state/failure-classes/semantic-validation-without-bytes-2026-07-25.md):
    leave the checkpoint-manifest INDEX JSON byte-identical and change the
    artifact it names (one shard's bytes) -- the PRODUCTION path must fail
    closed.

    The cert here is built the OLD (defective) way on purpose:
    checkpoint.byte_sha256 is set to manifest["checkpoint"]["sha256"], the
    checkpoint INDEX JSON's own self-consistency digest -- exactly what
    tests/test_cli_seat.py:42-46 did before this cure (and what PR #1038 was
    rejected for at exact head 50f575a). Reproduced per the reject: this
    value is unaffected by which shard bytes are on disk, so BEFORE the cure
    the production resolver accepts a checkpoint whose real bytes were
    swapped out from under it, because it only ever re-hashed the
    (unchanged) index file and never touched a shard.
    """
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    cert = json.loads(CERT_FIXTURE_PATH.read_text(encoding="utf-8"))
    checkpoint_index_digest = manifest["checkpoint"]["sha256"]
    cert["checkpoint"]["byte_sha256"] = checkpoint_index_digest
    cert["architecture"]["sha256"] = manifest["architecture"]["model_config"]["sha256"]
    cert["tokenizer"]["sha256"] = manifest["tokenizer"]["sha256"]
    cert["evaluation"]["subject_checkpoint_sha256"] = checkpoint_index_digest
    cert_path, digest = _write_cert_manifest(tmp_path, cert)
    manifest["cert_manifest_path"] = cert_path.name
    manifest["cert_manifest_digest"] = digest
    _write_json(manifest_path, manifest)

    # Tamper ONE shard's actual bytes. The checkpoint-manifest.json INDEX
    # (checkpoint.manifest_path) stays byte-identical -- only a shard it
    # references changes.
    checkpoint_index_path = tmp_path / manifest["checkpoint"]["manifest_path"]
    index_bytes_before = checkpoint_index_path.read_bytes()
    index_payload = json.loads(index_bytes_before)
    assert index_payload["shards"], "fixture must carry at least one shard"
    tampered_shard_path = tmp_path / index_payload["shards"][0]["path"]
    tampered_shard_path.write_bytes(b"TAMPERED-SHARD-BYTES-not-the-certified-checkpoint")
    assert checkpoint_index_path.read_bytes() == index_bytes_before, (
        "the index JSON must stay byte-identical -- only the shard changed"
    )

    result = _resolve(manifest_path)
    assert result.returncode != 0, (
        "production seat resolver served a checkpoint with a tampered shard "
        f"while its index JSON stayed unchanged: {result.stdout + result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["seat"] is None


def test_resolver_requires_external_registry_approval(tmp_path: Path, monkeypatch):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = tmp_path / "trusted-verifiers.json"
    approval = _approval(manifest_path)

    def _admitted_bridge(_seat_config, *, repo_root):
        assert repo_root == cli_seat.REPO_ROOT
        return {
            "valid": True,
            "seat": {
                "admitted": True,
                "checkpointSha256": "a" * 64,
                "modelConfigSha256": manifest["architecture"]["model_config"]["sha256"],
                "tokenizerSha256": manifest["tokenizer"]["sha256"],
            },
            "errors": [],
        }

    monkeypatch.setattr(cli_seat, "derive_seat_identity", _admitted_bridge)
    accepted = cli_seat.resolve_owned_seat(manifest_path, registry, approval)
    assert accepted["valid"] is True

    replaced = json.loads(registry.read_text(encoding="utf-8"))
    replaced["verifiers"][0]["criterion_ids"] = ["candidate-replacement"]
    _write_json(registry, replaced)
    manifest["trusted_verifier_registry_sha256"] = hashlib.sha256(registry.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)

    rejected = cli_seat.resolve_owned_seat(manifest_path, registry, approval)
    assert rejected["valid"] is False
    assert any("external authority hash mismatch" in error for error in rejected["errors"])
