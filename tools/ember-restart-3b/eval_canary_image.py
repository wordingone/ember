#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic mechanics-only image evaluation canary."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import torch
from tokenizers import Tokenizer, __version__ as tokenizers_version

from model import MultimodalSpan, RawPatchProjector, RestartDecoderConfig, UnifiedDecoder


ROOT = Path(__file__).resolve().parents[2]


class CanaryRefusal(ValueError):
    def __init__(self, row_class: str, detail: str) -> None:
        super().__init__(f"{row_class}: {detail}")
        self.row_class = row_class

NEGATIVE_ROWS: tuple[tuple[str, str | None], ...] = (
    ("LOADER_RECEIPT_MISSING", None),
    ("CHECKPOINT_TENSOR_IDENTITY_MISMATCH", None),
    ("CHECKPOINT_FILE_IDENTITY_MISMATCH_IDENTICAL_TENSORS", None),
    ("CALLER_PREDICTION_FORBIDDEN", "caller_supplied"),
    ("CALLER_PREDICTION_FORBIDDEN", "cached"),
    ("CALLER_PREDICTION_FORBIDDEN", "copied"),
    ("GOLD_SUBSTITUTION_FORBIDDEN", None),
    ("IMAGE_PAYLOAD_MISSING", None),
    ("IMAGE_PAYLOAD_IDENTITY_MISMATCH", None),
    ("ITEM_SET_INCOMPLETE", None),
    ("ITEM_ORDER_MISMATCH", None),
    ("DUPLICATE_ITEM_ID", None),
    ("DECLARED_DELETION_PATH_ACTIVE", None),
    ("IMAGE_PATH_DISABLED", None),
    ("ZERO_ITEMS", None),
    ("SKIPPED_ALL", None),
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_tensor_hash(name: str, tensor: torch.Tensor) -> str:
    if sys.byteorder != "little":
        raise RuntimeError("canonical tensor hashes require little-endian raw bytes")
    value = tensor.detach().cpu().contiguous()
    raw = bytes(value.view(torch.uint8).reshape(-1).tolist())
    header = json.dumps(
        {"dtype": str(value.dtype), "name": name, "shape": list(value.shape)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(header + b"\n" + raw)


def read_ppm(path: Path) -> torch.Tensor:
    raw = path.read_bytes()
    parts = raw.split(b"\n", 3)
    if len(parts) != 4 or parts[:3] != [b"P6", b"48 48", b"255"] or len(parts[3]) != 48 * 48 * 3:
        raise ValueError("canary image must be an exact 48x48 binary PPM")
    return torch.tensor(list(parts[3]), dtype=torch.uint8).reshape(1, 1, 48, 48, 3)


def validate_manifest(fixture_root: Path, manifest: dict[str, object]) -> None:
    if manifest.get("authority_scope") != "MECHANICS_CANARY_ONLY":
        raise CanaryRefusal("LOADER_RECEIPT_MISSING", "authority scope is absent or not mechanics-only")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise CanaryRefusal("ZERO_ITEMS", "no canary items were supplied")
    if len(items) != 8:
        raise CanaryRefusal("ITEM_SET_INCOMPLETE", "the exact eight-item set is required")
    ids = [item.get("item_id") for item in items if isinstance(item, dict)]
    if len(ids) != 8:
        raise CanaryRefusal("ITEM_SET_INCOMPLETE", "every item must be an object with an ID")
    if len(set(ids)) != len(ids):
        raise CanaryRefusal("DUPLICATE_ITEM_ID", "item IDs must be unique")
    expected_ids = [f"canary-image-{index:02d}" for index in range(8)]
    if ids != expected_ids:
        raise CanaryRefusal("ITEM_ORDER_MISMATCH", "item order differs from the frozen order")
    for declared in manifest.get("declared_deletion_paths", []):
        if (fixture_root / str(declared)).exists():
            raise CanaryRefusal("DECLARED_DELETION_PATH_ACTIVE", "a declared-deleted path is active")
    for item in items:
        asset_path = fixture_root / str(item["asset"])
        if not asset_path.is_file():
            raise CanaryRefusal("IMAGE_PAYLOAD_MISSING", f"missing {item['asset']}")
        if sha256_bytes(asset_path.read_bytes()) != item.get("asset_sha256"):
            raise CanaryRefusal("IMAGE_PAYLOAD_IDENTITY_MISMATCH", f"identity mismatch for {item['asset']}")


def load_positive(
    fixture_root: Path,
    *,
    manifest_override: dict[str, object] | None = None,
) -> tuple[dict[str, object], RestartDecoderConfig, UnifiedDecoder, Tokenizer]:
    manifest = (
        copy.deepcopy(manifest_override)
        if manifest_override is not None
        else json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
    )
    if manifest.get("authority_scope") != "MECHANICS_CANARY_ONLY":
        raise CanaryRefusal("LOADER_RECEIPT_MISSING", "authority_scope must be MECHANICS_CANARY_ONLY")
    if manifest.get("canary_id") != "EVAL-CANARY-IMAGE-V1":
        raise ValueError("unexpected canary identity")
    validate_manifest(fixture_root, manifest)

    config_path = fixture_root / str(manifest["config"]["file"])
    config_raw = config_path.read_bytes()
    if sha256_bytes(config_raw) != manifest["config"]["sha256"]:
        raise ValueError("config identity mismatch")
    config_payload = json.loads(config_raw)
    config = RestartDecoderConfig.small_for_tests(
        hidden_size=int(config_payload["hidden_size"]),
        layers=int(config_payload["layers"]),
        attention_heads=int(config_payload["attention_heads"]),
        vocab_size=int(config_payload["vocab_size"]),
        gradient_checkpointing=bool(config_payload["gradient_checkpointing"]),
    )

    tokenizer_path = ROOT / str(manifest["tokenizer"]["file"])
    tokenizer_raw = tokenizer_path.read_bytes()
    if sha256_bytes(tokenizer_raw) != manifest["tokenizer"]["sha256"]:
        raise ValueError("tokenizer identity mismatch")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    if tokenizer.get_vocab_size() != config.vocab_size or manifest["tokenizer"]["vocab_size"] != config.vocab_size:
        raise ValueError("config and real tokenizer vocabularies differ")

    checkpoint_path = fixture_root / str(manifest["checkpoint"]["file"])
    checkpoint_raw = checkpoint_path.read_bytes()
    if sha256_bytes(checkpoint_raw) != manifest["checkpoint"]["sha256"]:
        raise CanaryRefusal("CHECKPOINT_FILE_IDENTITY_MISMATCH_IDENTICAL_TENSORS", "checkpoint file hash differs")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    state_dict = checkpoint.get("state_dict")
    if not isinstance(state_dict, dict):
        raise ValueError("checkpoint state_dict missing")
    observed_hashes = {name: canonical_tensor_hash(name, tensor) for name, tensor in sorted(state_dict.items())}
    if observed_hashes != manifest["checkpoint"]["tensor_hashes"]:
        raise CanaryRefusal("CHECKPOINT_TENSOR_IDENTITY_MISMATCH", "canonical tensor hashes differ")
    model = UnifiedDecoder(config, genesis_seed=int(checkpoint["genesis_seed"])).eval()
    model.load_state_dict(state_dict, strict=True)
    return manifest, config, model, tokenizer


def positive_receipt(
    fixture_root: Path,
    *,
    manifest_override: dict[str, object] | None = None,
    caller_prediction_case: str | None = None,
    use_gold_as_prediction: bool = False,
    image_path_enabled: bool = True,
    emit_loader_receipt: bool = True,
    skip_all: bool = False,
) -> dict[str, object]:
    if not emit_loader_receipt:
        raise CanaryRefusal("LOADER_RECEIPT_MISSING", "loader receipt emission is mandatory")
    if caller_prediction_case is not None:
        raise CanaryRefusal("CALLER_PREDICTION_FORBIDDEN", f"{caller_prediction_case} prediction entered the call")
    if use_gold_as_prediction:
        raise CanaryRefusal("GOLD_SUBSTITUTION_FORBIDDEN", "gold cannot enter prediction construction")
    if not image_path_enabled:
        raise CanaryRefusal("IMAGE_PATH_DISABLED", "real raw-image path was disabled")
    if skip_all:
        raise CanaryRefusal("SKIPPED_ALL", "all items were skipped")
    manifest, config, model, tokenizer = load_positive(fixture_root, manifest_override=manifest_override)
    prompt_ids = tokenizer.encode("classify image parity as 0 or 1").ids
    if not prompt_ids:
        raise ValueError("real tokenizer produced an empty prompt")
    zero_id = tokenizer.token_to_id("0")
    one_id = tokenizer.token_to_id("1")
    if zero_id is None or one_id is None or zero_id == one_id:
        raise ValueError("real tokenizer must provide distinct 0 and 1 label tokens")
    rows: list[dict[str, object]] = []
    decoded_image_shapes: list[list[int]] = []
    for item in manifest["items"]:
        asset_path = fixture_root / str(item["asset"])
        asset_raw = asset_path.read_bytes()
        if sha256_bytes(asset_raw) != item["asset_sha256"]:
            raise ValueError("image payload identity mismatch")
        patches = read_ppm(asset_path)
        decoded_image_shapes.append(list(patches.shape))
        input_ids = torch.tensor([[config.image_token_id, *prompt_ids]], dtype=torch.long)
        logits = model(
            input_ids,
            image_patches=patches,
            image_coordinates=torch.tensor([[0, 0]], dtype=torch.long),
            spans=[MultimodalSpan(start=0, length=1, modality="image", attention_mode="isolated")],
            active_expert="vision",
        )
        raw_logits = logits[0, -1].detach().cpu().contiguous()
        prediction = "even" if float(raw_logits[zero_id]) >= float(raw_logits[one_id]) else "odd"
        rows.append(
            {
                "asset_sha256": item["asset_sha256"],
                "checkpoint_sha256": manifest["checkpoint"]["sha256"],
                "gold_label": item["gold_label"],
                "input_sha256": sha256_bytes(
                    json.dumps(
                        {"asset_sha256": item["asset_sha256"], "prompt_ids": input_ids.tolist()},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ),
                "item_id": item["item_id"],
                "pathway_event": "real_raw_image_adapter",
                "postprocessor": "compare_real_tokenizer_ids:0,1",
                "prediction": prediction,
                "raw_logits_sha256": canonical_tensor_hash(f"{item['item_id']}.raw_logits", raw_logits),
                "scorer": "exact_match",
            }
        )
    correct = sum(int(row["prediction"] == row["gold_label"]) for row in rows)
    return {
        "authority_scope": manifest["authority_scope"],
        "canary_id": manifest["canary_id"],
        "items": rows,
        "loader": {
            "adapter_class": RawPatchProjector.__name__,
            "checkpoint_sha256": manifest["checkpoint"]["sha256"],
            "checkpoint_file_identity_match": True,
            "checkpoint_tensor_identity_match": True,
            "config_sha256": manifest["config"]["sha256"],
            "decoded_image_shapes": decoded_image_shapes,
            "device": "cpu",
            "exclusions": ["capability_credit", "model_admission", "milestone_credit"],
            "fixture_seed": manifest["seed"],
            "item_order": [item["item_id"] for item in manifest["items"]],
            "model_class": UnifiedDecoder.__name__,
            "preprocessing": "binary_p6_ppm_to_uint8_rgb_then_model_normalization",
            "prompt_ids_sha256": sha256_bytes(json.dumps(prompt_ids, separators=(",", ":")).encode("utf-8")),
            "python": sys.version.split()[0],
            "source_commit": os.environ.get("GITHUB_SHA"),
            "tokenizer_sha256": manifest["tokenizer"]["sha256"],
            "tokenizers": tokenizers_version,
            "torch": torch.__version__,
            "weights_only": True,
        },
        "result": "PASS",
        "schema_version": "ember-eval-canary-image-receipt-v1",
        "score": {"accuracy": correct / 8, "correct": correct, "item_count": 8},
    }


def negative_matrix_report(fixture_root: Path) -> dict[str, object]:
    control = positive_receipt(fixture_root)
    control_raw = json.dumps(control, sort_keys=True, separators=(",", ":")).encode("utf-8")
    control_sha256 = sha256_bytes(control_raw)
    base_manifest = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []

    for row_class, subcase in NEGATIVE_ROWS:
        manifest = copy.deepcopy(base_manifest)
        options: dict[str, object] = {}
        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        identical_tensor_proof = False
        mutated_tensor_identity_differs = False
        mutated_checkpoint_sha256: str | None = None
        if row_class == "LOADER_RECEIPT_MISSING":
            options["emit_loader_receipt"] = False
        elif row_class == "CHECKPOINT_TENSOR_IDENTITY_MISMATCH":
            temp_dir = tempfile.TemporaryDirectory()
            alternate = Path(temp_dir.name) / "checkpoint-mutated.pt"
            original = torch.load(
                fixture_root / str(manifest["checkpoint"]["file"]),
                map_location="cpu",
                weights_only=True,
            )
            alternate_state = {
                name: tensor.clone() for name, tensor in original["state_dict"].items()
            }
            first_name = sorted(alternate_state)[0]
            first_bytes = alternate_state[first_name].view(torch.uint8).reshape(-1)
            first_bytes[0] = first_bytes[0] ^ 1
            torch.save({**original, "state_dict": alternate_state}, alternate)
            mutated_checkpoint_sha256 = sha256_bytes(alternate.read_bytes())
            alternate_hashes = {
                name: canonical_tensor_hash(name, tensor)
                for name, tensor in sorted(alternate_state.items())
            }
            mutated_tensor_identity_differs = (
                alternate_hashes != manifest["checkpoint"]["tensor_hashes"]
            )
            if not mutated_tensor_identity_differs:
                raise RuntimeError("mutated checkpoint negative retained tensor identity")
            manifest["checkpoint"]["file"] = str(alternate)
            manifest["checkpoint"]["sha256"] = mutated_checkpoint_sha256
        elif row_class == "CHECKPOINT_FILE_IDENTITY_MISMATCH_IDENTICAL_TENSORS":
            temp_dir = tempfile.TemporaryDirectory()
            alternate = Path(temp_dir.name) / "checkpoint-legacy.pt"
            original = torch.load(
                fixture_root / str(manifest["checkpoint"]["file"]),
                map_location="cpu",
                weights_only=True,
            )
            torch.save(original, alternate, _use_new_zipfile_serialization=False)
            mutated_checkpoint_sha256 = sha256_bytes(alternate.read_bytes())
            alternate_state = torch.load(alternate, map_location="cpu", weights_only=True)["state_dict"]
            alternate_hashes = {
                name: canonical_tensor_hash(name, tensor) for name, tensor in sorted(alternate_state.items())
            }
            identical_tensor_proof = alternate_hashes == manifest["checkpoint"]["tensor_hashes"]
            if not identical_tensor_proof:
                raise RuntimeError("re-serialized checkpoint negative lost tensor identity")
            manifest["checkpoint"]["file"] = str(alternate)
        elif row_class == "CALLER_PREDICTION_FORBIDDEN":
            options["caller_prediction_case"] = subcase
        elif row_class == "GOLD_SUBSTITUTION_FORBIDDEN":
            options["use_gold_as_prediction"] = True
        elif row_class == "IMAGE_PAYLOAD_MISSING":
            manifest["items"][0]["asset"] = "missing-image.ppm"
        elif row_class == "IMAGE_PAYLOAD_IDENTITY_MISMATCH":
            manifest["items"][0]["asset_sha256"] = "0" * 64
        elif row_class == "ITEM_SET_INCOMPLETE":
            manifest["items"] = manifest["items"][:-1]
        elif row_class == "ITEM_ORDER_MISMATCH":
            manifest["items"][0], manifest["items"][1] = manifest["items"][1], manifest["items"][0]
        elif row_class == "DUPLICATE_ITEM_ID":
            manifest["items"][1]["item_id"] = manifest["items"][0]["item_id"]
        elif row_class == "DECLARED_DELETION_PATH_ACTIVE":
            manifest["declared_deletion_paths"] = [manifest["items"][0]["asset"]]
        elif row_class == "IMAGE_PATH_DISABLED":
            options["image_path_enabled"] = False
        elif row_class == "ZERO_ITEMS":
            manifest["items"] = []
        elif row_class == "SKIPPED_ALL":
            options["skip_all"] = True

        mutation_description = {
            "row_class": row_class,
            "subcase": subcase,
            "manifest": manifest if row_class != "CHECKPOINT_FILE_IDENTITY_MISMATCH_IDENTICAL_TENSORS" else base_manifest,
            "options": options,
            "mutated_checkpoint_sha256": mutated_checkpoint_sha256,
            "mutated_tensor_identity_differs": mutated_tensor_identity_differs,
        }
        mutated_sha256 = sha256_bytes(
            json.dumps(mutation_description, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        try:
            positive_receipt(fixture_root, manifest_override=manifest, **options)
        except CanaryRefusal as error:
            if error.row_class != row_class:
                raise RuntimeError(f"{row_class} fired wrong class {error.row_class}") from error
            rows.append(
                {
                    "control_positive_sha256": control_sha256,
                    **(
                        {
                            "authority_checkpoint_sha256": base_manifest["checkpoint"]["sha256"],
                            "mutated_checkpoint_sha256": mutated_checkpoint_sha256,
                        }
                        if mutated_checkpoint_sha256 is not None
                        else {}
                    ),
                    **({"identical_tensor_proof": identical_tensor_proof} if identical_tensor_proof else {}),
                    **(
                        {"mutated_tensor_identity_differs": True}
                        if mutated_tensor_identity_differs
                        else {}
                    ),
                    "mutated_input_sha256": mutated_sha256,
                    "observed_error": error.row_class,
                    "result": "REFUSED",
                    "row_class": row_class,
                    **({"subcase": subcase} if subcase else {}),
                }
            )
        else:
            raise RuntimeError(f"negative matrix row unexpectedly accepted: {row_class}:{subcase}")
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()
    return {"schema_version": "ember-eval-canary-negative-matrix-v1", "result": "PASS", "rows": rows}


def terminal_suite_receipt(
    fixture_root: Path,
    *,
    torch_wheel_filename: str,
    torch_wheel_sha256: str,
) -> dict[str, object]:
    if not torch_wheel_filename or Path(torch_wheel_filename).name != torch_wheel_filename:
        raise ValueError("torch wheel filename must be one basename")
    if len(torch_wheel_sha256) != 64 or any(character not in "0123456789abcdef" for character in torch_wheel_sha256):
        raise ValueError("torch wheel sha256 must be lowercase hexadecimal")
    started_ns = time.perf_counter_ns()
    started_utc = time.time_ns()
    positive = positive_receipt(fixture_root)
    negative_matrix = negative_matrix_report(fixture_root)
    positive_sha256 = sha256_bytes(json.dumps(positive, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    negative_control_hashes = {row["control_positive_sha256"] for row in negative_matrix["rows"]}
    if negative_control_hashes != {positive_sha256}:
        raise RuntimeError("positive receipt did not reproduce byte-for-byte inside the negative-matrix process")
    stopped_utc = time.time_ns()
    measured_wall_seconds = (time.perf_counter_ns() - started_ns) / 1_000_000_000
    receipt: dict[str, object] = {
        "authority_scope": "MECHANICS_CANARY_ONLY",
        "canary_id": "EVAL-CANARY-IMAGE-V1",
        "dependencies": {
            "python": sys.version.split()[0],
            "tokenizers": tokenizers_version,
            "torch": torch.__version__,
            "torch_wheel_filename": torch_wheel_filename,
            "torch_wheel_sha256": torch_wheel_sha256,
        },
        "environment": {
            "ci": os.environ.get("CI") == "true",
            "device": "cpu",
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
        },
        "fixture_manifest_sha256": sha256_bytes((fixture_root / "manifest.json").read_bytes()),
        "measured_wall_seconds": measured_wall_seconds,
        "negative_matrix": negative_matrix,
        "negative_control_positive_sha256": positive_sha256,
        "positive": positive,
        "positive_sha256": positive_sha256,
        "result": "PASS",
        "schema_version": "ember-eval-canary-image-terminal-v1",
        "started_unix_ns": started_utc,
        "stopped_unix_ns": stopped_utc,
        "source_hashes": {
            "build_fixture.py": sha256_bytes((fixture_root / "build_fixture.py").read_bytes()),
            "checkpoint.pt": sha256_bytes((fixture_root / "checkpoint.pt").read_bytes()),
            "config.json": sha256_bytes((fixture_root / "config.json").read_bytes()),
            "eval_canary_image.py": sha256_bytes(Path(__file__).read_bytes()),
            "mechanics-only-dispositions.json": sha256_bytes((fixture_root / "mechanics-only-dispositions.json").read_bytes()),
            "model.py": sha256_bytes((Path(__file__).parent / "model.py").read_bytes()),
            "tokenizer.json": sha256_bytes((ROOT / "tokenizer" / "tokenizer.json").read_bytes()),
        },
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt["self_sha256"] = sha256_bytes(canonical)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-negative-matrix", action="store_true")
    mode.add_argument("--run-positive", action="store_true")
    mode.add_argument("--run-suite", action="store_true")
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--torch-wheel-filename")
    parser.add_argument("--torch-wheel-sha256")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.run_suite:
        if args.terminal_receipt is None or args.torch_wheel_filename is None or args.torch_wheel_sha256 is None:
            raise SystemExit("--run-suite requires --terminal-receipt, --torch-wheel-filename, and --torch-wheel-sha256")
        report = terminal_suite_receipt(
            args.fixture_root,
            torch_wheel_filename=args.torch_wheel_filename,
            torch_wheel_sha256=args.torch_wheel_sha256,
        )
        payload = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
        args.terminal_receipt.write_text(payload, encoding="utf-8", newline="\n")
        print(payload, end="")
    else:
        report = negative_matrix_report(args.fixture_root) if args.run_negative_matrix else positive_receipt(args.fixture_root)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
