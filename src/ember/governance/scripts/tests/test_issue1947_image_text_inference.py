# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds for the #1947 IMAGE-TEXT model-prediction producer (keyed gold, owner ruling mail 68732).

Fixture contracts and a fixture key only; no model, no card, no admitted bytes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue1947_image_text_inference.py"
SPEC = importlib.util.spec_from_file_location("issue1947_image_text_inference", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

KEY = bytes(range(32))
CHECKPOINT = "c" * 64


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def self_hash(payload: dict) -> dict:
    body = dict(payload)
    body.pop("self_sha256", None)
    body["self_sha256"] = sha(canonical(body))
    return body


def write(path: Path, payload: object) -> Path:
    path.write_bytes(canonical(payload))
    return path


class Fixture:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.payloads: dict[str, bytes] = {}
        self.answers: dict[str, str] = {}
        self.option_counts: dict[str, int] = {}
        frozen = []
        for index in range(MODULE.ITEM_COUNT):
            item_id = f"item-{index:04d}"
            option_count = 2 + index % 4
            options = [f"opt{n}" for n in range(option_count)]
            text = (json.dumps({"id": item_id, "question": f"q {index}", "options": options},
                               sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
            image = f"png-{index}".encode()
            for raw in (text, image):
                self.payloads[sha(raw)] = raw
            frozen.append({
                "item_id": item_id,
                "gold_item_sha256": sha(image + text),
                "image_objects": [{"sha256": sha(image), "byte_count": len(image), "media_type": "image/png"}],
                "item_text_object": {"sha256": sha(text), "byte_count": len(text)},
            })
            self.answers[item_id] = MODULE.LETTERS[index % option_count]
            self.option_counts[item_id] = option_count
        self.base_path = write(tmp / "base.json", self_hash({
            "schema_version": MODULE.BASE_CONTRACT_SCHEMA, "result": "PASS", "frozen_items": frozen,
        }))
        self.dictionary_path = tmp / "answers.json"
        self.dictionary_path.write_bytes(canonical(self.answers))
        self.key_path = tmp / "key.bin"
        self.key_path.write_bytes(KEY)
        contract = MODULE.build_answer_contract(
            base_contract_path=self.base_path, answer_dictionary_path=self.dictionary_path,
            expected_answer_dictionary_sha256=sha(self.dictionary_path.read_bytes()), key=KEY,
            option_counts=self.option_counts,
        )
        self.answer_path = write(tmp / "answer-contract.json", contract)

    def read_payload(self, ref: dict, item_id: str) -> bytes:
        raw = self.payloads[ref["sha256"]]
        assert len(raw) == ref["byte_count"]
        return raw

    def produce(self, answer_for) -> Path:
        loaded = MODULE.load_answer_contract(self.answer_path, self.base_path)

        def emit(images, text, position):
            return {"decoded_text": answer_for(text["id"], position), "generated_token_count": 1,
                    "prompt_token_count": 10, "stop_reason": "eos_token"}

        result = MODULE.run_pass(loaded["base"], loaded["contract"], self.read_payload, emit)
        receipt = MODULE.build_receipt(loaded=loaded, pass_result=result,
                                       checkpoint_manifest_raw_sha256=CHECKPOINT, model_bindings={"fixture": True})
        return write(self.tmp / "receipt.json", receipt)

    def verify(self, receipt_path: Path, **overrides):
        kwargs = dict(answer_contract_path=self.answer_path, base_contract_path=self.base_path, key_path=self.key_path)
        kwargs.update(overrides)
        checkpoint = kwargs.pop("checkpoint", CHECKPOINT)
        return MODULE.verify_receipt(receipt_path, kwargs["answer_contract_path"], kwargs["base_contract_path"],
                                     kwargs["key_path"], expected_checkpoint_manifest_sha256=checkpoint)


@pytest.fixture(scope="module")
def fx(tmp_path_factory) -> Fixture:
    return Fixture(tmp_path_factory.mktemp("image-text"))


def rewrite(path: Path, mutate) -> Path:
    payload = json.loads(path.read_bytes())
    mutate(payload)
    return write(path.with_name("mutated-" + path.name), self_hash(payload))


def test_correct_answers_score_one(fx):
    verified = fx.verify(fx.produce(lambda item_id, _p: f"Answer: {fx.answers[item_id]}"))
    assert verified["matched_count"] == MODULE.ITEM_COUNT and verified["score"] == 1.0


def test_wrong_model_is_a_reported_zero_not_a_refusal(fx):
    def wrong(item_id, _p):
        allowed = MODULE.LETTERS[: fx.option_counts[item_id]]
        return allowed[(allowed.index(fx.answers[item_id]) + 1) % len(allowed)]
    verified = fx.verify(fx.produce(wrong))
    assert verified["matched_count"] == 0 and verified["score"] == 0.0
    assert verified["parsed_count"] == MODULE.ITEM_COUNT


def test_unparsed_emission_is_a_miss_not_a_refusal(fx):
    verified = fx.verify(fx.produce(lambda _i, p: "no letter here" if p % 2 else "B"))
    assert verified["parsed_count"] < MODULE.ITEM_COUNT
    assert all(row["score"] == 0.0 for row in verified["items"][1::2])


def test_receipt_and_row_never_hold_gold_letters_or_key(fx):
    receipt_path = fx.produce(lambda item_id, _p: fx.answers[item_id])
    raw = receipt_path.read_bytes()
    assert KEY.hex() not in raw.decode() and fx.dictionary_path.read_bytes() not in raw
    receipt = json.loads(raw)
    assert all(set(r) & {"matched", "gold_answer_hmac", "score"} == set() for r in receipt["records"])
    verified = fx.verify(receipt_path)
    for row in verified["items"]:
        assert len(row["prediction"]) == 64 and row["prediction"] not in MODULE.LETTERS


def test_keyed_digest_does_not_invert_by_lookup(fx):
    contract = json.loads(fx.answer_path.read_bytes())
    plain = {sha(letter.encode()) for letter in MODULE.LETTERS}
    plain |= {sha(f"{item['item_id']}\x00{letter}".encode()) for item in contract["items"][:5] for letter in MODULE.LETTERS}
    assert not plain & {item["gold_answer_hmac"] for item in contract["items"]}


def test_wrong_checkpoint_refuses(fx):
    with pytest.raises(ValueError, match="CHECKPOINT_BINDING_REFUSED"):
        fx.verify(fx.produce(lambda item_id, _p: "A"), checkpoint="d" * 64)


def test_wrong_key_refuses(fx, tmp_path):
    other = tmp_path / "other-key.bin"
    other.write_bytes(bytes(32))
    with pytest.raises(ValueError, match="ANSWER_KEY_BINDING_REFUSED"):
        fx.verify(fx.produce(lambda item_id, _p: "A"), key_path=other)


def test_tampered_receipt_without_rehash_refuses(fx):
    path = fx.produce(lambda item_id, _p: "A")
    payload = json.loads(path.read_bytes())
    payload["records"][0]["predicted_letter"] = "B"
    with pytest.raises(ValueError, match="SELF_HASH_REFUSED"):
        fx.verify(write(path.with_name("tampered.json"), payload))


def test_dropped_item_refuses(fx):
    path = rewrite(fx.produce(lambda item_id, _p: "A"), lambda p: p["records"].pop())
    with pytest.raises(ValueError, match="TOTALITY_REFUSED"):
        fx.verify(path)


def test_reordered_items_refuse(fx):
    def swap(p):
        p["records"][0], p["records"][1] = p["records"][1], p["records"][0]
    with pytest.raises(ValueError, match="ORDER_REFUSED"):
        fx.verify(rewrite(fx.produce(lambda item_id, _p: "A"), swap))


def test_wrong_image_control_refuses(fx):
    def swap_image(p):
        p["records"][0]["image_sha256s"] = p["records"][1]["image_sha256s"]
    with pytest.raises(ValueError, match="CONTRACT_BINDING_REFUSED:item-0000"):
        fx.verify(rewrite(fx.produce(lambda item_id, _p: "A"), swap_image))


def test_letter_outside_options_refuses(fx):
    def out_of_range(p):
        p["records"][0]["predicted_letter"] = "J"
    with pytest.raises(ValueError, match="PREDICTION_SHAPE_REFUSED"):
        fx.verify(rewrite(fx.produce(lambda item_id, _p: "A"), out_of_range))


def test_wrong_dictionary_identity_refuses_the_builder(fx):
    with pytest.raises(ValueError, match="ANSWER_DICTIONARY_IDENTITY_REFUSED"):
        MODULE.build_answer_contract(
            base_contract_path=fx.base_path, answer_dictionary_path=fx.dictionary_path,
            expected_answer_dictionary_sha256="0" * 64, key=KEY, option_counts=fx.option_counts,
        )


def test_answer_outside_item_options_refuses_the_builder(fx, tmp_path):
    answers = dict(fx.answers)
    answers["item-0000"] = "E"  # item-0000 has two options
    bad = tmp_path / "bad-answers.json"
    bad.write_bytes(canonical(answers))
    with pytest.raises(ValueError, match="ANSWER_LETTER_REFUSED:item-0000"):
        MODULE.build_answer_contract(
            base_contract_path=fx.base_path, answer_dictionary_path=bad,
            expected_answer_dictionary_sha256=sha(bad.read_bytes()), key=KEY, option_counts=fx.option_counts,
        )


def test_unsealed_gold_rule_refuses(fx):
    path = rewrite(fx.answer_path, lambda p: p.__setitem__("gold_digest_rule", "sha256(letter)"))
    with pytest.raises(ValueError, match="ANSWER_CONTRACT_BINDING_REFUSED"):
        fx.verify(fx.produce(lambda item_id, _p: "A"), answer_contract_path=path)


def test_answer_contract_bound_to_another_base_refuses(fx, tmp_path):
    other = write(tmp_path / "other-base.json", self_hash({
        **json.loads(fx.base_path.read_bytes()), "result": "PASS", "note": "different bytes",
    }))
    with pytest.raises(ValueError, match="ANSWER_CONTRACT_BINDING_REFUSED"):
        MODULE.load_answer_contract(fx.answer_path, other)


def test_produce_refuses_until_the_vision_path_is_proven():
    completed = subprocess.run([sys.executable, "-B", str(SOURCE), "produce"], capture_output=True, text=True)
    assert completed.returncode == 2
    assert "IMAGE_TEXT_REAL_EMITTER_UNWIRED_REFUSED" in completed.stdout


def _release_row_module():
    path = ROOT / "src" / "ember" / "governance" / "scripts" / "issue1947_release_row.py"
    spec = importlib.util.spec_from_file_location("issue1947_release_row_for_image_text", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_row_adapter_emits_the_executor_item_schema(fx):
    rows = _release_row_module()
    row = rows.adapt_image_text_prediction(
        fx.base_path, fx.answer_path, fx.key_path,
        fx.produce(lambda item_id, p: fx.answers[item_id] if p % 3 == 0 else "none"), CHECKPOINT,
    )
    assert row["task_class"] == "checkpoint_inference" and row["item_count"] == MODULE.ITEM_COUNT
    assert all(set(item) == {"item_id", "gold_item_sha256", "prediction", "score"} for item in row["items"])
    assert row["matched_count"] == len(range(0, MODULE.ITEM_COUNT, 3))


def test_release_row_adapter_refuses_an_unbound_checkpoint(fx):
    rows = _release_row_module()
    with pytest.raises(ValueError, match="CHECKPOINT_BINDING_REFUSED"):
        rows.adapt_image_text_prediction(fx.base_path, fx.answer_path, fx.key_path,
                                         fx.produce(lambda item_id, _p: "A"), "short")
