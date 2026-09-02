# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Independent local verifier for owned reasoning and tool trajectory records."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import operator
import re
import sys
from pathlib import Path
from typing import Any, Mapping

VERIFIER_PATH = "src/ember/infrastructure/tools/ember-restart-3b/verify_capability_record.py"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def canonical_record_sha256(record: Mapping[str, Any]) -> str:
    canonical = {key: value for key, value in record.items() if key != "capability_receipt"}
    return hashlib.sha256(_canonical_bytes(canonical)).hexdigest()


def verifier_sha256() -> str:
    bound = globals().get("__ember_bound_source_sha256__")
    if isinstance(bound, str) and len(bound) == 64 and all(character in "0123456789abcdef" for character in bound):
        return bound
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _integer_expression(expression: object) -> int:
    if not isinstance(expression, str) or not expression:
        raise ValueError("tool expression must be a nonempty string")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}

    def evaluate(node: ast.AST) -> int:
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError("tool expression uses an unauthorized operation")

    return evaluate(ast.parse(expression, mode="eval").body)


def _reasoning_target(record: Mapping[str, Any]) -> dict[str, Any]:
    evidence = record.get("capability_evidence")
    if not isinstance(evidence, Mapping) or not isinstance(evidence.get("reasoning"), Mapping):
        raise ValueError("reasoning episode lacks a reasoning task")
    task = evidence["reasoning"]
    operands = task.get("operands")
    target = task.get("target")
    trace = task.get("trace")
    if (
        not isinstance(operands, list)
        or not operands
        or any(not isinstance(value, int) or isinstance(value, bool) for value in operands)
        or not isinstance(target, int)
        or isinstance(target, bool)
        or not isinstance(trace, list)
        or not trace
    ):
        raise ValueError("reasoning task is malformed")
    if sum(operands) != target:
        raise ValueError("reasoning target does not equal the owned arithmetic task")
    if trace != [*operands, target]:
        raise ValueError("reasoning trace does not exactly bind operands and target")
    return {"operands": operands, "target": target, "trace": trace}


def _tool_execution(record: Mapping[str, Any]) -> dict[str, Any]:
    evidence = record.get("capability_evidence")
    if not isinstance(evidence, Mapping) or not isinstance(evidence.get("tool"), Mapping):
        raise ValueError("tool episode lacks a typed tool task")
    task = evidence["tool"]
    if task.get("name") != "owned_calculator" or not isinstance(task.get("arguments"), Mapping):
        raise ValueError("tool task is not an authorized owned calculator call")
    observed = task.get("observation")
    if not isinstance(observed, Mapping) or set(observed) != {"value"}:
        raise ValueError("tool task observation is malformed")
    value = _integer_expression(task["arguments"].get("expression"))
    if observed["value"] != value:
        raise ValueError("tool observation does not equal executed owned tool result")
    return {"name": task["name"], "arguments": dict(task["arguments"]), "observation": dict(observed)}


def _verify_target_transcript(record: Mapping[str, Any], *, expert: str) -> None:
    if "target_text" not in record:
        return
    if not isinstance(record["target_text"], str):
        raise ValueError("target transcript must be a string")
    if expert == "reasoning":
        task = _reasoning_target(record)
        expected = f"reasoning sum {task['operands'][0]} plus {task['operands'][1]} equals {task['target']}"
    else:
        task = _tool_execution(record)
        expression = task["arguments"]["expression"]
        match = re.fullmatch(r"(-?\d+)\+(-?\d+)", expression)
        expected = (f"tool calculator {match.group(1)} plus {match.group(2)} equals {task['observation']['value']}" if match else f"tool calculator {expression} equals {task['observation']['value']}")
    if record["target_text"] != expected:
        raise ValueError("target transcript does not match locally executed evidence")

def expected_receipt(record: Mapping[str, Any]) -> dict[str, str] | None:
    expert = record.get("active_expert")
    if expert not in {"vision", "audio", "reasoning", "tool"}:
        raise ValueError("record lacks an authorized active expert")
    receipt: dict[str, str] = {
        "canonical_record_sha256": canonical_record_sha256(record),
        "verifier_path": VERIFIER_PATH,
        "verifier_sha256": verifier_sha256(),
        "result": "PASSED",
    }
    if expert == "reasoning":
        _verify_target_transcript(record, expert=expert)
        receipt["reasoning_target_sha256"] = hashlib.sha256(_canonical_bytes(_reasoning_target(record))).hexdigest()
    elif expert == "tool":
        _verify_target_transcript(record, expert=expert)
        receipt["tool_execution_sha256"] = hashlib.sha256(_canonical_bytes(_tool_execution(record))).hexdigest()
    else:
        return None
    return receipt


def verify_record(record: Mapping[str, Any]) -> dict[str, str] | None:
    expected = expected_receipt(record)
    if expected is None:
        return None
    supplied = record.get("capability_receipt")
    if not isinstance(supplied, Mapping) or dict(supplied) != expected:
        raise ValueError("capability receipt does not bind this record, verifier, and executed result")
    return expected


def _main() -> int:
    parser = argparse.ArgumentParser()
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--record-json-base64")
    inputs.add_argument("--records-json-base64")
    inputs.add_argument("--records-json-stdin", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.records_json_stdin:
            payload = json.load(sys.stdin)
        else:
            encoded = arguments.record_json_base64 or arguments.records_json_base64
            decoded = base64.b64decode(encoded, validate=True)
            payload = json.loads(decoded)
        if arguments.record_json_base64 is not None:
            if not isinstance(payload, dict):
                raise ValueError("record must be an object")
            receipt = verify_record(payload)
            output: dict[str, object] = {"result": "PASSED", "receipt": receipt}
        else:
            if not isinstance(payload, list) or not payload or any(not isinstance(record, dict) for record in payload):
                raise ValueError("records must be a nonempty array of objects")
            output = {"result": "PASSED", "receipts": [verify_record(record) for record in payload]}
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"result": "FAILED", "error": str(error)}, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())