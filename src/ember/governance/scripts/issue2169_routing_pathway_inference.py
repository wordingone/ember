#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2169: produce the E-MATRIX-ROUTING-PATHWAY receipt from real checkpoint inference.

The designated release-candidate checkpoint decodes each of the 192 frozen items of the #2169
protected routing-pathway contract TWICE: once with `active_expert` set to the item's required
pathway, and once with its control pathway (`shared`), which is the deletion control. Path events
are recorded from the model itself while it runs, and the per-item verdict is
`pathway_match AND engaged`:

  pathway_match  every decoder layer took the branch the item declares -- for an expert pathway,
                 one execution of that expert per layer and of no other expert; for `shared`,
                 zero expert executions anywhere.
  engaged        the required pass and the control pass produced DIFFERENT predictions. If deleting
                 the expert changes nothing, the expert was not doing anything for that item, and
                 the item does not count.

Claim boundary: this unit produces the engagement rate and claims nothing about it. A high rate
means declared pathways execute and matter; it is not a capability, threshold, release, campaign or
goal claim, and it is not a statement that the expert's contribution is correct.

Two independent event sources, deliberately
-------------------------------------------
A pre-hook on each `_DecoderLayer` records the `active_expert` argument the layer was CALLED with;
a forward hook on each expert module records that the expert module actually RAN. The first is a
declaration, the second is execution. `pathway_match` requires them to agree, so a future refactor
that passes an expert name without routing through it -- or routes through one it was not given --
fails the check instead of being invisible to it. The issue's minimum was the declaration alone;
observing only the argument would let the instrument report a pathway the model never took.

Subcommands:
  produce  real inference (CUDA) -> receipt      (the governed producer)
  verify   re-derive a receipt's verdicts        (the adapter's authoritative scorer, standalone)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import types
from pathlib import Path
from typing import Any, Callable

RECEIPT_SCHEMA = "ember-routing-pathway-inference-receipt-v1"
CONTRACT_SCHEMA = "protected-routing-pathway-contract-v1"
SOURCE_CONTRACT_SCHEMA = "ember-issue1947-protected-tool-use-contract-v1"
DESIGNATION_SCHEMA = "ember-issue1947-release-candidate-checkpoint-designation-v1"
CONNECTOR_SCHEMA = "corpus-connector-receipt-v1"
ITEM_COUNT = 192
SHARED_SHARD = "shared-model.pt"
RESULT_PASS = "ROUTING_PATHWAY_INFERENCE_PASS"
SHARED = "shared"

# The decode contract is #2162's, unchanged and re-derived from the contract's own binding. The one
# field this unit varies is `active_expert`, which is exactly what it is measuring.
DECODE_FIELDS_VARIED = ("active_expert",)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def self_hash(document: dict[str, Any], field: str = "self_sha256") -> str:
    return sha(canonical({key: value for key, value in document.items() if key != field}))


def load_self_hashed(path: Path, schema: str, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    if document.get("schema_version") != schema:
        raise ValueError(f"{label}_SCHEMA_REFUSED:{document.get('schema_version')}")
    recorded = document.get("self_sha256")
    computed = self_hash(document)
    if recorded != computed:
        raise ValueError(f"{label}_SELF_HASH_REFUSED: recorded {recorded} computed {computed}")
    return document, raw


# ---------------------------------------------------------------------------------------------
# Contract, source prompts, checkpoint designation
# ---------------------------------------------------------------------------------------------

def load_contract(path: Path) -> dict[str, Any]:
    contract, _ = load_self_hashed(path, CONTRACT_SCHEMA, "ROUTING_PATHWAY_CONTRACT")
    items = contract.get("items")
    if not isinstance(items, list) or len(items) != ITEM_COUNT:
        raise ValueError(f"ROUTING_PATHWAY_CONTRACT_TOTALITY_REFUSED:{len(items) if isinstance(items, list) else 'absent'}")
    order = sha(canonical([item["item_id"] for item in items]))
    if contract.get("frozen_order_sha256") != order:
        raise ValueError("ROUTING_PATHWAY_CONTRACT_ORDER_REFUSED")
    return contract


def load_source_contract(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """The single contract every prompt in the routing contract came from.

    Both declared slices were substituted at mint time -- the reasoning contract's items carry the
    ANSWER rather than a prompt, and the text-language row is a single-item identity row -- so all
    192 prompts are tool-use prompts. The substitutions are recorded in the contract and are
    re-checked here rather than trusted, because a substitution that is not verified at use time is
    a claim about provenance with nothing behind it.
    """
    source, _ = load_self_hashed(path, SOURCE_CONTRACT_SCHEMA, "ROUTING_PATHWAY_SOURCE_CONTRACT")
    expected = contract.get("sources", {}).get("tool_use_contract_self_sha256")
    if source.get("self_sha256") != expected:
        raise ValueError(f"ROUTING_PATHWAY_SOURCE_BINDING_REFUSED: contract names {expected}")
    declared = {item["source_contract_self_sha256"] for item in contract["items"]}
    if declared != {expected}:
        raise ValueError(f"ROUTING_PATHWAY_SOURCE_BINDING_REFUSED: items name {sorted(declared)}")
    return source


def source_items_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    frozen = source.get("frozen_items")
    if not isinstance(frozen, list):
        raise ValueError("ROUTING_PATHWAY_SOURCE_ITEMS_REFUSED")
    return {item["item_id"]: item for item in frozen}


def load_designation(path: Path, manifest_path: Path) -> tuple[dict[str, Any], str]:
    designation, _ = load_self_hashed(path, DESIGNATION_SCHEMA, "ROUTING_PATHWAY_DESIGNATION")
    manifest_sha = sha_file(manifest_path)
    identity = designation.get("checkpoint_identity")
    recorded = identity.get("manifest_raw_sha256") if isinstance(identity, dict) else None
    if recorded is None:
        recorded = designation.get("checkpoint_manifest_raw_sha256")
    if recorded != manifest_sha:
        raise ValueError(f"ROUTING_PATHWAY_CHECKPOINT_BINDING_REFUSED: designation {recorded} manifest {manifest_sha}")
    return designation, manifest_sha


def load_connector_payloads(receipt_paths: list[Path]) -> dict[str, Path]:
    """sha256 -> physical path, from the same connector receipts #2162 reads.

    Only the digest is trusted: each candidate file is hashed before it is admitted to the map, so a
    receipt row that points at replaced bytes drops out here rather than reaching a prompt.
    """
    by_sha: dict[str, Path] = {}
    for receipt_path in receipt_paths:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("schema_version") != CONNECTOR_SCHEMA:
            raise ValueError(f"ROUTING_PATHWAY_CONNECTOR_SCHEMA_REFUSED:{receipt_path}")
        root_value = receipt.get("root") or receipt.get("root_path")
        if not root_value:
            raise ValueError(f"ROUTING_PATHWAY_CONNECTOR_ROOT_REFUSED:{receipt_path}")
        root = Path(root_value)
        for row in receipt.get("objects", []) or receipt.get("rows", []):
            digest = row.get("sha256")
            relative = row.get("path")
            if not digest or not relative:
                continue
            physical = (root / Path(relative)).resolve()
            if digest in by_sha or not physical.is_file():
                continue
            by_sha[digest] = physical
    return by_sha


def prompt_bytes(by_sha: dict[str, Path], digest: str, item_id: str) -> bytes:
    physical = by_sha.get(digest)
    if physical is None:
        raise ValueError(f"ROUTING_PATHWAY_PROMPT_UNRESOLVED:{item_id}:{digest}")
    raw = physical.read_bytes()
    if sha(raw) != digest:
        raise ValueError(f"ROUTING_PATHWAY_PROMPT_INTEGRITY_REFUSED:{item_id}:{digest}")
    return raw


# ---------------------------------------------------------------------------------------------
# Path events
# ---------------------------------------------------------------------------------------------

class PathEventRecorder:
    """Records, per pass, what every decoder layer was asked to do and what actually ran.

    `declared` comes from the argument each layer received; `executed` comes from the expert module
    firing its own forward hook. They are kept apart on purpose -- agreement between them is the
    evidence, and folding them into one list would destroy exactly the disagreement worth catching.
    """

    def __init__(self) -> None:
        self.item_id: str | None = None
        self.pass_name: str | None = None
        self.declared: list[dict[str, Any]] = []
        self.executed: list[dict[str, Any]] = []
        self._enabled = False

    def begin(self, item_id: str, pass_name: str) -> None:
        self.item_id, self.pass_name = item_id, pass_name
        self.declared, self.executed = [], []
        self._enabled = True

    def end(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        self._enabled = False
        return self.declared, self.executed

    def install(self, model: Any) -> list[Any]:
        handles = []
        for index, layer in enumerate(model.layers):
            handles.append(layer.register_forward_pre_hook(self._layer_hook(index)))
            for name, expert in layer.experts.items():
                handles.append(expert.register_forward_hook(self._expert_hook(index, name)))
        return handles

    def _layer_hook(self, index: int) -> Callable[..., None]:
        def hook(_module: Any, args: tuple[Any, ...]) -> None:
            if not self._enabled:
                return
            active = args[3] if len(args) > 3 else None
            branch = "shared_only" if active == SHARED else f"expert:{active}"
            self.declared.append({"item_id": self.item_id, "pass": self.pass_name,
                                  "layer_index": index, "branch": branch})
        return hook

    def _expert_hook(self, index: int, name: str) -> Callable[..., None]:
        def hook(_module: Any, _args: Any, _output: Any) -> None:
            if not self._enabled:
                return
            self.executed.append({"item_id": self.item_id, "pass": self.pass_name,
                                  "layer_index": index, "branch": f"expert:{name}"})
        return hook


def summarize_events(declared: list[dict[str, Any]], executed: list[dict[str, Any]],
                     *, pathway: str, layers: int, decode_steps: int) -> dict[str, Any]:
    """Reduce one pass's raw events to the per-pass record.

    A greedy decode calls the model once per generated token, so each layer fires `decode_steps`
    times. Counts are therefore reported per decode step -- an absolute count would encode the
    length of the generation, which varies per item and says nothing about routing.
    """
    expected_declared = layers * decode_steps
    branches = {event["branch"] for event in declared}
    per_step_declared = len(declared) / decode_steps if decode_steps else 0.0
    executed_names = {event["branch"] for event in executed}
    per_step_expert = len(executed) / decode_steps if decode_steps else 0.0
    return {
        "events_sha256": sha(canonical({"declared": declared, "executed": executed})),
        "declared_event_count": len(declared),
        "declared_branches": sorted(branches),
        "declared_layers_per_step": per_step_declared,
        "declared_complete": len(declared) == expected_declared,
        "executed_expert_event_count": len(executed),
        "executed_expert_names": sorted({name.split(":", 1)[1] for name in executed_names}),
        "layers_with_expert": per_step_expert,
        "expert_name": None if pathway == SHARED else pathway,
        "decode_steps": decode_steps,
    }


def pathway_match(summary: dict[str, Any], *, pathway: str, layers: int) -> bool:
    """Declaration and execution both say this pathway, at every layer, and nothing else did."""
    if not summary["declared_complete"]:
        return False
    if pathway == SHARED:
        return (summary["declared_branches"] == ["shared_only"]
                and summary["executed_expert_event_count"] == 0)
    return (summary["declared_branches"] == [f"expert:{pathway}"]
            and summary["executed_expert_names"] == [pathway]
            and abs(summary["layers_with_expert"] - layers) < 1e-9)


# ---------------------------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------------------------

Emitter = Callable[[str, str, str], dict[str, Any]]
"""emit(prompt_text, item_id, pathway) -> {"prediction_sha256", "generated_token_count",
"stop_reason", "declared_events", "executed_events"}. Tests inject a stub; the real emitter is
`build_real_emitter`. The emitter never sees another item's record or any verdict."""


def run_pass(contract: dict[str, Any], source_items: dict[str, dict[str, Any]],
             by_sha: dict[str, Path], emit: Emitter, *, layers: int,
             progress: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for position, item in enumerate(contract["items"]):
        item_id = item["item_id"]
        source_item = source_items.get(item["source_item_id"])
        if source_item is None:
            raise ValueError(f"ROUTING_PATHWAY_SOURCE_ITEM_ABSENT:{item['source_item_id']}")
        digest = source_item["prompt_object"]["sha256"]
        if digest != item["prompt_sha256"]:
            raise ValueError(f"ROUTING_PATHWAY_PROMPT_BINDING_REFUSED:{item_id}")
        prompt_text = prompt_bytes(by_sha, digest, item_id).decode("utf-8")
        required = item["required_pathway"]
        control = item.get("control_pathway")

        started = time.monotonic()
        required_emitted = emit(prompt_text, item_id, required)
        required_summary = summarize_events(
            required_emitted["declared_events"], required_emitted["executed_events"],
            pathway=required, layers=layers, decode_steps=int(required_emitted["generated_token_count"]))
        required_record = {
            "prediction_sha256": required_emitted["prediction_sha256"],
            "generated_token_count": int(required_emitted["generated_token_count"]),
            "stop_reason": str(required_emitted["stop_reason"]),
            **required_summary,
        }

        control_record = None
        if control is not None:
            control_emitted = emit(prompt_text, item_id, control)
            control_summary = summarize_events(
                control_emitted["declared_events"], control_emitted["executed_events"],
                pathway=control, layers=layers, decode_steps=int(control_emitted["generated_token_count"]))
            control_record = {
                "prediction_sha256": control_emitted["prediction_sha256"],
                "generated_token_count": int(control_emitted["generated_token_count"]),
                "stop_reason": str(control_emitted["stop_reason"]),
                **control_summary,
            }

        matched = pathway_match(required_summary, pathway=required, layers=layers)
        if control_record is not None:
            matched = matched and pathway_match(control_summary, pathway=control, layers=layers)
            engaged: Any = required_record["prediction_sha256"] != control_record["prediction_sha256"]
        else:
            engaged = "not_applicable"

        record = {
            "position": position,
            "item_id": item_id,
            "prompt_sha256": digest,
            "source_item_id": item["source_item_id"],
            "required_pathway": required,
            "control_pathway": control,
            "required_pass": required_record,
            "control_pass": control_record,
            "pathway_match": bool(matched),
            "engaged": engaged,
            "scored": bool(matched) and (engaged is True or engaged == "not_applicable"),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        records.append(record)
        if progress is not None:
            progress(record)
    return records


def tally(records: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "item_count": len(records),
        "pathway_match_count": sum(1 for record in records if record["pathway_match"]),
        "engaged_count": sum(1 for record in records if record["engaged"] is True),
        "engagement_not_applicable_count": sum(1 for record in records if record["engaged"] == "not_applicable"),
        "scored_count": sum(1 for record in records if record["scored"]),
    }


# ---------------------------------------------------------------------------------------------
# The authoritative scorer: recompute every verdict from the recorded evidence
# ---------------------------------------------------------------------------------------------

def verify_receipt(receipt_path: Path, contract_path: Path, *,
                   expected_checkpoint_manifest_sha256: str | None = None) -> dict[str, Any]:
    """Re-derive every per-item verdict from what the receipt itself recorded.

    The producer's `scored_count` is advisory. This function is the authority, and it recomputes
    from the predictions and the event summaries rather than reading the producer's booleans --
    a verifier that reads the number it is checking cannot fail.
    """
    receipt, receipt_raw = load_self_hashed(receipt_path, RECEIPT_SCHEMA, "ROUTING_PATHWAY_RECEIPT")
    contract_raw = contract_path.read_bytes()
    contract = load_contract(contract_path)
    if receipt.get("contract_self_sha256") != contract["self_sha256"]:
        raise ValueError("ROUTING_PATHWAY_CONTRACT_BINDING_REFUSED")
    if expected_checkpoint_manifest_sha256 is not None and \
            receipt.get("checkpoint_manifest_raw_sha256") != expected_checkpoint_manifest_sha256:
        raise ValueError("ROUTING_PATHWAY_CHECKPOINT_BINDING_REFUSED")

    records = receipt.get("records")
    if not isinstance(records, list) or len(records) != ITEM_COUNT:
        raise ValueError(f"ROUTING_PATHWAY_TOTALITY_REFUSED:{len(records) if isinstance(records, list) else 'absent'}")
    layers = int(receipt["layers"])

    recomputed = 0
    items: list[dict[str, Any]] = []
    for position, (record, item) in enumerate(zip(records, contract["items"])):
        if record.get("position") != position or record.get("item_id") != item["item_id"]:
            raise ValueError(f"ROUTING_PATHWAY_ORDER_REFUSED:{position}")
        if record.get("prompt_sha256") != item["prompt_sha256"] or \
                record.get("required_pathway") != item["required_pathway"] or \
                record.get("control_pathway") != item.get("control_pathway"):
            raise ValueError(f"ROUTING_PATHWAY_ORDER_REFUSED:{position}:binding")

        required = record["required_pass"]
        control = record.get("control_pass")
        # Event identity: every summarized pass must belong to this item, and a control prediction
        # copied over its required prediction is the fabrication this check exists to catch.
        if required.get("expert_name") not in (None, item["required_pathway"]):
            raise ValueError(f"ROUTING_PATHWAY_EVENT_IDENTITY_REFUSED:{record['item_id']}")
        matched = pathway_match(required, pathway=item["required_pathway"], layers=layers)
        if control is not None:
            matched = matched and pathway_match(control, pathway=item["control_pathway"], layers=layers)
            engaged: Any = required["prediction_sha256"] != control["prediction_sha256"]
        else:
            engaged = "not_applicable"
        if record.get("engaged") != engaged or bool(record.get("pathway_match")) != bool(matched):
            raise ValueError(f"ROUTING_PATHWAY_SCORE_MISMATCH_REFUSED:{record['item_id']}")
        scored = bool(matched) and (engaged is True or engaged == "not_applicable")
        if scored:
            recomputed += 1
        items.append({
            "position": position,
            "item_id": record["item_id"],
            "required_pathway": item["required_pathway"],
            "control_pathway": item.get("control_pathway"),
            "pathway_match": bool(matched),
            "engaged": engaged,
            "scored": scored,
        })

    if int(receipt.get("scored_count", -1)) != recomputed:
        raise ValueError(f"ROUTING_PATHWAY_SCORE_MISMATCH_REFUSED: receipt {receipt.get('scored_count')} recomputed {recomputed}")
    return {
        "result": RESULT_PASS,
        "receipt": receipt,
        "receipt_raw_sha256": sha(receipt_raw),
        "contract": contract,
        "contract_raw_sha256": sha(contract_raw),
        "items": items,
        "item_count": ITEM_COUNT,
        "pathway_match_count": sum(1 for row in items if row["pathway_match"]),
        "engaged_count": sum(1 for row in items if row["engaged"] is True),
        "scored_count": recomputed,
        "score": recomputed / ITEM_COUNT,
    }


# ---------------------------------------------------------------------------------------------
# The real emitter
# ---------------------------------------------------------------------------------------------

def _load_module_from_bytes(source: bytes, path: Path, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def build_real_emitter(args: argparse.Namespace, contract: dict[str, Any]) -> tuple[Emitter, dict[str, Any], str, int]:
    import torch
    from tokenizers import Tokenizer

    designation, manifest_sha = load_designation(args.designation, args.checkpoint_manifest)
    manifest = json.loads(args.checkpoint_manifest.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "ember-sparse-checkpoint-v5" or \
            manifest.get("architecture_revision") != "ember-sparse-3b-v2":
        raise ValueError("ROUTING_PATHWAY_CHECKPOINT_SCHEMA_REFUSED")
    if manifest.get("model_config_sha256") != sha_file(args.model_config):
        raise ValueError("ROUTING_PATHWAY_MODEL_CONFIG_BINDING_REFUSED")
    tokenizer_raw = args.tokenizer.read_bytes()
    tokenizer_sha = sha(tokenizer_raw)
    identity = designation.get("checkpoint_identity") if isinstance(designation.get("checkpoint_identity"), dict) else {}
    if identity.get("tokenizer_sha256") not in (None, tokenizer_sha):
        raise ValueError("ROUTING_PATHWAY_TOKENIZER_BINDING_REFUSED")

    # Every expert this contract names, plus the shared trunk. Both passes of every item run
    # against one loaded model, so the control differs from the required pass in the routing
    # argument and in nothing else.
    experts = sorted({item["required_pathway"] for item in contract["items"]} - {SHARED})
    shards = {record["path"]: record for record in manifest.get("shards", []) if isinstance(record, dict)}
    root = args.checkpoint_manifest.parent
    wanted = [SHARED_SHARD] + [f"expert-{name}.pt" for name in experts]
    for name in wanted:
        record = shards.get(name)
        path = root / name
        if record is None or not path.is_file() or path.stat().st_size != record.get("bytes") or \
                sha_file(path) != record.get("sha256"):
            raise ValueError(f"ROUTING_PATHWAY_SHARD_INTEGRITY_REFUSED:{name}")

    module = _load_module_from_bytes(args.model_source.read_bytes(), args.model_source, "ember_issue2169_model")
    config = module.RestartDecoderConfig.from_contract(args.model_config)
    device = torch.device(args.device)
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = module.UnifiedDecoder(config, device=device, allow_production_allocation=True)
    finally:
        torch.set_default_dtype(previous_dtype)

    expected = model.state_dict()
    plan = [(SHARED_SHARD, {key for key in expected if ".experts." not in key}, SHARED)]
    for name in experts:
        plan.append((f"expert-{name}.pt", {key for key in expected if f".experts.{name}." in key}, name))
    for shard_name, expected_keys, label in plan:
        payload = torch.load(root / shard_name, map_location="cpu", weights_only=True, mmap=True)
        state = payload.get("model") if isinstance(payload, dict) else None
        if not isinstance(state, dict) or set(state) != expected_keys:
            raise ValueError(f"ROUTING_PATHWAY_SHARD_STATE_REFUSED:{label}")
        if label != SHARED and payload.get("expert") != label:
            raise ValueError(f"ROUTING_PATHWAY_SHARD_STATE_REFUSED:{label}:expert_identity")
        for key, tensor in state.items():
            if tuple(tensor.shape) != tuple(expected[key].shape):
                raise ValueError(f"ROUTING_PATHWAY_SHARD_STATE_REFUSED:{label}:{key}")
        missing, unexpected = model.load_state_dict(
            {key: value.to(device=device, dtype=torch.bfloat16) for key, value in state.items()}, strict=False)
        if unexpected or any(key in expected_keys for key in missing):
            raise ValueError(f"ROUTING_PATHWAY_SHARD_STATE_REFUSED:{label}:load")
        del payload, state
    model.eval()

    recorder = PathEventRecorder()
    recorder.install(model)
    tokenizer = Tokenizer.from_str(tokenizer_raw.decode("utf-8"))
    decode = contract["decode_contract_binding"]
    eos = int(decode.get("eos_token_id", 0))
    limit = int(decode.get("max_new_tokens", 256))
    layers = int(config.layers)

    def emit(prompt_text: str, item_id: str, pathway: str) -> dict[str, Any]:
        prompt_ids = tokenizer.encode(prompt_text).ids
        if not prompt_ids or any(token >= config.vocab_size for token in prompt_ids):
            raise ValueError(f"ROUTING_PATHWAY_PROMPT_TOKENIZATION_REFUSED:{item_id}")
        tokens = torch.tensor([prompt_ids], device=device, dtype=torch.long)
        generated: list[int] = []
        stop_reason = "max_new_tokens"
        recorder.begin(item_id, pathway)
        with torch.no_grad():
            for _ in range(limit):
                logits = model(tokens, active_expert=pathway)
                token = int(torch.argmax(logits[:, -1, :], dim=-1).item())
                generated.append(token)
                if token == eos:
                    stop_reason = "eos_token"
                    break
                text = tokenizer.decode(generated)
                if ";" in text:
                    stop_reason = "first_semicolon_in_decoded_text"
                    break
                if "\n\n" in text:
                    stop_reason = "first_blank_line_in_decoded_text"
                    break
                tokens = torch.cat([tokens, torch.tensor([[token]], device=device, dtype=torch.long)], dim=1)
        declared, executed = recorder.end()
        return {
            "prediction_sha256": sha(canonical(generated)),
            "generated_token_count": len(generated),
            "stop_reason": stop_reason,
            "declared_events": declared,
            "executed_events": executed,
        }

    binding = {
        "checkpoint_manifest_raw_sha256": manifest_sha,
        "designation_self_sha256": designation["self_sha256"],
        "model_config_sha256": sha_file(args.model_config),
        "model_source_sha256": sha_file(args.model_source),
        "tokenizer_sha256": tokenizer_sha,
        "experts_loaded": experts,
        "device": str(device),
    }
    return emit, binding, manifest_sha, layers


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def command_produce(args: argparse.Namespace) -> int:
    contract = load_contract(args.contract)
    source = load_source_contract(args.source_contract, contract)
    source_items = source_items_by_id(source)
    by_sha = load_connector_payloads(args.connector_receipt)
    emit, binding, manifest_sha, layers = build_real_emitter(args, contract)

    started = time.time()

    def progress(record: dict[str, Any]) -> None:
        if record["position"] % 16 == 0 or record["position"] == ITEM_COUNT - 1:
            done = record["position"] + 1
            rate = (time.time() - started) / done
            print(f"  {done:3d}/{ITEM_COUNT}  {record['item_id']}  "
                  f"match={record['pathway_match']} engaged={record['engaged']} "
                  f"eta={(ITEM_COUNT - done) * rate / 60:.1f} min", flush=True)

    records = run_pass(contract, source_items, by_sha, emit, layers=layers, progress=progress)
    counts = tally(records)

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "issue": 2169,
        "result": RESULT_PASS,
        "contract_self_sha256": contract["self_sha256"],
        "frozen_order_sha256": contract["frozen_order_sha256"],
        "decode_contract_sha256": contract["decode_contract_sha256"],
        "checkpoint_manifest_raw_sha256": manifest_sha,
        "binding": binding,
        "layers": layers,
        "engagement_rule": contract["engagement_rule"],
        "varied_decode_fields": list(DECODE_FIELDS_VARIED),
        "records": records,
        "wall_seconds": round(time.time() - started, 1),
        **counts,
        "claim_boundary": ("PATHWAY ENGAGEMENT RATE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, "
                           "CAMPAIGN, OR GOAL CREDIT"),
    }
    receipt["self_sha256"] = self_hash(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    print(f"{RESULT_PASS} scored {counts['scored_count']}/{ITEM_COUNT} "
          f"(match {counts['pathway_match_count']}, engaged {counts['engaged_count']}, "
          f"n/a {counts['engagement_not_applicable_count']})")
    print(f"receipt {args.out} self {receipt['self_sha256']}")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    verdict = verify_receipt(args.receipt, args.contract,
                             expected_checkpoint_manifest_sha256=args.expect_checkpoint_manifest_sha256)
    print(json.dumps(verdict, indent=1, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    produce = sub.add_parser("produce")
    produce.add_argument("--contract", type=Path, required=True)
    produce.add_argument("--source-contract", type=Path, required=True)
    produce.add_argument("--connector-receipt", type=Path, action="append", required=True)
    produce.add_argument("--checkpoint-manifest", type=Path, required=True)
    produce.add_argument("--designation", type=Path, required=True)
    produce.add_argument("--model-source", type=Path, required=True)
    produce.add_argument("--model-config", type=Path, required=True)
    produce.add_argument("--tokenizer", type=Path, required=True)
    produce.add_argument("--out", type=Path, required=True)
    produce.add_argument("--device", default="cuda")
    produce.set_defaults(handler=command_produce)

    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--contract", type=Path, required=True)
    verify.add_argument("--expect-checkpoint-manifest-sha256", default=None)
    verify.set_defaults(handler=command_verify)

    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
