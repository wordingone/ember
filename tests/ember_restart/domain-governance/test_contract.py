# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ember.governance.scripts.ember_restart import contract


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
VALIDATOR = (
    REPO_ROOT
    / "src"
    / "ember"
    / "governance"
    / "scripts"
    / "ember_restart"
    / "contract.py"
)


def test_governed_repository_root_tracks_relocated_contract() -> None:
    assert contract.governed_repository_root() == REPO_ROOT


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

    Initializing a fresh bare remote, copying this checkout's exact HEAD commit
    object into it, and forcing ``refs/heads/master`` to that sha resolves to
    exactly one row on every checkout shape (attached branch, detached HEAD,
    orphan detach reachable only via the branch this checkout's HEAD sits
    on).  Copying the one content-addressed object avoids both a dependency on
    this checkout's branch state and Git-for-Windows' shell-backed local-clone
    path, which is unavailable on some lifecycle-managed hosts.
    """
    remote_dir = tmp_path / "governed-remote.git"
    head_sha = _current_source_commit()
    subprocess.run(
        ["git", "init", "--bare", str(remote_dir)],
        check=True, capture_output=True, text=True,
    )
    commit_bytes = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "commit", head_sha],
        check=True, capture_output=True,
    ).stdout
    copied_sha = subprocess.run(
        ["git", "--git-dir", str(remote_dir), "hash-object", "-t", "commit", "-w", "--stdin"],
        input=commit_bytes, check=True, capture_output=True, text=False,
    ).stdout.decode("ascii").strip()
    assert copied_sha == head_sha
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
if args.active_expert and args.active_expert not in experts:
    raise SystemExit(1)
active = shared if not args.active_expert else shared + layers * expert_per_layer
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
    "active_expert_ids": [args.active_expert] if args.active_expert else [],
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


def _genesis_manifest(tmp_path: Path) -> Path:
    """Convert the real on-disk trained fixture shape into the additive genesis class.

    The checkpoint, expert shards, independently trusted counter, and custody
    inputs remain physical files.  Only the claim envelope changes; PR2 will
    replace this fixture author with the production zero-step materializer.
    """
    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint_path = tmp_path / manifest["checkpoint"]["manifest_path"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    boundary = {
        "schema_version": "ember-genesis-claim-boundary-v1",
        "global_step": 0,
        "tokens_seen": 0,
        "optimizer_steps": 0,
        "training_executed": False,
        "observed_training": False,
        "positive_modality_exposure": False,
        "evaluation_eligible": False,
        "trained_authority": False,
        "sufficiency": False,
        "capability": False,
        "benchmark": False,
    }
    checkpoint["schema_version"] = "ember-sparse-checkpoint-v5"
    checkpoint["contract_version"] = 5
    for shard in checkpoint["shards"]:
        shard["path"] = Path(shard["path"]).name
    checkpoint["data_cursor"] = {
        "shard": "GENESIS",
        "record_index": 0,
        "global_step": 0,
        "tokens_seen": 0,
    }
    checkpoint["genesis_claim_boundary"] = boundary
    checkpoint_sha256 = _write_json(checkpoint_path, checkpoint)
    parameter_receipt_path = tmp_path / manifest["architecture"]["parameter_receipt"]["path"]
    parameter_receipt = json.loads(parameter_receipt_path.read_text(encoding="utf-8"))
    parameter_receipt["subject_checkpoint_sha256"] = checkpoint_sha256
    manifest["architecture"]["parameter_receipt"]["sha256"] = _write_json(
        parameter_receipt_path, parameter_receipt
    )
    manifest["schema_version"] = "ember-owned-genesis-v1"
    manifest["stage"] = "GENESIS_CANDIDATE"
    manifest["checkpoint"]["sha256"] = checkpoint_sha256
    for bank in manifest["architecture"]["expert_banks"]:
        bank["artifact_sha256"] = bank["genesis_sha256"]
    manifest.pop("tokenizer")
    manifest.pop("training_data")
    manifest.pop("training")
    manifest["genesis_claim_boundary"] = boundary
    _write_json(manifest_path, manifest)
    return manifest_path


def _register_checkpoint_custody(tmp_path: Path) -> Path:
    """Issue #1721: contract.py's checkpoint admission now runs the real
    `ember-lab custody-verify` gate over `_candidate_manifest`'s checkpoint
    shards. Registers those exact shard hashes into an ISOLATED per-test
    catalog (never the real repo state/ember-lab-catalog.sqlite3) via the
    real `register-artifact` CLI, so the fixture is admitted instead of
    refused as unregistered. Skips (not fails) when no binary is built --
    the same skip-not-refuse convention contract.py's own gate uses for a
    host that structurally cannot run the Windows-only ember-lab CLI.
    """
    from src.ember.governance.scripts import artifact_custody_gate as gate

    binary = gate.canonical_ember_lab_binary(REPO_ROOT)
    if binary is None:
        pytest.skip(
            "no built ember-lab binary under runtime/ember-lab/target/"
            "{release,debug}/ember-lab.exe; build it before running this test"
        )
    index = json.loads((tmp_path / "checkpoint" / "checkpoint-manifest.json").read_text(encoding="utf-8"))
    db_path = tmp_path / "custody-gate-test.sqlite3"
    for shard in index["shards"]:
        # The manifest's shard "path" is relative to `root` (this fixture's
        # `tmp_path`, matching contract.py's own custody_verify(root=...)
        # call) but was built via `str(Path.relative_to(...))`, which on
        # Windows yields backslash separators. The catalog's locator
        # validator is portable-relative-path-only (forward slashes) --
        # normalize before registering, exactly as a real writer would.
        locator = shard["path"].replace("\\", "/")
        registration = subprocess.run(
            [
                str(binary),
                "register-artifact",
                "--db",
                str(db_path),
                "--sha256",
                shard["sha256"],
                "--byte-count",
                str(shard["bytes"]),
                "--media-type",
                "application/octet-stream",
                "--location",
                f"{gate.RESUME_CHECKPOINT_VOLUME}={locator}",
            ],
            capture_output=True,
            text=True,
        )
        assert registration.returncode == 0, registration.stderr
    return db_path


def test_checkpoint_candidate_binds_owned_multimodal_reasoning_tool_path(tmp_path: Path):
    manifest = _candidate_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
            "--custody-db",
            str(custody_db),
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


def test_genesis_candidate_is_zero_step_entry_only_and_uses_real_checkpoint_bytes(tmp_path: Path):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )

    assert result == {"valid": True, "stage": "GENESIS_CANDIDATE", "errors": []}


def test_checkpoint_shard_resolution_is_version_gated(tmp_path: Path):
    from src.ember.governance.scripts.ember_restart import contract

    trained_root = tmp_path / "trained"
    trained_root.mkdir()
    trained_manifest = _candidate_manifest(trained_root)
    trained_db = _register_checkpoint_custody(trained_root)
    assert contract.validate_manifest(
        trained_manifest,
        trained_root / "trusted-verifiers.json",
        custody_db=trained_db,
    )["valid"] is True

    genesis_root = tmp_path / "genesis"
    genesis_root.mkdir()
    genesis_manifest = _genesis_manifest(genesis_root)
    genesis_db = _register_checkpoint_custody(genesis_root)
    assert contract.validate_manifest(
        genesis_manifest,
        genesis_root / "trusted-verifiers.json",
        custody_db=genesis_db,
    )["valid"] is True

    manifest = json.loads(genesis_manifest.read_text(encoding="utf-8"))
    checkpoint_path = genesis_root / manifest["checkpoint"]["manifest_path"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["shards"][0]["path"] = f"checkpoint/{checkpoint['shards'][0]['path']}"
    checkpoint_sha256 = _write_json(checkpoint_path, checkpoint)
    manifest["checkpoint"]["sha256"] = checkpoint_sha256
    parameter_receipt_path = genesis_root / manifest["architecture"]["parameter_receipt"]["path"]
    parameter_receipt = json.loads(parameter_receipt_path.read_text(encoding="utf-8"))
    parameter_receipt["subject_checkpoint_sha256"] = checkpoint_sha256
    manifest["architecture"]["parameter_receipt"]["sha256"] = _write_json(
        parameter_receipt_path, parameter_receipt
    )
    _write_json(genesis_manifest, manifest)

    result = contract.validate_manifest(
        genesis_manifest,
        genesis_root / "trusted-verifiers.json",
        custody_db=genesis_db,
    )
    assert result["valid"] is False
    assert any("checkpoint.shards[0]" in error for error in result["errors"])


def test_genesis_expert_artifact_sha_is_distinct_from_tensor_genesis_sha(tmp_path: Path):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / manifest["architecture"]["parameter_receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for index, bank in enumerate(manifest["architecture"]["expert_banks"]):
        tensor_sha = hashlib.sha256(f"tensor-genesis-{index}".encode()).hexdigest()
        assert bank["artifact_sha256"] != tensor_sha
        bank["genesis_sha256"] = tensor_sha
        receipt["expert_genesis_sha256"][bank["id"]] = tensor_sha
    manifest["architecture"]["parameter_receipt"]["sha256"] = _write_json(
        receipt_path, receipt
    )
    _write_json(manifest_path, manifest)

    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert result == {"valid": True, "stage": "GENESIS_CANDIDATE", "errors": []}


@pytest.mark.parametrize("field", ["global_step", "tokens_seen", "optimizer_steps"])
def test_genesis_candidate_refuses_any_post_init_counter(tmp_path: Path, field: str):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["genesis_claim_boundary"][field] = 1
    _write_json(manifest_path, manifest)

    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert result["valid"] is False
    assert "genesis_claim_boundary: exact zero-step entry-only boundary required" in result["errors"]


@pytest.mark.parametrize(
    "field",
    [
        "training_executed",
        "observed_training",
        "positive_modality_exposure",
        "evaluation_eligible",
        "trained_authority",
        "sufficiency",
        "capability",
        "benchmark",
    ],
)
def test_genesis_candidate_refuses_widened_claim_boundary(tmp_path: Path, field: str):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["genesis_claim_boundary"][field] = True
    _write_json(manifest_path, manifest)

    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert result["valid"] is False
    assert "genesis_claim_boundary: exact zero-step entry-only boundary required" in result["errors"]


@pytest.mark.parametrize("field", ["training", "training_data", "admission", "evaluations", "serving"])
def test_genesis_candidate_refuses_every_post_training_surface(tmp_path: Path, field: str):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = {} if field != "training_data" else []
    _write_json(manifest_path, manifest)

    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert result["valid"] is False
    assert "genesis manifest: closed schema keys required" in result["errors"]


def test_trained_schema_cannot_claim_genesis_stage(tmp_path: Path):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _candidate_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "GENESIS_CANDIDATE"
    _write_json(manifest_path, manifest)

    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert result["valid"] is False
    assert "stage: must equal CHECKPOINT_CANDIDATE or OWNED_ADMITTED" in result["errors"]


def test_genesis_schema_cannot_claim_trained_stage(tmp_path: Path):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "CHECKPOINT_CANDIDATE"
    _write_json(manifest_path, manifest)

    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert result["valid"] is False
    assert "stage: must equal GENESIS_CANDIDATE" in result["errors"]


def test_genesis_checkpoint_cursor_and_boundary_must_match_outer_claim(tmp_path: Path):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint_path = tmp_path / manifest["checkpoint"]["manifest_path"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["data_cursor"]["global_step"] = 1
    checkpoint_sha256 = _write_json(checkpoint_path, checkpoint)
    manifest["checkpoint"]["sha256"] = checkpoint_sha256
    parameter_receipt_path = tmp_path / manifest["architecture"]["parameter_receipt"]["path"]
    parameter_receipt = json.loads(parameter_receipt_path.read_text(encoding="utf-8"))
    parameter_receipt["subject_checkpoint_sha256"] = checkpoint_sha256
    manifest["architecture"]["parameter_receipt"]["sha256"] = _write_json(
        parameter_receipt_path, parameter_receipt
    )
    _write_json(manifest_path, manifest)

    result = contract.validate_manifest(
        manifest_path,
        tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert result["valid"] is False
    assert "genesis checkpoint: exact zero cursor required" in result["errors"]


def test_r1_entry_mints_from_actual_on_disk_genesis_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from src.ember.governance.scripts.ember_restart import contract

    manifest_path = _genesis_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = _current_source_commit()
    _write_json(manifest_path, manifest)

    source_binding = {"test_seam": "same-process physical genesis consumer"}
    monkeypatch.setattr(contract, "_current_source_commit", lambda _root: manifest["source_commit"])
    monkeypatch.setattr(contract, "_require_clean_source_tree", lambda _root: None)
    monkeypatch.setattr(
        contract,
        "_git_blob_sha256",
        lambda root, _commit, relative: _sha256(Path(root) / relative),
    )
    monkeypatch.setattr(
        contract.source_authority,
        "bind_source_identity",
        lambda *_args, **_kwargs: source_binding,
    )

    payload = contract.build_r1_warm100_entry(
        manifest_path,
        source_commit=manifest["source_commit"],
        source_root=REPO_ROOT,
        prereg_path=REPO_ROOT / "docs/domains/governance/spec/ember02-preregistration-v1.md",
        config_path=REPO_ROOT / "configs/ember-restart-3b.json",
        fixed_prior_path=REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json",
        trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
        custody_db=custody_db,
    )

    assert payload["manifest_stage"] == "GENESIS_CANDIDATE"
    assert payload["result"] == "PREP_ONLY"
    assert payload["claim_boundary"] == {
        "steps": 100,
        "execution": False,
        "sufficiency": False,
        "capability": False,
        "benchmark": False,
    }


def test_git_authority_probe_hides_windows_console(monkeypatch: pytest.MonkeyPatch):
    from src.ember.governance.scripts.ember_restart import contract

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
    # issue2015 exact-local-import:src/ember/governance/scripts/ember_restart/contract.py
    import importlib.util as _ember_3cb9868455ee2567_importlib
    import sys as _ember_3cb9868455ee2567_sys
    from pathlib import Path as _ember_3cb9868455ee2567_Path
    _ember_3cb9868455ee2567_path = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file()).joinpath('src', 'ember', 'governance', 'scripts', 'ember_restart', 'contract.py')
    if not _ember_3cb9868455ee2567_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_restart/contract.py')
    _ember_3cb9868455ee2567_aliases = ('_ember_issue2015_3cb9868455ee2567', 'contract', 'scripts.ember_restart.contract')
    _ember_3cb9868455ee2567_existing = []
    for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
        _ember_3cb9868455ee2567_candidate = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
        if _ember_3cb9868455ee2567_candidate is not None and all(_ember_3cb9868455ee2567_candidate is not item for item in _ember_3cb9868455ee2567_existing):
            _ember_3cb9868455ee2567_existing.append(_ember_3cb9868455ee2567_candidate)
    if len(_ember_3cb9868455ee2567_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
    if _ember_3cb9868455ee2567_existing:
        _ember_3cb9868455ee2567_module = _ember_3cb9868455ee2567_existing[0]
        _ember_3cb9868455ee2567_observed = getattr(_ember_3cb9868455ee2567_module, '__file__', None)
        if _ember_3cb9868455ee2567_observed is None or _ember_3cb9868455ee2567_Path(_ember_3cb9868455ee2567_observed).resolve() != _ember_3cb9868455ee2567_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_restart/contract.py')
    else:
        _ember_3cb9868455ee2567_spec = _ember_3cb9868455ee2567_importlib.spec_from_file_location('_ember_issue2015_3cb9868455ee2567', _ember_3cb9868455ee2567_path)
        if _ember_3cb9868455ee2567_spec is None or _ember_3cb9868455ee2567_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_restart/contract.py')
        _ember_3cb9868455ee2567_module = _ember_3cb9868455ee2567_importlib.module_from_spec(_ember_3cb9868455ee2567_spec)
        for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
            _ember_3cb9868455ee2567_prior = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
            if _ember_3cb9868455ee2567_prior is not None and _ember_3cb9868455ee2567_prior is not _ember_3cb9868455ee2567_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
            _ember_3cb9868455ee2567_sys.modules[_ember_3cb9868455ee2567_alias] = _ember_3cb9868455ee2567_module
        try:
            _ember_3cb9868455ee2567_spec.loader.exec_module(_ember_3cb9868455ee2567_module)
        except BaseException:
            for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
                if _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias) is _ember_3cb9868455ee2567_module:
                    _ember_3cb9868455ee2567_sys.modules.pop(_ember_3cb9868455ee2567_alias, None)
            raise
    for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
        _ember_3cb9868455ee2567_prior = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
        if _ember_3cb9868455ee2567_prior is not None and _ember_3cb9868455ee2567_prior is not _ember_3cb9868455ee2567_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
        _ember_3cb9868455ee2567_sys.modules[_ember_3cb9868455ee2567_alias] = _ember_3cb9868455ee2567_module
    build_r1_warm100_entry = getattr(_ember_3cb9868455ee2567_module, 'build_r1_warm100_entry')
    validate_r1_warm100_entry = getattr(_ember_3cb9868455ee2567_module, 'validate_r1_warm100_entry')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/contract.py

    governed_remote, governed_ref = hermetic_governed_remote
    manifest_path = _candidate_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = _current_source_commit()
    _write_json(manifest_path, manifest)
    payload = build_r1_warm100_entry(
        manifest_path,
        source_commit=manifest["source_commit"],
        source_root=REPO_ROOT,
        prereg_path=REPO_ROOT / "docs/domains/governance/spec/ember02-preregistration-v1.md",
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
        custody_db=custody_db,
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
    # issue2015 exact-local-import:src/ember/governance/scripts/ember_restart/contract.py
    import importlib.util as _ember_3cb9868455ee2567_importlib
    import sys as _ember_3cb9868455ee2567_sys
    from pathlib import Path as _ember_3cb9868455ee2567_Path
    _ember_3cb9868455ee2567_path = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file()).joinpath('src', 'ember', 'governance', 'scripts', 'ember_restart', 'contract.py')
    if not _ember_3cb9868455ee2567_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_restart/contract.py')
    _ember_3cb9868455ee2567_aliases = ('_ember_issue2015_3cb9868455ee2567', 'contract', 'scripts.ember_restart.contract')
    _ember_3cb9868455ee2567_existing = []
    for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
        _ember_3cb9868455ee2567_candidate = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
        if _ember_3cb9868455ee2567_candidate is not None and all(_ember_3cb9868455ee2567_candidate is not item for item in _ember_3cb9868455ee2567_existing):
            _ember_3cb9868455ee2567_existing.append(_ember_3cb9868455ee2567_candidate)
    if len(_ember_3cb9868455ee2567_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
    if _ember_3cb9868455ee2567_existing:
        _ember_3cb9868455ee2567_module = _ember_3cb9868455ee2567_existing[0]
        _ember_3cb9868455ee2567_observed = getattr(_ember_3cb9868455ee2567_module, '__file__', None)
        if _ember_3cb9868455ee2567_observed is None or _ember_3cb9868455ee2567_Path(_ember_3cb9868455ee2567_observed).resolve() != _ember_3cb9868455ee2567_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_restart/contract.py')
    else:
        _ember_3cb9868455ee2567_spec = _ember_3cb9868455ee2567_importlib.spec_from_file_location('_ember_issue2015_3cb9868455ee2567', _ember_3cb9868455ee2567_path)
        if _ember_3cb9868455ee2567_spec is None or _ember_3cb9868455ee2567_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_restart/contract.py')
        _ember_3cb9868455ee2567_module = _ember_3cb9868455ee2567_importlib.module_from_spec(_ember_3cb9868455ee2567_spec)
        for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
            _ember_3cb9868455ee2567_prior = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
            if _ember_3cb9868455ee2567_prior is not None and _ember_3cb9868455ee2567_prior is not _ember_3cb9868455ee2567_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
            _ember_3cb9868455ee2567_sys.modules[_ember_3cb9868455ee2567_alias] = _ember_3cb9868455ee2567_module
        try:
            _ember_3cb9868455ee2567_spec.loader.exec_module(_ember_3cb9868455ee2567_module)
        except BaseException:
            for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
                if _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias) is _ember_3cb9868455ee2567_module:
                    _ember_3cb9868455ee2567_sys.modules.pop(_ember_3cb9868455ee2567_alias, None)
            raise
    for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
        _ember_3cb9868455ee2567_prior = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
        if _ember_3cb9868455ee2567_prior is not None and _ember_3cb9868455ee2567_prior is not _ember_3cb9868455ee2567_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
        _ember_3cb9868455ee2567_sys.modules[_ember_3cb9868455ee2567_alias] = _ember_3cb9868455ee2567_module
    build_r1_warm100_entry = getattr(_ember_3cb9868455ee2567_module, 'build_r1_warm100_entry')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/contract.py

    current = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    stale = subprocess.check_output(
        ["git", "rev-parse", "HEAD^"], cwd=REPO_ROOT, text=True
    ).strip()
    assert stale and stale != current
    manifest_path = _candidate_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = stale
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="current source commit"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=stale,
            source_root=REPO_ROOT,
            prereg_path=REPO_ROOT / "docs/domains/governance/spec/ember02-preregistration-v1.md",
            config_path=REPO_ROOT / "configs/ember-restart-3b.json",
            fixed_prior_path=REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json",
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            custody_db=custody_db,
        )


def test_r1_warm100_entry_rejects_dirty_source_tree(tmp_path: Path):
    """A dirty checkout cannot mint a source-authoritative R1 entry."""
    # issue2015 exact-local-import:src/ember/governance/scripts/ember_restart/contract.py
    import importlib.util as _ember_3cb9868455ee2567_importlib
    import sys as _ember_3cb9868455ee2567_sys
    from pathlib import Path as _ember_3cb9868455ee2567_Path
    _ember_3cb9868455ee2567_path = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file()).joinpath('src', 'ember', 'governance', 'scripts', 'ember_restart', 'contract.py')
    if not _ember_3cb9868455ee2567_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_restart/contract.py')
    _ember_3cb9868455ee2567_aliases = ('_ember_issue2015_3cb9868455ee2567', 'contract', 'scripts.ember_restart.contract')
    _ember_3cb9868455ee2567_existing = []
    for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
        _ember_3cb9868455ee2567_candidate = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
        if _ember_3cb9868455ee2567_candidate is not None and all(_ember_3cb9868455ee2567_candidate is not item for item in _ember_3cb9868455ee2567_existing):
            _ember_3cb9868455ee2567_existing.append(_ember_3cb9868455ee2567_candidate)
    if len(_ember_3cb9868455ee2567_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
    if _ember_3cb9868455ee2567_existing:
        _ember_3cb9868455ee2567_module = _ember_3cb9868455ee2567_existing[0]
        _ember_3cb9868455ee2567_observed = getattr(_ember_3cb9868455ee2567_module, '__file__', None)
        if _ember_3cb9868455ee2567_observed is None or _ember_3cb9868455ee2567_Path(_ember_3cb9868455ee2567_observed).resolve() != _ember_3cb9868455ee2567_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_restart/contract.py')
    else:
        _ember_3cb9868455ee2567_spec = _ember_3cb9868455ee2567_importlib.spec_from_file_location('_ember_issue2015_3cb9868455ee2567', _ember_3cb9868455ee2567_path)
        if _ember_3cb9868455ee2567_spec is None or _ember_3cb9868455ee2567_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_restart/contract.py')
        _ember_3cb9868455ee2567_module = _ember_3cb9868455ee2567_importlib.module_from_spec(_ember_3cb9868455ee2567_spec)
        for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
            _ember_3cb9868455ee2567_prior = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
            if _ember_3cb9868455ee2567_prior is not None and _ember_3cb9868455ee2567_prior is not _ember_3cb9868455ee2567_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
            _ember_3cb9868455ee2567_sys.modules[_ember_3cb9868455ee2567_alias] = _ember_3cb9868455ee2567_module
        try:
            _ember_3cb9868455ee2567_spec.loader.exec_module(_ember_3cb9868455ee2567_module)
        except BaseException:
            for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
                if _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias) is _ember_3cb9868455ee2567_module:
                    _ember_3cb9868455ee2567_sys.modules.pop(_ember_3cb9868455ee2567_alias, None)
            raise
    for _ember_3cb9868455ee2567_alias in _ember_3cb9868455ee2567_aliases:
        _ember_3cb9868455ee2567_prior = _ember_3cb9868455ee2567_sys.modules.get(_ember_3cb9868455ee2567_alias)
        if _ember_3cb9868455ee2567_prior is not None and _ember_3cb9868455ee2567_prior is not _ember_3cb9868455ee2567_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/contract.py')
        _ember_3cb9868455ee2567_sys.modules[_ember_3cb9868455ee2567_alias] = _ember_3cb9868455ee2567_module
    build_r1_warm100_entry = getattr(_ember_3cb9868455ee2567_module, 'build_r1_warm100_entry')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/contract.py

    manifest_path = _candidate_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = _current_source_commit()
    _write_json(manifest_path, manifest)
    dirty_path = REPO_ROOT / "docs/domains/governance/ember-restart/r1-warm100-entry-v1.md"
    original = dirty_path.read_bytes()
    try:
        dirty_path.write_bytes(original + b"\nlocal-dirty-source\n")
        with pytest.raises(ValueError, match="source tree is dirty"):
            build_r1_warm100_entry(
                manifest_path,
                source_commit=manifest["source_commit"],
                source_root=REPO_ROOT,
                prereg_path=REPO_ROOT / "docs/domains/governance/spec/ember02-preregistration-v1.md",
                config_path=REPO_ROOT / "configs/ember-restart-3b.json",
                fixed_prior_path=REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json",
                trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
                custody_db=custody_db,
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
    from src.ember.governance.scripts.ember_restart import contract as contract_module

    governed_remote, governed_ref = hermetic_governed_remote
    monkeypatch.setattr(contract_module, "GOVERNED_REMOTE", governed_remote)
    monkeypatch.setattr(contract_module, "GOVERNED_REMOTE_REF", governed_ref)

    manifest_path = _candidate_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
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
            str(REPO_ROOT / "docs/domains/governance/spec/ember02-preregistration-v1.md"),
            "--config",
            str(REPO_ROOT / "configs/ember-restart-3b.json"),
            "--fixed-prior",
            str(REPO_ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json"),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
            "--custody-db",
            str(custody_db),
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
            str(REPO_ROOT / "docs/domains/governance/spec/ember02-preregistration-v1.md"),
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


SHARED_ROUTE_ACTIVE_PARAMETERS = 1_020_589_568


def _shared_route_candidate(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest_path = _candidate_manifest(tmp_path)
    custody_db = _register_checkpoint_custody(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry_path = tmp_path / "trusted-verifiers.json"

    architecture = manifest["architecture"]
    architecture["active_expert_ids"] = ["shared"]
    architecture["active_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS
    architecture["episode_trainable_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS

    receipt_path = tmp_path / architecture["parameter_receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["active_expert_ids"] = ["shared"]
    receipt["active_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS
    receipt["episode_trainable_parameters"] = SHARED_ROUTE_ACTIVE_PARAMETERS
    architecture["parameter_receipt"]["sha256"] = _write_json(receipt_path, receipt)

    _write_json(manifest_path, manifest)
    return manifest_path, registry_path, custody_db


def test_shared_route_is_passed_verbatim_to_the_trusted_parameter_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, registry_path, custody_db = _shared_route_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / manifest["architecture"]["parameter_receipt"]["path"]
    measured = json.loads(receipt_path.read_text(encoding="utf-8"))
    observed_argv: list[str] = []
    original_run = subprocess.run

    def execute_counter(argv, **kwargs):
        if "--active-expert" not in argv:
            return original_run(argv, **kwargs)
        observed_argv.extend(str(value) for value in argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps(measured), stderr="")

    monkeypatch.setattr(contract.subprocess, "run", execute_counter)
    result = contract.validate_manifest(
        manifest_path,
        registry_path,
        custody_db=custody_db,
    )

    assert result == {"valid": True, "stage": "CHECKPOINT_CANDIDATE", "errors": []}
    assert observed_argv[observed_argv.index("--active-expert") + 1] == "shared"


@pytest.mark.parametrize(
    ("active_expert_ids", "expected_error"),
    [
        ([], "architecture.active_expert_ids: exactly one route must be active per episode"),
        (["undeclared"], "architecture.active_expert_ids: active route is not declared"),
    ],
)
def test_candidate_refuses_absent_or_wrong_active_route(
    tmp_path: Path,
    active_expert_ids: list[str],
    expected_error: str,
) -> None:
    manifest_path, registry_path, custody_db = _shared_route_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["architecture"]["active_expert_ids"] = active_expert_ids
    _write_json(manifest_path, manifest)

    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest_path),
            "--trusted-verifier-registry",
            str(registry_path),
            "--custody-db",
            str(custody_db),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert result["valid"] is False
    assert expected_error in result["errors"]
