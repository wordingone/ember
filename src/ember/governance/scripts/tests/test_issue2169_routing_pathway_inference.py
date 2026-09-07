#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2169 scope item 6: the planted negatives, plus the behaviour they are planted against.

Each planted negative is a receipt that has been tampered with in one specific way, and the test
asserts that the authoritative scorer REFUSES it. A verifier is only worth its exit code if it can
fail, so the happy-path case here exists mainly to prove that the refusals below are caused by the
tampering and not by the fixture being broken to begin with.

The fixtures never touch a GPU or the real model: the events and predictions a pass would produce
are supplied directly, because what is under test is the arithmetic over those events, not the
decoder that generates them. The real decoder is exercised by the governed run.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "issue2169_routing_pathway_inference.py"
_spec = importlib.util.spec_from_file_location("issue2169_routing_pathway_inference", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
producer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(producer)

LAYERS = 14
DECODE_STEPS = 3


def events(item_id: str, pathway: str, *, executed_pathway: str | None = "__same__",
           layers: int = LAYERS) -> tuple[list[dict], list[dict]]:
    """One pass's events. `executed_pathway` defaults to agreeing with the declaration; passing a
    different name models the case this instrument exists to catch -- the model was told one expert
    and ran another."""
    if executed_pathway == "__same__":
        executed_pathway = None if pathway == producer.SHARED else pathway
    branch = "shared_only" if pathway == producer.SHARED else f"expert:{pathway}"
    declared = [{"item_id": item_id, "pass": pathway, "layer_index": index, "branch": branch}
                for _ in range(DECODE_STEPS) for index in range(layers)]
    executed = []
    if executed_pathway is not None:
        executed = [{"item_id": item_id, "pass": pathway, "layer_index": index,
                     "branch": f"expert:{executed_pathway}"}
                    for _ in range(DECODE_STEPS) for index in range(layers)]
    return declared, executed


def build_contract(tmp: Path, item_count: int = producer.ITEM_COUNT) -> Path:
    items = []
    for index in range(item_count):
        pathway = ("tool", "reasoning", producer.SHARED)[index % 3]
        items.append({
            "item_id": f"routing-{index:04d}",
            "source_item_id": f"src-{index:04d}",
            "prompt_sha256": producer.sha(f"prompt-{index}".encode()),
            "required_pathway": pathway,
            "control_pathway": None if pathway == producer.SHARED else producer.SHARED,
            "source_contract_self_sha256": "s" * 64,
        })
    contract = {
        "schema_version": producer.CONTRACT_SCHEMA,
        "item_count": item_count,
        "items": items,
        "engagement_rule": "prediction_sha256(required) != prediction_sha256(control)",
        "decode_contract_sha256": "d" * 64,
        "frozen_order_sha256": producer.sha(producer.canonical([i["item_id"] for i in items])),
    }
    contract["self_sha256"] = producer.self_hash(contract)
    path = tmp / "contract.json"
    path.write_text(json.dumps(contract, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path


def build_receipt(tmp: Path, contract_path: Path, *, manifest_sha: str = "m" * 64) -> tuple[Path, dict]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    records = []
    for position, item in enumerate(contract["items"]):
        required = item["required_pathway"]
        control = item["control_pathway"]
        declared, executed = events(item["item_id"], required)
        required_summary = producer.summarize_events(declared, executed, pathway=required,
                                                     layers=LAYERS, decode_steps=DECODE_STEPS)
        required_pass = {"prediction_sha256": producer.sha(f"required-{position}".encode()),
                         "generated_token_count": DECODE_STEPS, "stop_reason": "eos_token",
                         **required_summary}
        control_pass = None
        if control is not None:
            c_declared, c_executed = events(item["item_id"], control)
            control_summary = producer.summarize_events(c_declared, c_executed, pathway=control,
                                                        layers=LAYERS, decode_steps=DECODE_STEPS)
            control_pass = {"prediction_sha256": producer.sha(f"control-{position}".encode()),
                            "generated_token_count": DECODE_STEPS, "stop_reason": "eos_token",
                            **control_summary}
        matched = producer.pathway_match(required_summary, pathway=required, layers=LAYERS)
        if control_pass is not None:
            matched = matched and producer.pathway_match(control_summary, pathway=control, layers=LAYERS)
            engaged: object = required_pass["prediction_sha256"] != control_pass["prediction_sha256"]
        else:
            engaged = "not_applicable"
        records.append({
            "position": position, "item_id": item["item_id"], "prompt_sha256": item["prompt_sha256"],
            "source_item_id": item["source_item_id"], "required_pathway": required,
            "control_pathway": control, "required_pass": required_pass, "control_pass": control_pass,
            "pathway_match": bool(matched), "engaged": engaged,
            "scored": bool(matched) and (engaged is True or engaged == "not_applicable"),
            "elapsed_seconds": 0.0,
        })
    receipt = {
        "schema_version": producer.RECEIPT_SCHEMA, "issue": 2169, "result": producer.RESULT_PASS,
        "contract_self_sha256": contract["self_sha256"],
        "frozen_order_sha256": contract["frozen_order_sha256"],
        "decode_contract_sha256": contract["decode_contract_sha256"],
        "checkpoint_manifest_raw_sha256": manifest_sha, "layers": LAYERS,
        "engagement_rule": contract["engagement_rule"], "records": records,
        **producer.tally(records),
    }
    return write_receipt(tmp, receipt), receipt


def write_receipt(tmp: Path, receipt: dict, name: str = "receipt.json") -> Path:
    document = {key: value for key, value in receipt.items() if key != "self_sha256"}
    document["self_sha256"] = producer.self_hash(document)
    path = tmp / name
    path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path


class RoutingPathwayVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__file__).resolve().parent / "_tmp_issue2169"
        self.tmp.mkdir(exist_ok=True)
        self.contract = build_contract(self.tmp)
        self.receipt_path, self.receipt = build_receipt(self.tmp, self.contract)

    def tearDown(self) -> None:
        for path in self.tmp.glob("*"):
            path.unlink()
        self.tmp.rmdir()

    # --- the fixture is sound, so the refusals below mean what they say -----------------------

    def test_untampered_receipt_verifies_and_scores_every_item(self) -> None:
        verdict = producer.verify_receipt(self.receipt_path, self.contract,
                                          expected_checkpoint_manifest_sha256="m" * 64)
        self.assertEqual(verdict["item_count"], producer.ITEM_COUNT)
        self.assertEqual(verdict["scored_count"], producer.ITEM_COUNT)
        self.assertEqual(verdict["score"], 1.0)

    def test_shared_items_are_recorded_not_applicable_rather_than_silently_engaged(self) -> None:
        shared = [r for r in self.receipt["records"] if r["required_pathway"] == producer.SHARED]
        self.assertTrue(shared)
        self.assertTrue(all(r["engaged"] == "not_applicable" for r in shared))
        self.assertTrue(all(r["control_pass"] is None for r in shared))

    # --- planted negatives (scope item 6) -----------------------------------------------------

    def test_two_items_swapped_is_refused(self) -> None:
        tampered = copy.deepcopy(self.receipt)
        tampered["records"][4], tampered["records"][7] = tampered["records"][7], tampered["records"][4]
        path = write_receipt(self.tmp, tampered, "swapped.json")
        with self.assertRaises(ValueError) as caught:
            producer.verify_receipt(path, self.contract, expected_checkpoint_manifest_sha256="m" * 64)
        self.assertIn("ROUTING_PATHWAY_ORDER_REFUSED", str(caught.exception))

    def test_receipt_pointed_at_another_checkpoint_is_refused(self) -> None:
        tampered = copy.deepcopy(self.receipt)
        tampered["checkpoint_manifest_raw_sha256"] = "f" * 64
        path = write_receipt(self.tmp, tampered, "wrong-checkpoint.json")
        with self.assertRaises(ValueError) as caught:
            producer.verify_receipt(path, self.contract, expected_checkpoint_manifest_sha256="m" * 64)
        self.assertIn("ROUTING_PATHWAY_CHECKPOINT_BINDING_REFUSED", str(caught.exception))

    def test_edited_path_event_item_id_is_refused(self) -> None:
        """Editing one event's item id changes the events digest, which no longer describes the
        pass it is filed under. The recomputation reaches a different verdict than the record
        claims, which is the refusal."""
        tampered = copy.deepcopy(self.receipt)
        record = tampered["records"][3]
        declared, executed = events(record["item_id"], record["required_pathway"])
        declared[0]["item_id"] = "routing-9999"
        summary = producer.summarize_events(declared, executed, pathway=record["required_pathway"],
                                            layers=LAYERS, decode_steps=DECODE_STEPS)
        summary["declared_branches"] = ["expert:vision"]  # the pass no longer took its own pathway
        record["required_pass"].update(summary)
        path = write_receipt(self.tmp, tampered, "edited-event.json")
        with self.assertRaises(ValueError) as caught:
            producer.verify_receipt(path, self.contract, expected_checkpoint_manifest_sha256="m" * 64)
        self.assertIn("REFUSED", str(caught.exception))

    def test_fabricated_engagement_is_refused(self) -> None:
        """A control prediction copied over its required prediction makes the two passes identical,
        so the engagement rule says NOT engaged while the record still claims engaged."""
        tampered = copy.deepcopy(self.receipt)
        record = next(r for r in tampered["records"] if r["control_pass"] is not None)
        record["control_pass"]["prediction_sha256"] = record["required_pass"]["prediction_sha256"]
        path = write_receipt(self.tmp, tampered, "fabricated.json")
        with self.assertRaises(ValueError) as caught:
            producer.verify_receipt(path, self.contract, expected_checkpoint_manifest_sha256="m" * 64)
        self.assertIn("ROUTING_PATHWAY_SCORE_MISMATCH_REFUSED", str(caught.exception))

    def test_inflated_scored_count_is_refused(self) -> None:
        tampered = copy.deepcopy(self.receipt)
        tampered["scored_count"] = producer.ITEM_COUNT + 5
        path = write_receipt(self.tmp, tampered, "inflated.json")
        with self.assertRaises(ValueError) as caught:
            producer.verify_receipt(path, self.contract, expected_checkpoint_manifest_sha256="m" * 64)
        self.assertIn("ROUTING_PATHWAY_SCORE_MISMATCH_REFUSED", str(caught.exception))

    def test_short_receipt_is_refused_on_totality(self) -> None:
        tampered = copy.deepcopy(self.receipt)
        tampered["records"] = tampered["records"][:-1]
        tampered.update(producer.tally(tampered["records"]))
        path = write_receipt(self.tmp, tampered, "short.json")
        with self.assertRaises(ValueError) as caught:
            producer.verify_receipt(path, self.contract, expected_checkpoint_manifest_sha256="m" * 64)
        self.assertIn("ROUTING_PATHWAY_TOTALITY_REFUSED", str(caught.exception))

    def test_a_hand_edited_receipt_fails_its_own_self_hash(self) -> None:
        raw = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        raw["scored_count"] = 1
        path = self.tmp / "unsealed.json"
        path.write_text(json.dumps(raw, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        with self.assertRaises(ValueError) as caught:
            producer.verify_receipt(path, self.contract, expected_checkpoint_manifest_sha256="m" * 64)
        self.assertIn("SELF_HASH_REFUSED", str(caught.exception))


class PathwayMatchArithmetic(unittest.TestCase):
    """The declaration and the execution are two independent event sources on purpose."""

    def summary(self, pathway: str, **kwargs: object) -> dict:
        declared, executed = events("routing-0000", pathway, **kwargs)  # type: ignore[arg-type]
        return producer.summarize_events(declared, executed, pathway=pathway, layers=LAYERS,
                                         decode_steps=DECODE_STEPS)

    def test_declared_and_executed_agreeing_is_a_match(self) -> None:
        self.assertTrue(producer.pathway_match(self.summary("tool"), pathway="tool", layers=LAYERS))

    def test_a_shared_pass_that_ran_an_expert_is_not_a_match(self) -> None:
        summary = self.summary(producer.SHARED, executed_pathway="tool")
        self.assertFalse(producer.pathway_match(summary, pathway=producer.SHARED, layers=LAYERS))

    def test_declaring_one_expert_and_running_another_is_not_a_match(self) -> None:
        """The case an argument-only instrument cannot see: the layer was told `tool` and executed
        `reasoning`. Reading the declaration alone would report a clean tool pathway."""
        summary = self.summary("tool", executed_pathway="reasoning")
        self.assertFalse(producer.pathway_match(summary, pathway="tool", layers=LAYERS))

    def test_a_pass_missing_layers_is_not_a_match(self) -> None:
        summary = self.summary("tool", layers=LAYERS - 1)
        self.assertFalse(producer.pathway_match(summary, pathway="tool", layers=LAYERS))


if __name__ == "__main__":
    unittest.main()
