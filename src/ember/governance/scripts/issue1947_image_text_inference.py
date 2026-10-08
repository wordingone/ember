#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1947: produce and verify the E-MATRIX-IMAGE-TEXT model-prediction receipt.

The #2130 contract freezes 847 multiple-choice MMMU items and records the answer dictionary as an
identity only. That contract can score payload identity, never correctness. This module adds the
missing half on the #2162 pattern:

  answer contract  built ONCE by a sealed builder (owner ruling, mail 68732, 2026-10-07): it reads the answer
                   dictionary, checks its sha256 against the frozen identity, and writes one KEYED
                   digest per item, gold_answer_hmac = HMAC-SHA256(key, item_id || 0x00 || letter).
                   A plain sha256 of a letter is not sealed (four or five letters invert by lookup),
                   so the key is the seal. Only the builder and the verifier read the key.
  emission         the designated checkpoint answers each frozen item in frozen order under a frozen
                   decode contract; the emitter sees images + question + options, never gold or key.
  receipt          records what the model answered and nothing it was scored against: no gold, no
                   key, no per-item verdict. A receipt alone does not reveal a single answer.
  verify           holds the key, recomputes HMAC(key, item_id || 0x00 || predicted letter) per item
                   and compares it with the contract's gold digest. The row carries keyed digests on
                   both sides, so the row does not reveal answers either.

Claim boundary: totality of emission + receipt + keyed scoring. The correctness rate is a reported
number. A valid instrument with a below-floor model is a reportable outcome, not a refusal.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

ANSWER_CONTRACT_SCHEMA = "ember-issue1947-protected-image-text-answer-contract-v1"
BASE_CONTRACT_SCHEMA = "ember-protected-image-text-contract-v1"
RECEIPT_SCHEMA = "ember-image-text-inference-receipt-v2"
ROW_ID = "E-MATRIX-IMAGE-TEXT"
ITEM_COUNT = 847
RESULT_PASS = "IMAGE_TEXT_INFERENCE_PASS"
KEY_BYTES = 32
LETTERS = "ABCDEFGHIJ"
GOLD_DIGEST_RULE = "HMAC-SHA256(key, utf8(item_id) || 0x00 || utf8(uppercase letter))"
NEVER_READ_LIFT = {
    "ruling": "owner ruling, mail 68732",
    "date": "2026-10-07",
    "scope": "the sealed answer-contract builder only; the model, emitter, receipts and rows never hold a letter or the key",
}
# The public boundary (review of PR 2345, R1): a receipt carries no letter in any form -- not the gold
# letter, not the predicted letter, not an unkeyed digest of either or of the decoded text -- and no key.
# The pass harness (never the emitter) keys each prediction; the verifier refuses any field outside these sets.
RECEIPT_FIELDS = frozenset({
    "schema_version", "result", "row_id", "base_contract_raw_sha256", "answer_contract_raw_sha256",
    "answer_contract_self_sha256", "checkpoint_manifest_raw_sha256", "model_bindings", "decode_contract",
    "decode_contract_sha256", "frozen_order_sha256", "item_count", "parsed_count", "wall_seconds_total",
    "records", "claim_boundary", "self_sha256",
})
RECORD_FIELDS = frozenset({
    "position", "item_id", "image_sha256s", "item_text_sha256", "decoded_text_hmac", "prediction_hmac",
    "parsed", "prompt_token_count", "generated_token_count", "stop_reason", "elapsed_seconds",
})
MODEL_BINDING_VALUE_TYPES = (str, int, float, bool)

DECODE_CONTRACT: dict[str, Any] = {
    "strategy": "greedy_argmax",
    "temperature": 0,
    "sampling": False,
    "retries": 0,
    "batch": 1,
    "max_new_tokens": 16,
    "stop_rules": ["eos_token", "first_newline_in_decoded_text", "max_new_tokens"],
    "prompt": (
        "the item's images in column order, then the question, then one line per option "
        "'<LETTER>. <option>' in frozen option order, then 'Answer:'; no system prompt"
    ),
    "answer_extraction": (
        "the first standalone letter A..<option_count letter> in the decoded text, case-insensitive; "
        "none found = unparsed, scored as a miss, never a refusal of the pass"
    ),
    "parameter_dtype": "bfloat16",
}
CLAIM_BOUNDARY = (
    "EMISSION + RECEIPT + KEYED-SCORING TOTALITY ONLY; the correctness rate is a reported number; "
    "NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, EMBER-02, OR GOAL CREDIT"
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def decode_contract_sha256() -> str:
    return sha(canonical(DECODE_CONTRACT))


def frozen_order_sha256(item_ids: list[str]) -> str:
    return sha(canonical(item_ids))


def keyed_answer_digest(key: bytes, item_id: str, letter: str) -> str:
    if len(key) != KEY_BYTES:
        raise ValueError("IMAGE_TEXT_ANSWER_KEY_LENGTH_REFUSED")
    return hmac.new(key, item_id.encode("utf-8") + b"\x00" + letter.encode("utf-8"), hashlib.sha256).hexdigest()


def keyed_decoded_digest(key: bytes, item_id: str, decoded: str) -> str:
    # Domain-separated from the answer digest (0x01), so a decoded text equal to a bare letter never collides with it.
    if len(key) != KEY_BYTES:
        raise ValueError("IMAGE_TEXT_ANSWER_KEY_LENGTH_REFUSED")
    return hmac.new(key, item_id.encode("utf-8") + b"\x01" + decoded.encode("utf-8"), hashlib.sha256).hexdigest()


def load_self_hashed(path: Path, schema_version: str, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}_UNREADABLE_REFUSED") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        raise ValueError(f"{label}_SCHEMA_REFUSED")
    body = dict(payload)
    claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError(f"{label}_SELF_HASH_REFUSED")
    return payload, raw


def load_key(key_path: Path, expected_key_sha256: str) -> bytes:
    key = key_path.read_bytes()
    if len(key) != KEY_BYTES or sha(key) != expected_key_sha256:
        raise ValueError("IMAGE_TEXT_ANSWER_KEY_BINDING_REFUSED")
    return key


# ---------------------------------------------------------------------------------------------
# Sealed builder (owner: the custody holder). Reads the dictionary once, writes digests only.
# ---------------------------------------------------------------------------------------------

def build_answer_contract(
    *,
    base_contract_path: Path,
    answer_dictionary_path: Path,
    expected_answer_dictionary_sha256: str,
    key: bytes,
    option_counts: dict[str, int],
) -> dict[str, Any]:
    """`answer_dictionary_path` is a JSON object {item_id: letter}. Its raw sha256 must equal the
    identity the #2130 contract froze; any other dictionary is refused before a value is read.
    `option_counts` comes from the admitted item-text payloads, so a letter outside an item's own
    options refuses the build instead of minting an unreachable gold."""

    base, base_raw = load_self_hashed(base_contract_path, BASE_CONTRACT_SCHEMA, "IMAGE_TEXT_BASE_CONTRACT")
    frozen = base.get("frozen_items")
    if not isinstance(frozen, list) or len(frozen) != ITEM_COUNT:
        raise ValueError("IMAGE_TEXT_BASE_CONTRACT_TOTALITY_REFUSED")
    # The caller's digest is not the authority: the base contract's own frozen source identity is.
    source = base.get("source")
    if not isinstance(source, dict) or source.get("answer_dictionary_sha256") != expected_answer_dictionary_sha256:
        raise ValueError("IMAGE_TEXT_ANSWER_DICTIONARY_IDENTITY_REFUSED:base_source")
    dictionary_raw = answer_dictionary_path.read_bytes()
    if sha(dictionary_raw) != expected_answer_dictionary_sha256:
        raise ValueError("IMAGE_TEXT_ANSWER_DICTIONARY_IDENTITY_REFUSED")
    dictionary = json.loads(dictionary_raw)
    if not isinstance(dictionary, dict):
        raise ValueError("IMAGE_TEXT_ANSWER_DICTIONARY_SHAPE_REFUSED")
    items: list[dict[str, Any]] = []
    for item in frozen:
        item_id = item.get("item_id") if isinstance(item, dict) else None
        if not isinstance(item_id, str):
            raise ValueError("IMAGE_TEXT_BASE_CONTRACT_ITEM_SCHEMA_REFUSED")
        option_count = option_counts.get(item_id)
        if not isinstance(option_count, int) or not 2 <= option_count <= len(LETTERS):
            raise ValueError(f"IMAGE_TEXT_OPTION_COUNT_REFUSED:{item_id}")
        letter = dictionary.get(item_id)
        if not isinstance(letter, str) or letter not in LETTERS[:option_count]:
            raise ValueError(f"IMAGE_TEXT_ANSWER_LETTER_REFUSED:{item_id}")
        items.append({
            "item_id": item_id,
            "option_count": option_count,
            "gold_answer_hmac": keyed_answer_digest(key, item_id, letter),
        })
    contract: dict[str, Any] = {
        "schema_version": ANSWER_CONTRACT_SCHEMA,
        "result": "PASS",
        "row_id": ROW_ID,
        "base_contract_raw_sha256": sha(base_raw),
        "base_contract_self_sha256": base["self_sha256"],
        "answer_dictionary_sha256": expected_answer_dictionary_sha256,
        "answer_key_sha256": sha(key),
        "gold_digest_rule": GOLD_DIGEST_RULE,
        "never_read_lift": NEVER_READ_LIFT,
        "totality": {"expected": ITEM_COUNT, "observed": len(items), "complete": len(items) == ITEM_COUNT},
        "items": items,
    }
    contract["self_sha256"] = sha(canonical(contract))
    return contract


def load_answer_contract(answer_contract_path: Path, base_contract_path: Path) -> dict[str, Any]:
    base, base_raw = load_self_hashed(base_contract_path, BASE_CONTRACT_SCHEMA, "IMAGE_TEXT_BASE_CONTRACT")
    contract, contract_raw = load_self_hashed(answer_contract_path, ANSWER_CONTRACT_SCHEMA, "IMAGE_TEXT_ANSWER_CONTRACT")
    if (
        contract.get("result") != "PASS"
        or contract.get("row_id") != ROW_ID
        or contract.get("base_contract_raw_sha256") != sha(base_raw)
        or contract.get("base_contract_self_sha256") != base.get("self_sha256")
        or contract.get("gold_digest_rule") != GOLD_DIGEST_RULE
        or contract.get("never_read_lift") != NEVER_READ_LIFT
        or not isinstance(base.get("source"), dict)
        or contract.get("answer_dictionary_sha256") != base["source"].get("answer_dictionary_sha256")
        or contract.get("totality") != {"expected": ITEM_COUNT, "observed": ITEM_COUNT, "complete": True}
    ):
        raise ValueError("IMAGE_TEXT_ANSWER_CONTRACT_BINDING_REFUSED")
    items = contract.get("items")
    frozen = base.get("frozen_items")
    if not isinstance(items, list) or not isinstance(frozen, list) or len(items) != ITEM_COUNT or len(frozen) != ITEM_COUNT:
        raise ValueError("IMAGE_TEXT_ANSWER_CONTRACT_TOTALITY_REFUSED")
    for answer, item in zip(items, frozen):
        if (
            not isinstance(answer, dict)
            or answer.get("item_id") != item.get("item_id")
            or not isinstance(answer.get("option_count"), int)
            or not isinstance(answer.get("gold_answer_hmac"), str)
            or len(answer["gold_answer_hmac"]) != 64
        ):
            raise ValueError(f"IMAGE_TEXT_ANSWER_CONTRACT_ORDER_REFUSED:{answer.get('item_id') if isinstance(answer, dict) else None}")
    return {"contract": contract, "contract_raw_sha256": sha(contract_raw), "base": base, "base_raw_sha256": sha(base_raw)}


# ---------------------------------------------------------------------------------------------
# The pass: frozen order, one answer per item, receipt (no gold, no key)
# ---------------------------------------------------------------------------------------------

Emitter = Callable[[list[bytes], dict[str, Any], int], dict[str, Any]]
"""emit(image_payloads, item_text_payload, position) -> {"decoded_text": str, "generated_token_count":
int, "prompt_token_count": int, "stop_reason": str}. Tests inject a stub; the real emitter binds the
designated checkpoint and its vision path. The emitter never sees gold, the key, or another item."""

PayloadReader = Callable[[dict[str, Any], str], bytes]
"""read(object_ref {sha256, byte_count}, item_id) -> bytes, digest-checked by the caller's custody
reader (issue1947_release_row._bound_payload over the #2130 connector receipts)."""


def extract_letter(decoded: str, option_count: int) -> str | None:
    allowed = LETTERS[:option_count]
    for match in re.finditer(r"(?<![A-Za-z])([A-Za-z])(?![A-Za-z])", decoded):
        letter = match.group(1).upper()
        if letter in allowed:
            return letter
    return None


def _verified_payload(read_payload: PayloadReader, ref: dict[str, Any], item_id: str) -> bytes:
    # The reader is not trusted to have checked anything: size and sha256 of the bytes the emitter
    # will see are compared here against the base contract's declared object.
    raw = read_payload(ref, item_id)
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != ref.get("byte_count") or sha(bytes(raw)) != ref.get("sha256"):
        raise ValueError(f"IMAGE_TEXT_PAYLOAD_BINDING_REFUSED:{item_id}:{ref.get('sha256')}")
    return bytes(raw)


def run_pass(
    base: dict[str, Any],
    answer_contract: dict[str, Any],
    read_payload: PayloadReader,
    emit: Emitter,
    *,
    prediction_key: bytes,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    # prediction_key is held by this harness only; emit() never receives it.
    if len(prediction_key) != KEY_BYTES or sha(prediction_key) != answer_contract["answer_key_sha256"]:
        raise ValueError("IMAGE_TEXT_ANSWER_KEY_BINDING_REFUSED")
    frozen = base["frozen_items"]
    option_counts = {answer["item_id"]: answer["option_count"] for answer in answer_contract["items"]}
    records: list[dict[str, Any]] = []
    for position, item in enumerate(frozen):
        item_id = item["item_id"]
        images = [_verified_payload(read_payload, image, item_id) for image in item["image_objects"]]
        text_raw = _verified_payload(read_payload, item["item_text_object"], item_id)
        text = json.loads(text_raw)
        if not isinstance(text, dict) or set(text) != {"id", "question", "options"} or text.get("id") != item_id:
            raise ValueError(f"IMAGE_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_shape:{item_id}")
        if len(text["options"]) != option_counts[item_id]:
            raise ValueError(f"IMAGE_TEXT_OPTION_COUNT_REFUSED:{item_id}")
        started = time.monotonic()
        emitted = emit(images, text, position)
        decoded = emitted.get("decoded_text")
        if not isinstance(decoded, str):
            raise ValueError(f"IMAGE_TEXT_EMITTER_CONTRACT_REFUSED:{item_id}")
        letter = extract_letter(decoded, option_counts[item_id])
        record = {
            "position": position,
            "item_id": item_id,
            "image_sha256s": [image["sha256"] for image in item["image_objects"]],
            "item_text_sha256": item["item_text_object"]["sha256"],
            "decoded_text_hmac": keyed_decoded_digest(prediction_key, item_id, decoded),
            "prediction_hmac": keyed_answer_digest(prediction_key, item_id, letter) if letter is not None else None,
            "parsed": letter is not None,
            "prompt_token_count": int(emitted.get("prompt_token_count", -1)),
            "generated_token_count": int(emitted.get("generated_token_count", -1)),
            "stop_reason": str(emitted.get("stop_reason", "unknown")),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        records.append(record)
        if progress is not None:
            progress(record)
    if len(records) != ITEM_COUNT:
        raise ValueError(f"IMAGE_TEXT_INFERENCE_TOTALITY_REFUSED:{len(records)}")
    return {
        "records": records,
        "item_count": len(records),
        "parsed_count": sum(1 for record in records if record["parsed"]),
        "wall_seconds_total": round(sum(record["elapsed_seconds"] for record in records), 3),
    }


def build_receipt(
    *,
    loaded: dict[str, Any],
    pass_result: dict[str, Any],
    checkpoint_manifest_raw_sha256: str,
    model_bindings: dict[str, Any],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "result": RESULT_PASS,
        "row_id": ROW_ID,
        "base_contract_raw_sha256": loaded["base_raw_sha256"],
        "answer_contract_raw_sha256": loaded["contract_raw_sha256"],
        "answer_contract_self_sha256": loaded["contract"]["self_sha256"],
        "checkpoint_manifest_raw_sha256": checkpoint_manifest_raw_sha256,
        "model_bindings": model_bindings,
        "decode_contract": DECODE_CONTRACT,
        "decode_contract_sha256": decode_contract_sha256(),
        "frozen_order_sha256": frozen_order_sha256([record["item_id"] for record in pass_result["records"]]),
        "item_count": pass_result["item_count"],
        "parsed_count": pass_result["parsed_count"],
        "wall_seconds_total": pass_result["wall_seconds_total"],
        "records": pass_result["records"],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


# ---------------------------------------------------------------------------------------------
# Verification: the only place the key meets a prediction
# ---------------------------------------------------------------------------------------------

def verify_receipt(
    receipt_path: Path,
    answer_contract_path: Path,
    base_contract_path: Path,
    key_path: Path,
    *,
    expected_checkpoint_manifest_sha256: str,
) -> dict[str, Any]:
    if not isinstance(expected_checkpoint_manifest_sha256, str) or len(expected_checkpoint_manifest_sha256) != 64:
        raise ValueError("IMAGE_TEXT_INFERENCE_CHECKPOINT_BINDING_REFUSED")
    loaded = load_answer_contract(answer_contract_path, base_contract_path)
    contract, base = loaded["contract"], loaded["base"]
    key = load_key(key_path, contract["answer_key_sha256"])
    raw = receipt_path.read_bytes()
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("IMAGE_TEXT_INFERENCE_RECEIPT_SELF_HASH_REFUSED") from error
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("IMAGE_TEXT_INFERENCE_RECEIPT_SELF_HASH_REFUSED")
    body = dict(receipt)
    if body.pop("self_sha256", None) != sha(canonical(body)):
        raise ValueError("IMAGE_TEXT_INFERENCE_RECEIPT_SELF_HASH_REFUSED")
    model_bindings = receipt.get("model_bindings")
    if (
        set(receipt) != RECEIPT_FIELDS
        or not isinstance(model_bindings, dict)
        or not all(isinstance(value, MODEL_BINDING_VALUE_TYPES) for value in model_bindings.values())
    ):
        raise ValueError("IMAGE_TEXT_RECEIPT_FIELD_ALLOWLIST_REFUSED")
    if receipt.get("checkpoint_manifest_raw_sha256") != expected_checkpoint_manifest_sha256:
        raise ValueError("IMAGE_TEXT_INFERENCE_CHECKPOINT_BINDING_REFUSED")
    if (
        receipt.get("base_contract_raw_sha256") != loaded["base_raw_sha256"]
        or receipt.get("answer_contract_raw_sha256") != loaded["contract_raw_sha256"]
        or receipt.get("answer_contract_self_sha256") != contract["self_sha256"]
        or receipt.get("decode_contract") != DECODE_CONTRACT
        or receipt.get("decode_contract_sha256") != decode_contract_sha256()
    ):
        raise ValueError("IMAGE_TEXT_INFERENCE_CONTRACT_BINDING_REFUSED")
    records = receipt.get("records")
    if (
        receipt.get("result") != RESULT_PASS
        or not isinstance(records, list)
        or len(records) != ITEM_COUNT
        or receipt.get("item_count") != ITEM_COUNT
    ):
        raise ValueError("IMAGE_TEXT_INFERENCE_TOTALITY_REFUSED")
    frozen = base["frozen_items"]
    if receipt.get("frozen_order_sha256") != frozen_order_sha256([item["item_id"] for item in frozen]):
        raise ValueError("IMAGE_TEXT_EMISSION_ORDER_REFUSED")
    rows: list[dict[str, Any]] = []
    parsed = matched = 0
    for position, (record, item, answer) in enumerate(zip(records, frozen, contract["items"])):
        item_id = item["item_id"]
        if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
            raise ValueError(f"IMAGE_TEXT_RECEIPT_FIELD_ALLOWLIST_REFUSED:{position}")
        if record.get("position") != position or record.get("item_id") != item_id:
            raise ValueError("IMAGE_TEXT_EMISSION_ORDER_REFUSED")
        if (
            record.get("image_sha256s") != [image["sha256"] for image in item["image_objects"]]
            or record.get("item_text_sha256") != item["item_text_object"]["sha256"]
        ):
            raise ValueError(f"IMAGE_TEXT_INFERENCE_CONTRACT_BINDING_REFUSED:{item_id}")
        keyed = record.get("prediction_hmac")
        allowed = {keyed_answer_digest(key, item_id, option) for option in LETTERS[: answer["option_count"]]}
        if keyed is not None and keyed not in allowed:
            raise ValueError(f"IMAGE_TEXT_PREDICTION_SHAPE_REFUSED:{item_id}")
        if record.get("parsed") is not (keyed is not None):
            raise ValueError(f"IMAGE_TEXT_PREDICTION_SHAPE_REFUSED:parsed:{item_id}")
        decoded_hmac = record.get("decoded_text_hmac")
        if not isinstance(decoded_hmac, str) or len(decoded_hmac) != 64:
            raise ValueError(f"IMAGE_TEXT_PREDICTION_SHAPE_REFUSED:decoded:{item_id}")
        prediction = keyed if keyed is not None else sha(canonical({"item_id": item_id, "unparsed": True}))
        is_matched = keyed is not None and hmac.compare_digest(keyed, answer["gold_answer_hmac"])
        parsed += int(keyed is not None)
        matched += int(is_matched)
        rows.append({
            "item_id": item_id,
            "gold_item_sha256": answer["gold_answer_hmac"],
            "prediction": prediction,
            "score": 1.0 if is_matched else 0.0,
        })
    if receipt.get("parsed_count") != parsed:
        raise ValueError("IMAGE_TEXT_INFERENCE_TOTALITY_REFUSED:counts")
    return {
        "receipt": receipt,
        "receipt_raw_sha256": sha(raw),
        "answer_contract": contract,
        "answer_contract_raw_sha256": loaded["contract_raw_sha256"],
        "base_contract_raw_sha256": loaded["base_raw_sha256"],
        "items": rows,
        "parsed_count": parsed,
        "matched_count": matched,
        "score": matched / ITEM_COUNT,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="re-verify a receipt with the key (verifier only)")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--answer-contract", type=Path, required=True)
    verify.add_argument("--base-contract", type=Path, required=True)
    verify.add_argument("--key", type=Path, required=True)
    verify.add_argument("--checkpoint-manifest-sha256", required=True)
    sub.add_parser("produce", help="real inference on the card (not wired: needs the vision input path)")
    args = parser.parse_args(argv)
    if args.command == "produce":
        # The designated 3B head's image input path is not yet proven (owner ruling, mail 68177: the input-path
        # census). Refuse by name rather than emit a receipt from a path nobody has checked.
        print(json.dumps({"result": "IMAGE_TEXT_REAL_EMITTER_UNWIRED_REFUSED"}))
        return 2
    verified = verify_receipt(
        args.receipt, args.answer_contract, args.base_contract, args.key,
        expected_checkpoint_manifest_sha256=args.checkpoint_manifest_sha256,
    )
    print(json.dumps({
        "result": "IMAGE_TEXT_RECEIPT_VERIFIED",
        "parsed_count": verified["parsed_count"],
        "matched_count": verified["matched_count"],
        "score": verified["score"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
