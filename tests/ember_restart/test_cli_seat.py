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
from seat_identity_bridge import resolve_checkpoint_byte_identity  # noqa: E402

RESOLVER = REPO_ROOT / "scripts" / "ember_restart" / "cli_seat.py"
CERT_FIXTURE_PATH = (
    REPO_ROOT / "tools" / "ember-cli" / "src" / "commands" / "__fixtures__" / "model-identity" / "manifest.json"
)


def _write_cert_manifest(tmp_path: Path, cert: dict, name: str = "cert-manifest.json") -> tuple[Path, str]:
    path = tmp_path / name
    data = json.dumps(cert, indent=2).encode("utf-8")
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def _matching_cert(manifest: dict, tmp_path: Path) -> dict:
    """A real cert manifest whose identity-bearing hash fields exactly equal
    THIS generated run manifest's own (real, already-computed) values --
    reusing the checked-in model-identity fixture (known to pass
    validate_identity.py per scripts/ember_restart/test_seat_identity_bridge.py)
    and overriding only the overlapping hashes. No hash is invented: every
    value copied in here was already produced by the admission fixture
    builder or by hashing real fixture bytes.

    checkpoint.byte_sha256 is set to the CANONICAL CHECKPOINT-BYTE identity
    (resolve_checkpoint_byte_identity over the real checkpoint index +
    shards this manifest references) -- NOT manifest["checkpoint"]["sha256"]
    (the checkpoint INDEX JSON's own self-consistency digest). Copying the
    index digest in here is the exact defect
    state/failure-classes/semantic-validation-without-bytes-2026-07-25.md
    names: it made every historical version of this fixture pass while
    proving nothing about checkpoint bytes. See
    test_shard_tamper_with_unchanged_index_json_refused_through_production_path
    for the reproduction of that defect against a cert built the old way.
    """
    cert = json.loads(CERT_FIXTURE_PATH.read_text(encoding="utf-8"))
    checkpoint_index_path = tmp_path / manifest["checkpoint"]["manifest_path"]
    checkpoint_sha256, errors = resolve_checkpoint_byte_identity(checkpoint_index_path, root=tmp_path)
    assert not errors, errors
    cert["checkpoint"]["byte_sha256"] = checkpoint_sha256
    cert["architecture"]["sha256"] = manifest["architecture"]["model_config"]["sha256"]
    cert["tokenizer"]["sha256"] = manifest["tokenizer"]["sha256"]
    cert["evaluation"]["subject_checkpoint_sha256"] = checkpoint_sha256
    return cert


def _resolve(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            str(manifest),
            "--trusted-verifier-registry",
            str(manifest.parent / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_resolver_derives_owned_identity_from_cert_bridge_but_refuses_unadmitted_cert(tmp_path: Path):
    """cond3 wiring (state/specs/cond3-seat-bridge-spec.md): the resolver no
    longer trusts the run manifest's own checkpoint/model-config/tokenizer
    hashes as an independent identity authority (goal line 95) -- it derives
    them from the referenced cert manifest via seat_identity_bridge, fail-
    closed. This replaces the old GREEN happy-path test, which asserted
    valid:True purely from the run manifest's own fields with no cert
    involved at all -- exactly the independent-derivation this bridge removes.

    This test proves the cross-check reaches production and passes (bridge
    Step 1-5 GREEN) using a REAL matching cert -- the checked-in
    model-identity fixture with its overlapping hashes overridden to the
    real, already-computed run-manifest values (no invented hashes) -- then
    documents a genuine, currently-open upstream gap: validate_identity.py's
    OWNED_ADMITTED admission checks (evaluation receipt / checkpoint bytes /
    artifact bundle) unconditionally require --receipt-bundle/--checkpoint/
    --artifact-bundle CLI flags that NEITHER model.ts's _resolveModelIdentity
    (tools/ember-cli/src/commands/model.ts:113, passes at most --checkpoint)
    NOR seat_identity_bridge.derive_seat_identity (passes only the bare
    manifest path) ever supply. No cert manifest can therefore currently
    reach identity.disposition == OWNED_ADMITTED through this bridge, so the
    only reachable passing disposition is OWNED_CANDIDATE, and
    require_admitted_seat correctly REFUSES it (negative #6: never serve or
    count a candidate as admitted). This is a real, disclosed gap in the
    admission plumbing shared by model.ts and the bridge -- not a defect
    introduced by this wiring -- and is out of scope for the production-
    wiring leg (tracked separately from Artifact B / consumer replay).
    """
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cert = _matching_cert(manifest, tmp_path)
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
        "not OWNED_ADMITTED+selected" in error for error in payload["errors"]
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
    result = cli_seat.resolve_owned_seat(manifest_path, tmp_path / "trusted-verifiers.json")

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


def test_axis6_mismatched_cert_field_refused_through_production_path(tmp_path: Path):
    """A seat whose identity fields disagree with the referenced cert
    manifest is REFUSED through the REAL production path (subprocess, no
    mocking) -- proving the new cross-check is load-bearing there, not
    merely present in the bridge module. The run manifest here is internally
    self-consistent (would have passed the OLD resolver unmodified); only the
    cert cross-check this wiring introduces disagrees, isolating exactly the
    new behavior."""
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cert = _matching_cert(manifest, tmp_path)
    # Deliberately mismatch ONE overlapping field: the cert's architecture
    # hash disagrees with the run manifest's own (real, self-consistent)
    # model_config sha256 -- swapped for the tokenizer sha256, another real
    # value already present in the manifest, so nothing is invented.
    cert["architecture"]["sha256"] = manifest["tokenizer"]["sha256"]
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
        "does not equal cert-derived value" in error for error in payload["errors"]
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
