# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Proves the bytes /designate selects (the admitted candidate's
restart_run_manifest role) are a genuine, resolvable OWNED_ADMITTED seat --
not that /designate's own copy/receipt logic is correct (that is
tools/ember-cli/src/commands/designate-fixture.test.ts's job, driven against
the real admit.ts verifier), but that what /designate is handed by a real
/admit run is authentic, non-corrupted, seat-resolvable content.

Two house-precedented boundaries are reused here rather than re-derived:

1. Candidate PRODUCTION is driven through the real produce_candidate.main()
   with only the identity/restart CONSUMER subprocess calls monkeypatched --
   the exact pattern test_final_path_consumption.py::
   test_consumers_receive_only_final_candidate_paths already established as
   legitimate for testing what happens to a produced candidate, as opposed
   to re-testing candidate producer semantics (#1107's own claim).
2. The restart_run_manifest content itself is the REAL, full house fixture
   (test_admission.py::test_owned_admission_binds_sufficient_pretraining_
   evals_and_cli), and cli_seat.resolve_owned_seat is driven with only
   derive_seat_identity (the cert-cross-check bridge, a materially separate
   concern from candidate selection) monkeypatched -- the exact pattern
   test_cli_seat.py::test_resolver_requires_external_registry_approval
   already established as the boundary for proving resolve_owned_seat
   reaches a real OWNED_ADMITTED accept through the real production path.

What this test does NOT claim: that EMBER_HOME/owned/current.json's
dependency closure is reachable from owned/ in a live deployment. That is a
property of how a real /admit --output-root is chosen relative to owned/,
which is outside /designate's contract (its only product write is
current.json itself). This test instead resolves the manifest from a root
that DOES contain its full dependency closure -- the candidate's own
published directory, which /designate reads FROM to build current.json's
bytes -- proving the selected bytes are legitimately admissible, not that
they remain admissible from an arbitrary later location.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
ADMISSION_ROOT = REPO_ROOT / "scripts" / "ember_admission"
RESTART_ROOT = REPO_ROOT / "src" / "ember" / "governance" / "scripts" / "ember_restart"
sys.path.insert(0, str(ADMISSION_ROOT))
sys.path.insert(0, str(RESTART_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "ember_restart"))

import produce_candidate  # noqa: E402
import cli_seat  # noqa: E402
from test_admission import (  # noqa: E402
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli,
)


REQUIRED_FIXED_ROLES = (
    "artifact_bundle",
    "identity_manifest",
    "receipt_bundle",
    "tensor_hashes",
    "tensor_manifest",
    "identity_trusted_verifier_registry",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _slug(relative_posix: str) -> str:
    return relative_posix.replace("/", "_")


def _build_descriptor_and_roles(workspace: Path) -> list[dict[str, object]]:
    """Walks the real, house-produced OWNED_ADMITTED fixture tree and
    declares every file it contains as an admission role -- the three
    REQUIRED_ROLES the manifest's own fields name specifically
    (restart_run_manifest / checkpoint / restart_model_config /
    restart_trusted_verifier_registry), everything else the manifest
    transitively depends on as restart_dependency:<slug> roles. This is
    mechanical (no semantic understanding of each file is needed): the
    admission producer only needs role+path+sha256 per file, and the
    manifest's own internal relative paths are already self-consistent
    within `workspace` (that is what reaching OWNED_ADMITTED already
    proved) -- admission preserves that relative structure verbatim.
    """
    run_json = workspace / "run.json"
    manifest = json.loads(run_json.read_text(encoding="utf-8"))
    # The house fixture builder serializes these two path fields with
    # str(Path.relative_to(...)), which is OS-native (backslash on
    # Windows) -- normalize to posix here so the lookup below matches the
    # posix-form keys the rglob walk produces (and so descriptor.py's own
    # backslash-forbidding _valid_relative_path would accept them too).
    checkpoint_manifest_rel = manifest["checkpoint"]["manifest_path"].replace("\\", "/")
    model_config_rel = manifest["architecture"]["model_config"]["path"].replace("\\", "/")
    registry_rel = "trusted-verifiers.json"

    fixed = {
        "run.json": "restart_run_manifest",
        checkpoint_manifest_rel: "checkpoint",
        model_config_rel: "restart_model_config",
        registry_rel: "restart_trusted_verifier_registry",
    }

    roles: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for file in sorted(workspace.rglob("*")):
        if not file.is_file():
            continue
        relative = file.relative_to(workspace).as_posix()
        if relative in seen_paths:
            continue
        seen_paths.add(relative)
        role = fixed.get(relative, f"restart_dependency:{_slug(relative)}")
        roles.append(
            {"role": role, "path": relative, "sha256": _sha256_file(file)}
        )

    # The identity-side REQUIRED_ROLES are genuinely out of scope for this
    # test (identity semantic validation is /admit's own already-tested
    # claim, per test_final_path_consumption.py's identical choice to
    # monkeypatch run_identity_consumer) -- trivial, distinct placeholder
    # files satisfy the descriptor's completeness rule without pretending to
    # exercise validate_identity.py's real checks.
    identity_dir = workspace / "identity-side"
    identity_dir.mkdir(parents=True, exist_ok=True)
    for role in REQUIRED_FIXED_ROLES:
        target = identity_dir / f"{role}.json"
        payload = (json.dumps({"role": role}, sort_keys=True) + "\n").encode("utf-8")
        target.write_bytes(payload)
        roles.append(
            {
                "role": role,
                "path": target.relative_to(workspace).as_posix(),
                "sha256": _sha256_bytes(payload),
            }
        )

    return roles


def _accept(paths, _snapshot):
    return subprocess.CompletedProcess([], 0, "{}\n", "")


def test_designated_bytes_resolve_through_the_real_owned_seat_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(workspace)

    roles = _build_descriptor_and_roles(workspace)
    descriptor = workspace / "admission.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": "ember-owned-admission-input-v1",
                "candidate_id": "candidate-designate-fixture",
                "roles": roles,
            }
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "candidates"

    monkeypatch.setattr(produce_candidate, "run_identity_consumer", _accept)
    monkeypatch.setattr(produce_candidate, "run_restart_consumer", _accept)
    monkeypatch.setattr(
        produce_candidate, "verify_consumer_validators", lambda _snapshots: True
    )

    result = produce_candidate.main(
        [
            "--workspace", str(workspace),
            "--descriptor", str(descriptor),
            "--output-root", str(output_root),
        ]
    )
    assert result == 0

    candidate_root = output_root / "candidate-designate-fixture"
    published_manifest = candidate_root / "run.json"
    assert published_manifest.is_file()
    # Byte-identity with the pre-admission source: admission preserves the
    # exact bytes /designate will later select, unmodified.
    assert published_manifest.read_bytes() == (workspace / "run.json").read_bytes()

    # Simulate exactly what /designate writes -- a file literally named
    # current.json holding the restart_run_manifest role's exact bytes --
    # co-located with the rest of the candidate's already-published
    # dependency closure (which is what makes root-relative resolution
    # inside contract.py/cli_seat.py possible at all).
    current_json = candidate_root / "current.json"
    shutil.copyfile(published_manifest, current_json)
    assert _sha256_file(current_json) == _sha256_file(published_manifest)

    registry_path = candidate_root / "trusted-verifiers.json"
    registry_bytes = registry_path.read_bytes()
    approval_path = candidate_root / "trusted-registry-approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "schema_version": "ember-trusted-verifier-registry-approval-v1",
                "trusted_verifier_registry_sha256": _sha256_bytes(registry_bytes),
            }
        ),
        encoding="utf-8",
    )

    manifest = json.loads(current_json.read_text(encoding="utf-8"))

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

    # The setup call above already registered workspace's checkpoint shards
    # at this exact db path (_register_checkpoint_custody's own fixed name)
    # -- reuse it. Custody records are hash-keyed, not location-keyed, so
    # they still cover current_json's copied-but-byte-identical manifest.
    resolved = cli_seat.resolve_owned_seat(
        current_json,
        registry_path,
        approval_path,
        custody_db=workspace / "custody-gate-test.sqlite3",
    )

    assert resolved["valid"] is True, resolved["errors"]
    assert resolved["seat"] == "OWNED_ADMITTED"
    assert resolved["checkpoint_sha256"] == "a" * 64
