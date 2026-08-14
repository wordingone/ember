# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "ember_restart" / "contract.py"


def _current_source_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


@pytest.fixture
def hermetic_governed_remote(tmp_path: Path) -> tuple[str, str]:
    """A real clone of this checkout's own object store, ref forced to HEAD.

    Round-3 fix (review-1702-adversarial.md, round 3): the prior approach
    derived the governed ref from this checkout's OWN branch state
    (``git rev-parse --symbolic-full-name HEAD``, falling back to bare
    "HEAD" when detached). That fallback was never exercised until a
    lifecycle-managed ``--detach`` worktree -- the exact shape
    worktree_lifecycle certification requires -- hit it: bare "HEAD"
    ambiguous-suffix-matches both this repo's own ``HEAD`` and
    ``refs/remotes/origin/HEAD`` on ``git ls-remote``, so
    ``resolve_governed_master`` sees two rows and fails closed regardless of
    which commit is actually checked out. Test outcome was still a function
    of checkout shape, not of the code under test.

    Cloning a fresh bare remote from this checkout and forcing
    ``refs/heads/master`` to this checkout's real HEAD sha resolves to
    exactly one row on every checkout shape (attached branch, detached HEAD,
    orphan detach reachable only via the branch this checkout's HEAD sits
    on) and drops the self-referential dependency on this checkout's own
    branch state entirely.
    """
    remote_dir = tmp_path / "governed-remote.git"
    subprocess.run(
        # --no-hardlinks: pytest's tmp_path and this checkout can sit on
        # different Windows volumes/drives, where a hardlinking --local
        # clone fails outright ("Improper link") rather than falling back.
        ["git", "clone", "--local", "--no-hardlinks", "--bare", str(REPO_ROOT), str(remote_dir)],
        check=True, capture_output=True, text=True,
    )
    head_sha = _current_source_commit()
    subprocess.run(
        ["git", "-C", str(remote_dir), "update-ref", "refs/heads/master", head_sha],
        check=True, capture_output=True, text=True,
    )
    return str(remote_dir), "refs/heads/master"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return _sha256(path)


def _candidate_manifest(tmp_path: Path) -> Path:
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text('{"owned":true,"vocab_size":32000}\n', encoding="utf-8")
    tokenizer_sha = _sha256(tokenizer)
    tokenizer_script = tmp_path / "tokenizer" / "train_owned.py"
    tokenizer_script.parent.mkdir(parents=True)
    tokenizer_script.write_text("print('owned tokenizer training')\n", encoding="utf-8")
    tokenizer_corpus = tmp_path / "tokenizer" / "corpus-manifest.json"
    tokenizer_corpus_sha = _write_json(
        tokenizer_corpus, {"schema_version": "owned-tokenizer-corpus-v1", "documents": 1}
    )
    tokenizer_verifier = tmp_path / "verifiers" / "tokenizer_freeze.py"
    tokenizer_verifier.parent.mkdir(parents=True)
    tokenizer_verifier.write_text(
        """import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--tokenizer", required=True)
parser.add_argument("--training-script", required=True)
parser.add_argument("--training-corpus-manifest", required=True)
args = parser.parse_args()
tokenizer = json.loads(Path(args.tokenizer).read_text(encoding="utf-8"))
if tokenizer.get("vocab_size") != 32000:
    raise SystemExit(2)
print(json.dumps({
    "schema_version": "ember-owned-tokenizer-freeze-v1",
    "result": "FROZEN",
    "tokenizer_sha256": sha(args.tokenizer),
    "vocab_size": 32000,
    "training_script_sha256": sha(args.training_script),
    "training_corpus_sha256": sha(args.training_corpus_manifest),
    "verifier_sha256": sha(__file__),
    "borrowed_tokenizer": False,
    "frozen_pre_step0": True,
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    tokenizer_verifier_record = {
        "path": str(tokenizer_verifier.relative_to(tmp_path)),
        "sha256": _sha256(tokenizer_verifier),
    }
    tokenizer_freeze = tmp_path / "receipts" / "tokenizer-freeze.json"
    tokenizer_freeze_sha = _write_json(
        tokenizer_freeze,
        {
            "schema_version": "ember-owned-tokenizer-freeze-v1",
            "result": "FROZEN",
            "tokenizer_sha256": tokenizer_sha,
            "vocab_size": 32000,
            "training_script_sha256": _sha256(tokenizer_script),
            "training_corpus_sha256": tokenizer_corpus_sha,
            "verifier_sha256": tokenizer_verifier_record["sha256"],
            "borrowed_tokenizer": False,
            "frozen_pre_step0": True,
        },
    )

    data_verifier = tmp_path / "verifiers" / "training_data.py"
    data_verifier.parent.mkdir(parents=True, exist_ok=True)
    data_verifier.write_text(
        """import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--data-manifest", required=True)
parser.add_argument("--tokenizer", required=True)
parser.add_argument("--capability", required=True)
args = parser.parse_args()
data_path = Path(args.data_manifest)
payload = json.loads(data_path.read_text(encoding="utf-8"))
root = data_path.parents[1]
source = root / payload["source_manifest"]["path"]
records = root / payload["records_artifact"]["path"]
if payload["capability"] != args.capability:
    raise SystemExit(2)
semantic_checks = {
    "text": ["token_roundtrip", "source_target_pair"],
    "image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"],
    "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"],
    "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"],
    "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"],
}
print(json.dumps({
    "schema_version": "ember-training-data-verification-v1",
    "result": "VERIFIED",
    "capability": args.capability,
    "data_manifest_sha256": sha(data_path),
    "tokenizer_sha256": sha(args.tokenizer),
    "verifier_sha256": sha(__file__),
    "data_class": payload["data_class"],
    "record_count": payload["record_count"],
    "token_count": payload["token_count"],
    "source_manifest_sha256": sha(source),
    "records_artifact_sha256": sha(records),
    "semantic_checks": (
        semantic_checks[args.capability]
        if payload["data_class"] == "SEMANTIC_PRETRAINING"
        else []
    ),
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    data_verifier_record = {
        "path": str(data_verifier.relative_to(tmp_path)),
        "sha256": _sha256(data_verifier),
    }

    data_entries = []
    for capability in ("text", "image", "audio", "reasoning", "tool"):
        source_manifest = tmp_path / "sources" / f"{capability}.json"
        source_hash = _write_json(
            source_manifest,
            {
                "schema_version": "ember-owned-source-v1",
                "capability": capability,
                "records": 1,
                "model_mediated": False,
                "borrowed_labels": False,
            },
        )
        records_artifact = tmp_path / "records" / f"{capability}.json"
        records_hash = _write_json(
            records_artifact,
            {
                "schema_version": "ember-owned-records-v1",
                "capability": capability,
                "prompt": f"owned {capability} prompt",
                "target": f"owned {capability} target",
            },
        )
        data_manifest = tmp_path / "data" / f"{capability}.json"
        data_hash = _write_json(
            data_manifest,
            {
                "schema_version": "ember-owned-training-data-v1",
                "capability": capability,
                "data_class": "SMOKE_ONLY",
                "tokenizer_sha256": tokenizer_sha,
                "model_mediated": False,
                "borrowed_labels": False,
                "record_count": 1,
                "token_count": 1,
                "source_manifest": {
                    "path": str(source_manifest.relative_to(tmp_path)),
                    "sha256": source_hash,
                },
                "records_artifact": {
                    "path": str(records_artifact.relative_to(tmp_path)),
                    "sha256": records_hash,
                },
            },
        )
        data_receipt = tmp_path / "receipts" / f"data-{capability}.json"
        data_receipt_hash = _write_json(
            data_receipt,
            {
                "schema_version": "ember-training-data-verification-v1",
                "result": "VERIFIED",
                "capability": capability,
                "data_manifest_sha256": data_hash,
                "tokenizer_sha256": tokenizer_sha,
                "verifier_sha256": data_verifier_record["sha256"],
                "data_class": "SMOKE_ONLY",
                "record_count": 1,
                "token_count": 1,
                "source_manifest_sha256": source_hash,
                "records_artifact_sha256": records_hash,
                "semantic_checks": [],
            },
        )
        data_entries.append(
            {
                "capability": capability,
                "manifest_path": str(data_manifest.relative_to(tmp_path)),
                "sha256": data_hash,
                "owned": True,
                "locally_verified": True,
                "verifier": data_verifier_record,
                "verification_receipt": {
                    "path": str(data_receipt.relative_to(tmp_path)),
                    "sha256": data_receipt_hash,
                },
            }
        )

    optimizer = {
        "implementation": "torch.optim.AdamW",
        "hyperparameters": {
            "learning_rate": 1e-5,
            "betas": [0.9, 0.999],
            "eps": 1e-8,
            "weight_decay": 0.01,
            "foreach": False,
        },
        "state_format": "torch-optimizer-state-v1",
    }
    shard = tmp_path / "checkpoint" / "model-00001.safetensors"
    shard.parent.mkdir(parents=True)
    shard.write_bytes(b"owned-random-init-checkpoint")
    shard_records = [
        {
            "path": str(shard.relative_to(tmp_path)),
            "sha256": _sha256(shard),
            "bytes": shard.stat().st_size,
        }
    ]
    expert_banks = []
    for index, domain in enumerate(("vision", "audio", "reasoning", "tool")):
        expert = tmp_path / "checkpoint" / f"expert-{domain}.safetensors"
        expert.write_bytes(f"owned-{domain}-expert-genesis-{index}".encode("utf-8"))
        expert_hash = _sha256(expert)
        expert_path = str(expert.relative_to(tmp_path))
        shard_records.append(
            {"path": expert_path, "sha256": expert_hash, "bytes": expert.stat().st_size}
        )
        expert_banks.append(
            {"id": domain, "domain": domain, "path": expert_path, "genesis_sha256": expert_hash}
        )
    checkpoint_index = tmp_path / "checkpoint" / "checkpoint-manifest.json"
    checkpoint_index_hash = _write_json(
        checkpoint_index,
        {"shards": shard_records, "optimizer": optimizer},
    )
    parameter_counts = {
        "allocated_parameters": 3_839_161_856,
        "unique_parameters": 3_839_161_856,
        "trainable_parameters": 3_839_161_856,
        "active_parameters": 1_725_232_640,
        "episode_trainable_parameters": 1_725_232_640,
        "served_parameters": 3_839_161_856,
    }
    model_config = tmp_path / "configs" / "ember-restart-3b.json"
    model_config_hash = _write_json(
        model_config,
        {
            "contract_name": "ember-restart-3b",
            "contract_version": 3,
            "architecture_revision": "ember-sparse-3b-v2",
            "model": {
                "hidden_size": 2048,
                "layers": 14,
                "attention_heads": 16,
                "vocab_size": 32000,
                "tied_embeddings": True,
                "image_projection": {"input_shape": [48, 48, 3]},
                "audio_projection": {"frame_samples": 640},
                "expert_routing": {
                    "expert_names": ["vision", "audio", "reasoning", "tool"],
                    "shared_text_ffn": "always_active_SwiGLU_4H",
                },
                "total_unique_trainable_parameters": 3_839_161_856,
            },
            "training": {"optimizer": optimizer},
        },
    )
    counter = tmp_path / "counter" / "instantiated_meta_counter.py"
    counter.parent.mkdir(parents=True)
    counter.write_text(
        """import argparse
import hashlib
import json
import math
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--model-config", required=True)
parser.add_argument("--checkpoint-manifest", required=True)
parser.add_argument("--active-expert", required=True)
args = parser.parse_args()
config = json.loads(Path(args.model_config).read_text(encoding="utf-8"))
checkpoint = json.loads(Path(args.checkpoint_manifest).read_text(encoding="utf-8"))
if not checkpoint.get("shards"):
    raise SystemExit(3)
model = config["model"]
hidden = model["hidden_size"]
layers = model["layers"]
experts = model["expert_routing"]["expert_names"]
image_input = math.prod(model["image_projection"]["input_shape"])
audio_input = model["audio_projection"]["frame_samples"]
expert_per_layer = 12 * hidden * hidden
head_dim = hidden // model["attention_heads"]
shared = (
    model["vocab_size"] * hidden
    + layers * (4 * hidden * hidden + 12 * hidden * hidden + 2 * hidden + 2 * head_dim)
    + image_input * hidden
    + audio_input * hidden
    + hidden
)
total = shared + len(experts) * layers * expert_per_layer
active = shared if args.active_expert == "shared" else shared + layers * expert_per_layer
print(json.dumps({
    "result": "MEASURED",
    "subject_checkpoint_sha256": sha256(args.checkpoint_manifest),
    "model_config_sha256": sha256(args.model_config),
    "architecture_revision": "ember-sparse-3b-v2",
    "allocated_parameters": total,
    "unique_parameters": total,
    "trainable_parameters": total,
    "served_parameters": total,
    "active_parameters": active,
    "episode_trainable_parameters": active,
    "active_expert_ids": [args.active_expert],
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    counter_record = {
        "path": str(counter.relative_to(tmp_path)),
        "sha256": _sha256(counter),
    }
    _write_json(
        tmp_path / "trusted-verifiers.json",
        {
            "schema_version": "ember-trusted-verifiers-v1",
            "verifiers": [
                {
                    **counter_record,
                    "evidence_classes": ["parameter_realization"],
                    "criterion_ids": [],
                },
                {
                    **data_verifier_record,
                    "evidence_classes": ["training_data"],
                    "criterion_ids": [],
                },
                {
                    **tokenizer_verifier_record,
                    "evidence_classes": ["tokenizer_freeze"],
                    "criterion_ids": [],
                },
            ],
        },
    )
    parameter_receipt = tmp_path / "receipts" / "parameter-count.json"
    parameter_receipt_hash = _write_json(
        parameter_receipt,
        {
            "result": "MEASURED",
            "subject_checkpoint_sha256": checkpoint_index_hash,
            "counter_sha256": counter_record["sha256"],
            "model_config_sha256": model_config_hash,
            "architecture_revision": "ember-sparse-3b-v2",
            **parameter_counts,
            "active_expert_ids": ["reasoning"],
            "expert_genesis_sha256": {
                bank["id"]: bank["genesis_sha256"] for bank in expert_banks
            },
        },
    )
    optimizer_receipt = tmp_path / "receipts" / "optimizer.json"
    optimizer_receipt_hash = _write_json(
        optimizer_receipt,
        {
            "schema_version": "ember-optimizer-realization-v1",
            "result": "REALIZED",
            **optimizer,
            "model_config_sha256": model_config_hash,
        },
    )

    manifest = {
        "schema_version": "ember-owned-rung-v1",
        "stage": "CHECKPOINT_CANDIDATE",
        "run_id": "ember-3b-test",
        "source_commit": "7f751ac0b4c26e1f7d6278e46a6e6bb3f0ecd647",
        "lineage": {
            "genesis": "OWNED_RANDOM_INIT",
            "parent_checkpoint_sha256": None,
            "borrowed_weights": False,
            "borrowed_teachers": False,
            "borrowed_judges": False,
            "borrowed_filters": False,
            "borrowed_generated_labels": False,
        },
        "architecture": {
            "family": "ember-unified-decoder",
            "revision": "ember-sparse-3b-v2",
            "model_config": {
                "path": str(model_config.relative_to(tmp_path)),
                "sha256": model_config_hash,
            },
            **parameter_counts,
            "parameter_counter": counter_record,
            "parameter_receipt": {
                "path": str(parameter_receipt.relative_to(tmp_path)),
                "sha256": parameter_receipt_hash,
            },
            "shared_core": True,
            "sparse_differentiated_capacity": True,
            "task_level_expert_routing": True,
            "asymmetric_expert_initialization": True,
            "expert_banks": expert_banks,
            "active_expert_ids": ["reasoning"],
            "raw_image_patches": True,
            "raw_audio_frames": True,
            "soft_token_splicing": True,
            "multimodal_span_attention": True,
            "rope_2d": True,
            "separate_pretrained_encoders": False,
        },
        "tokenizer": {
            "path": str(tokenizer.relative_to(tmp_path)),
            "sha256": tokenizer_sha,
            "owned": True,
            "kind": "OWNED_TRAINED",
            "vocab_size": 32000,
            "training_script": {
                "path": str(tokenizer_script.relative_to(tmp_path)),
                "sha256": _sha256(tokenizer_script),
            },
            "training_corpus_manifest": {
                "path": str(tokenizer_corpus.relative_to(tmp_path)),
                "sha256": tokenizer_corpus_sha,
            },
            "freeze_receipt": {
                "path": str(tokenizer_freeze.relative_to(tmp_path)),
                "sha256": tokenizer_freeze_sha,
            },
            "verifier": tokenizer_verifier_record,
        },
        "training_data": data_entries,
        "training": {
            "input_class": "SMOKE_ONLY",
            "optimizer": optimizer,
            "optimizer_receipt": {
                "path": str(optimizer_receipt.relative_to(tmp_path)),
                "sha256": optimizer_receipt_hash,
            },
            "tokens_seen": 5,
            "modality_tokens": {
                "text": 1,
                "image": 1,
                "audio": 1,
                "reasoning": 1,
                "tool": 1,
            },
            "command": "python scripts/train_owned_3b.py --manifest run.json",
        },
        "checkpoint": {
            "manifest_path": str(checkpoint_index.relative_to(tmp_path)),
            "sha256": checkpoint_index_hash,
        },
    }
    manifest_path = tmp_path / "run.json"
    _write_json(manifest_path, manifest)
    return manifest_path

def test_checkpoint_candidate_binds_owned_multimodal_reasoning_tool_path(tmp_path: Path):
    manifest = _candidate_manifest(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["stage"] == "CHECKPOINT_CANDIDATE"


def test_git_authority_probe_hides_windows_console(monkeypatch: pytest.MonkeyPatch):
    from scripts.ember_restart import contract

    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, b"", "")

    monkeypatch.setattr(contract.os, "name", "nt")
    monkeypatch.setattr(contract.subprocess, "run", fake_run)

    contract._run_git(REPO_ROOT, "status", "--porcelain=v1")

    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_r1_warm100_entry_binds_contract_and_preserves_prep_only_boundary(
    tmp_path: Path, hermetic_governed_remote: tuple[str, str]
):
    """The R1 entry producer must delegate admission to the canonical contract.

    This is intentionally a PREP_ONLY artifact: no WARM-100 execution, result, or
    sufficiency credit is implied until the governed Ember CLI -> Ember Lab path
    supplies the missing runtime receipts.
    """
    from scripts.ember_restart.contract import build_r1_warm100_entry, validate_r1_warm100_entry

    governed_remote, governed_ref = hermetic_governed_remote
    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = _current_source_commit()
    _write_json(manifest_path, manifest)
    payload = build_r1_warm100_entry(
        manifest_path,
        source_commit=manifest["source_commit"],
        source_root=REPO_ROOT,
        prereg_path=REPO_ROOT / "docs/spec/ember02-preregistration-v1.md",
        config_path=REPO_ROOT / "configs/ember-restart-3b.json",
        fixed_prior_path=REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json",
        trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
        # Hermetic, no-network source-identity binding (issue #1296 P1): the
        # governed-remote leg is a bare clone of this same checkout's object
        # store via file transport, with refs/heads/master forced to this
        # checkout's real HEAD -- resolves to exactly one row on every
        # checkout shape (attached branch or detached), unlike deriving the
        # ref from this checkout's own branch state. canonical_root is left
        # at its default (self-anchor), which also resolves to this checkout.
        governed_remote=governed_remote,
        governed_ref=governed_ref,
    )
    assert validate_r1_warm100_entry(
        payload,
        source_root=REPO_ROOT,
        manifest_path=manifest_path,
        governed_remote=governed_remote,
        governed_ref=governed_ref,
    )
    assert payload["entry"] == "WARM-100"
    assert payload["result"] == "PREP_ONLY"
    assert payload["claim_boundary"] == {
        "steps": 100,
        "execution": False,
        "sufficiency": False,
        "capability": False,
        "benchmark": False,
    }
    assert payload["source_binding"]["canonical_common_dir_bound"] is True
    assert payload["source_binding"]["worktree_identity"] in {"MAIN", "MANAGED", "LEGACY"}
    assert payload["source_binding"]["governed_remote"] == governed_remote
    assert payload["source_binding"]["remote_master_sha"] == manifest["source_commit"]
    assert payload["source_binding"]["ancestry"] == "EQUAL"

    for mutate in (
        lambda candidate: candidate["dispatch"].update({"authority": "standalone-launcher"}),
        lambda candidate: candidate["source_files"]["cli_train"].update({"sha256": "0" * 64}),
        lambda candidate: candidate.update({"config_sha256": "0" * 64}),
        lambda candidate: candidate.update({"receipt_sha256": "0" * 64}),
    ):
        tampered = json.loads(json.dumps(payload))
        mutate(tampered)
        try:
            validate_r1_warm100_entry(
                tampered,
                source_root=REPO_ROOT,
                manifest_path=manifest_path,
                governed_remote=governed_remote,
                governed_ref=governed_ref,
            )
        except ValueError:
            continue
        raise AssertionError("tampered R1 entry was accepted")


def test_r1_warm100_entry_rejects_stale_source_commit(tmp_path: Path):
    """A reachable but stale source tree cannot mint a current R1 entry."""
    from scripts.ember_restart.contract import build_r1_warm100_entry

    current = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    stale = subprocess.check_output(
        ["git", "rev-parse", "HEAD^"], cwd=REPO_ROOT, text=True
    ).strip()
    assert stale and stale != current
    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = stale
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="current source commit"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=stale,
            source_root=REPO_ROOT,
            prereg_path=REPO_ROOT / "docs/spec/ember02-preregistration-v1.md",
            config_path=REPO_ROOT / "configs/ember-restart-3b.json",
            fixed_prior_path=REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json",
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
        )


def test_r1_warm100_entry_rejects_dirty_source_tree(tmp_path: Path):
    """A dirty checkout cannot mint a source-authoritative R1 entry."""
    from scripts.ember_restart.contract import build_r1_warm100_entry

    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = _current_source_commit()
    _write_json(manifest_path, manifest)
    dirty_path = REPO_ROOT / "docs/ember-restart/r1-warm100-entry-v1.md"
    original = dirty_path.read_bytes()
    try:
        dirty_path.write_bytes(original + b"\nlocal-dirty-source\n")
        with pytest.raises(ValueError, match="source tree is dirty"):
            build_r1_warm100_entry(
                manifest_path,
                source_commit=manifest["source_commit"],
                source_root=REPO_ROOT,
                prereg_path=REPO_ROOT / "docs/spec/ember02-preregistration-v1.md",
                config_path=REPO_ROOT / "configs/ember-restart-3b.json",
                fixed_prior_path=REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json",
                trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            )
    finally:
        dirty_path.write_bytes(original)


def test_r1_warm100_entry_cli_emits_path_free_receipt(
    tmp_path: Path, monkeypatch, capsys, hermetic_governed_remote: tuple[str, str]
):
    """The real CLI entry point (argparse main(), in-process), no argv override:
    issue #1296 P1 deliberately exposes no --canonical-root/--governed-remote
    flag, so this test cannot point the CLI at a hermetic remote via argv.

    F1 fix (review-1702-adversarial.md, round 2): the prior version instead
    let this test bind the real network GOVERNED_REMOTE and assert rc==0,
    which is only true when THIS checkout's HEAD is itself published-or-
    ancestor on github master -- false on the PR branch itself, on any
    unpushed branch, and offline (require_published_ancestry binds the
    branch TIP via _current_source_commit(), not "the branch point" the old
    docstring claimed). That made the test's own green/red state a function
    of which branch happened to be checked out, not of the code under test.

    Round-2 fix used a hermetic file-transport remote, but derived
    governed_ref from THIS checkout's own branch state -- which broke again
    (round 3) the moment the checkout was a detached-HEAD managed worktree,
    the exact shape worktree_lifecycle certification requires. Now uses the
    same hermetic_governed_remote fixture as
    test_r1_warm100_entry_binds_contract_and_preserves_prep_only_boundary: a
    bare clone with refs/heads/master forced to this checkout's real HEAD,
    independent of this checkout's own branch/detach state.

    Hermetic fix: main()'s r1-entry path always calls build_r1_warm100_entry
    with governed_remote=None (there is no argv flag for it), which falls
    back to reading the module-level GOVERNED_REMOTE/GOVERNED_REMOTE_REF
    globals at call time. Monkeypatching those two globals exercises the
    identical CLI code path a real subprocess invocation takes (argv
    parsing, no override flags, same build_r1_warm100_entry call), with zero
    new CLI surface.
    """
    from scripts.ember_restart import contract as contract_module

    governed_remote, governed_ref = hermetic_governed_remote
    monkeypatch.setattr(contract_module, "GOVERNED_REMOTE", governed_remote)
    monkeypatch.setattr(contract_module, "GOVERNED_REMOTE_REF", governed_ref)

    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = _current_source_commit()
    _write_json(manifest_path, manifest)
    exit_code = contract_module.main(
        [
            "r1-entry",
            str(manifest_path),
            "--source-commit",
            manifest["source_commit"],
            "--source-root",
            str(REPO_ROOT),
            "--prereg",
            str(REPO_ROOT / "docs/spec/ember02-preregistration-v1.md"),
            "--config",
            str(REPO_ROOT / "configs/ember-restart-3b.json"),
            "--fixed-prior",
            str(REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json"),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    payload = json.loads(captured.out)
    assert payload["schema"] == "ember-r1-warm100-entry-v2"
    assert payload["result"] == "PREP_ONLY"
    assert all("\\" not in row["path"] and ":" not in row["path"] for row in payload["source_files"].values())
    assert payload["source_binding"]["canonical_common_dir_bound"] is True
    assert payload["source_binding"]["worktree_identity"] in {"MAIN", "MANAGED", "LEGACY"}
    assert payload["source_binding"]["governed_remote"] == governed_remote
    assert payload["source_binding"]["remote_master_sha"] == manifest["source_commit"]
    assert payload["source_binding"]["ancestry"] == "EQUAL"


def test_r1_warm100_entry_cli_refusal_is_content_addressed(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "r1-entry",
            str(REPO_ROOT / "configs/ember-restart-3b.json"),
            "--source-commit",
            "60c0c6fe8d2fe66e10be4e1168d8be560642d954",
            "--source-root",
            str(REPO_ROOT),
            "--prereg",
            str(REPO_ROOT / "docs/spec/ember02-preregistration-v1.md"),
            "--config",
            str(REPO_ROOT / "configs/ember-restart-3b.json"),
            "--fixed-prior",
            str(REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["schema"] == "ember-r1-warm100-entry-refusal-v1"
    assert payload["source_commit"] == "60c0c6fe8d2fe66e10be4e1168d8be560642d954"
    assert payload["result"] == "REFUSED"
    assert payload["claim_boundary"]["execution"] is False
    assert payload["next_action"] == "author and validate the governed R1 WARM-100 manifest"
    unsigned = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    assert payload["receipt_sha256"] == hashlib.sha256(
        (json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


REAL_PARAMETER_COUNTER = (
    REPO_ROOT
    / "manifests"
    / "ember-02-admission"
    / "verifiers"
    / "parameter-realization-verifier.py"
)
SHARED_ROUTE_ACTIVE_PARAMETERS = 1_020_589_568


def test_shared_route_candidate_clears_the_real_trusted_parameter_counter(tmp_path: Path):
    """A shared-route candidate must satisfy the real counter contract.py invokes (#1718).

    contract.py spells the shared route "shared"; the trusted verifier spells it as an
    absent expert (`--active-expert <id|empty>`) and rejects "shared" outright. The
    fixture counter in this file accepts "shared", so only the real verifier catches it.
    """
    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    counter = tmp_path / "counter" / "parameter-realization-verifier.py"
    counter.write_bytes(REAL_PARAMETER_COUNTER.read_bytes())
    counter_record = {
        "path": str(counter.relative_to(tmp_path)),
        "sha256": _sha256(counter),
    }
    registry_path = tmp_path / "trusted-verifiers.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["verifiers"] = [
        (
            {
                **counter_record,
                "evidence_classes": ["parameter_realization"],
                "criterion_ids": [],
            }
            if "parameter_realization" in entry.get("evidence_classes", [])
            else entry
        )
        for entry in registry["verifiers"]
    ]
    _write_json(registry_path, registry)

    architecture = manifest["architecture"]
    architecture["parameter_counter"] = counter_record
    architecture["active_expert_ids"] = ["shared"]
    architecture["active_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS
    architecture["episode_trainable_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS

    receipt_path = tmp_path / architecture["parameter_receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["counter_sha256"] = counter_record["sha256"]
    receipt["active_expert_ids"] = ["shared"]
    receipt["active_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS
    receipt["episode_trainable_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS
    architecture["parameter_receipt"]["sha256"] = _write_json(receipt_path, receipt)

    _write_json(manifest_path, manifest)

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest_path),
            "--trusted-verifier-registry",
            str(registry_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
