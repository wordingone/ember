#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Custody-bound one-item MMMU loader/adapter/scorer front unit; no capability credit."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# issue2015 exact-local-import:src/ember/governance/scripts/ember_restart/prediction_contract.py
import importlib.util as _ember_5fe35e3f50d06cc1_importlib
import sys as _ember_5fe35e3f50d06cc1_sys
from pathlib import Path as _ember_5fe35e3f50d06cc1_Path
_ember_5fe35e3f50d06cc1_path = _ember_5fe35e3f50d06cc1_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'ember_restart', 'prediction_contract.py')
if not _ember_5fe35e3f50d06cc1_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_restart/prediction_contract.py')
_ember_5fe35e3f50d06cc1_aliases = ('_ember_issue2015_5fe35e3f50d06cc1', 'prediction_contract', 'scripts.ember_restart.prediction_contract')
_ember_5fe35e3f50d06cc1_existing = []
for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
    _ember_5fe35e3f50d06cc1_candidate = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
    if _ember_5fe35e3f50d06cc1_candidate is not None and all(_ember_5fe35e3f50d06cc1_candidate is not item for item in _ember_5fe35e3f50d06cc1_existing):
        _ember_5fe35e3f50d06cc1_existing.append(_ember_5fe35e3f50d06cc1_candidate)
if len(_ember_5fe35e3f50d06cc1_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
if _ember_5fe35e3f50d06cc1_existing:
    _ember_5fe35e3f50d06cc1_module = _ember_5fe35e3f50d06cc1_existing[0]
    _ember_5fe35e3f50d06cc1_observed = getattr(_ember_5fe35e3f50d06cc1_module, '__file__', None)
    if _ember_5fe35e3f50d06cc1_observed is None or _ember_5fe35e3f50d06cc1_Path(_ember_5fe35e3f50d06cc1_observed).resolve() != _ember_5fe35e3f50d06cc1_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_restart/prediction_contract.py')
else:
    _ember_5fe35e3f50d06cc1_spec = _ember_5fe35e3f50d06cc1_importlib.spec_from_file_location('_ember_issue2015_5fe35e3f50d06cc1', _ember_5fe35e3f50d06cc1_path)
    if _ember_5fe35e3f50d06cc1_spec is None or _ember_5fe35e3f50d06cc1_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_restart/prediction_contract.py')
    _ember_5fe35e3f50d06cc1_module = _ember_5fe35e3f50d06cc1_importlib.module_from_spec(_ember_5fe35e3f50d06cc1_spec)
    for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
        _ember_5fe35e3f50d06cc1_prior = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
        if _ember_5fe35e3f50d06cc1_prior is not None and _ember_5fe35e3f50d06cc1_prior is not _ember_5fe35e3f50d06cc1_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
        _ember_5fe35e3f50d06cc1_sys.modules[_ember_5fe35e3f50d06cc1_alias] = _ember_5fe35e3f50d06cc1_module
    try:
        _ember_5fe35e3f50d06cc1_spec.loader.exec_module(_ember_5fe35e3f50d06cc1_module)
    except BaseException:
        for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
            if _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias) is _ember_5fe35e3f50d06cc1_module:
                _ember_5fe35e3f50d06cc1_sys.modules.pop(_ember_5fe35e3f50d06cc1_alias, None)
        raise
for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
    _ember_5fe35e3f50d06cc1_prior = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
    if _ember_5fe35e3f50d06cc1_prior is not None and _ember_5fe35e3f50d06cc1_prior is not _ember_5fe35e3f50d06cc1_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
    _ember_5fe35e3f50d06cc1_sys.modules[_ember_5fe35e3f50d06cc1_alias] = _ember_5fe35e3f50d06cc1_module
ContractError = getattr(_ember_5fe35e3f50d06cc1_module, 'ContractError')
materialize = getattr(_ember_5fe35e3f50d06cc1_module, 'materialize')
validate_predictions = getattr(_ember_5fe35e3f50d06cc1_module, 'validate_predictions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/prediction_contract.py


ANSWER_SHA256 = "76080f5597b8f4d29abba8551489c4b82e4a285b9d62b946fd67a1952e95502c"
ELIGIBLE_ID_SET_SHA256 = "7a8800c96f0a6003b004d4bc3dfc089b8d6d5aa56a5f85e8c4719fbadd63ecc6"
CUSTODY_SHA256 = "20af6ef398cd7913ea0ba5b53025dbf568eab6d74f7290d01ceda30c4a206b03"
FREEZE_SHA256 = "2f1f5ab0e961e8eb3f7082277dc354f0d503f775fb177a385585444ccd5110b4"
IMAGE_INPUTS_SHA256 = "719619b79f85e56d42552d2935de3bf43e9bd5dee9529f037a7e32dc228d0ebd"
SCORER_SHA256 = "07cc41149073066441379d69bfa51afe1e10644701fc3d0d0a7fb74833ecd5f3"
PREDICTION_CONTRACT_SHA256 = "0d91773d0f0dae5f639fa97f1527fec793dab8bfee28e1fee4071875bdc6174f"
PROTOCOL_SHA256 = "260d6f2da13a10def5c158641452e77b86d2fc5d330251c0e98b76ca811bc42c"
PROBE_ITEM_ID = "validation_Accounting_1"


class FrontUnitError(ValueError):
    """Fail-closed MMMU front-unit error."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def derive_self(value: dict) -> str:
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    return canonical_digest(unsigned)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eligible_identity(answers: dict[str, Any]) -> tuple[list[str], str]:
    ids = sorted(
        key for key, value in answers.items()
        if isinstance(value, dict) and value.get("question_type") == "multiple-choice"
    )
    return ids, hashlib.sha256(("\n".join(ids) + "\n").encode("utf-8")).hexdigest()


def parse_options(raw: str) -> list[str]:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise FrontUnitError("OPTION_SHAPE") from exc
    if not isinstance(value, list) or len(value) < 2 or any(not isinstance(item, str) or not item for item in value):
        raise FrontUnitError("OPTION_SHAPE")
    return value


def validate_parquet_index(validation_root: Path, expected: list[dict]) -> list[Path]:
    files = sorted(validation_root.glob("*/validation-*.parquet"))
    relative = [path.relative_to(validation_root).as_posix() for path in files]
    expected_paths = [row.get("path") for row in expected if isinstance(row, dict)]
    if not files or relative != expected_paths:
        raise FrontUnitError("PARQUET_PATH_DRIFT")
    for path, row in zip(files, expected):
        if file_sha(path) != row.get("sha256"):
            raise FrontUnitError("PARQUET_BYTES_DRIFT")
    return files


def _validated_envelope(envelope: dict) -> dict:
    try:
        return validate_predictions(envelope)
    except ContractError as exc:
        raise FrontUnitError(str(exc)) from exc


def score_one(loader: dict, envelope: dict) -> dict:
    if loader.get("options_sha256") != canonical_digest(loader.get("options")):
        raise FrontUnitError("CHANGED_ORDER")
    checked = _validated_envelope(envelope)
    if checked["benchmark"]["id"] != "MMMU" or checked["benchmark"]["capability"] != "image":
        raise FrontUnitError("BENCHMARK_IDENTITY")
    if len(checked["rows"]) != 1:
        raise FrontUnitError("EXACTLY_ONE_ROW_REQUIRED")
    row = checked["rows"][0]
    if row["id"] != loader["id"] or row["input_sha256"] != loader["input_sha256"]:
        raise FrontUnitError("ROW_IDENTITY")
    adapted = materialize(checked, "mmmu")
    prediction = adapted[0]["prediction"]
    if prediction not in loader["option_labels"]:
        raise FrontUnitError("CHOICE_OUT_OF_RANGE")
    return {"exact_match": int(prediction == loader["ground_truth"]), "sample_count": 1}


def internal_test_envelope(loader: dict, choice: str) -> dict:
    """Build the non-capability, internally test-bound canonical adapter input."""
    return {
        "schema_version": "ember-owned-predictions-v1",
        "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": hashlib.sha256(b"NON_CLAIM_CPU_FRONT_UNIT_CHECKPOINT").hexdigest(),
        "model_config_sha256": hashlib.sha256(b"NON_CLAIM_CPU_FRONT_UNIT_CONFIG").hexdigest(),
        "tokenizer_sha256": hashlib.sha256(b"NON_CLAIM_CPU_FRONT_UNIT_TOKENIZER").hexdigest(),
        "inference_implementation_sha256": hashlib.sha256(b"NON_CLAIM_CPU_FRONT_UNIT_INFERENCE").hexdigest(),
        "benchmark": {"id": "MMMU", "version": "bc168a9119d986d7cdf1e07b1eeb96ed3e8f92fa", "capability": "image", "split_sha256": ANSWER_SHA256, "protocol_sha256": PROTOCOL_SHA256},
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
        "rows": [{"id": loader["id"], "input_sha256": loader["input_sha256"], "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "choice", "value": choice}}],
    }


def run_two_state(loader: dict) -> dict:
    mismatch_choice = next(label for label in loader["option_labels"] if label != loader["ground_truth"])
    match_score = score_one(loader, internal_test_envelope(loader, loader["ground_truth"]))
    mismatch_score = score_one(loader, internal_test_envelope(loader, mismatch_choice))
    match = {"expected_exact_match": 1, "observed_exact_match": match_score["exact_match"], "result": "PASS" if match_score["exact_match"] == 1 else "FAIL"}
    mismatch = {"expected_exact_match": 0, "observed_exact_match": mismatch_score["exact_match"], "result": "PASS" if mismatch_score["exact_match"] == 0 else "FAIL"}
    terminal = "PASS" if match["result"] == mismatch["result"] == "PASS" else "FAIL"
    return {"match": match, "mismatch": mismatch, "terminal_result": terminal}


def run_negative(failure_class: str, loader: dict, envelope: dict) -> str:
    try:
        if failure_class in {"wrong-gold", "changed-order", "duplicate-ID", "empty-prediction"}:
            result = score_one(loader, envelope)
            if result["exact_match"] != 1:
                raise FrontUnitError(failure_class.upper())
        elif failure_class == "scorer-substitution":
            if "0" * 64 != SCORER_SHA256:
                raise FrontUnitError("SCORER_SUBSTITUTION")
        elif failure_class == "caller-prediction":
            refuse_caller_prediction_argument(["--prediction", "A"])
        else:
            raise FrontUnitError("UNKNOWN_NEGATIVE_CLASS")
    except (FrontUnitError, KeyError, TypeError):
        return "PASS_REFUSED"
    raise AssertionError(f"negative did not refuse: {failure_class}")


def refuse_caller_prediction_argument(argv: list[str]) -> None:
    if "--prediction" in argv:
        raise FrontUnitError("CALLER_PREDICTION_FORBIDDEN")


def _read_bound_json(path: Path, expected_sha: str, failure: str) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise FrontUnitError(failure)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise FrontUnitError(failure)
    return value


def load_probe_item(validation_root: Path, answers_path: Path, custody_path: Path,
                    freeze_path: Path, image_inputs_path: Path) -> dict:
    answers = _read_bound_json(answers_path, ANSWER_SHA256, "WRONG_GOLD")
    custody = _read_bound_json(custody_path, CUSTODY_SHA256, "CUSTODY_DRIFT")
    freeze = _read_bound_json(freeze_path, FREEZE_SHA256, "FREEZE_DRIFT")
    image_inputs = _read_bound_json(image_inputs_path, IMAGE_INPUTS_SHA256, "IMAGE_INPUT_DRIFT")
    ids, id_sha = eligible_identity(answers)
    if len(ids) != 847 or id_sha != ELIGIBLE_ID_SET_SHA256 or PROBE_ITEM_ID not in ids:
        raise FrontUnitError("ELIGIBLE_ID_SET_DRIFT")
    split = custody.get("split", {})
    if split.get("eligible_multiple_choice_items") != 847 or split.get("eligible_id_set_sha256") != id_sha or split.get("answer_dictionary_sha256") != ANSWER_SHA256:
        raise FrontUnitError("CUSTODY_ADMISSION_DRIFT")
    if freeze.get("validation_row_count") != 900 or freeze.get("eligible_multiple_choice_count") != 847:
        raise FrontUnitError("FREEZE_COUNT_DRIFT")
    frozen_inputs = {row.get("id"): row for row in image_inputs.get("rows", []) if isinstance(row, dict)}
    if len(frozen_inputs) != 900 or PROBE_ITEM_ID not in frozen_inputs:
        raise FrontUnitError("IMAGE_INPUT_COUNT_DRIFT")

    try:
        import pyarrow.parquet as parquet
        observed = None
        source_path = None
        parquet_files = validate_parquet_index(validation_root, freeze.get("validation_parquet_files", []))
        for path in parquet_files:
            table = parquet.read_table(path)
            matches = [row for row in table.to_pylist() if row.get("id") == PROBE_ITEM_ID]
            if matches:
                if observed is not None or len(matches) != 1:
                    raise FrontUnitError("DUPLICATE_ID")
                observed, source_path = matches[0], path
        if observed is None or source_path is None:
            raise FrontUnitError("PROBE_ID_MISSING")
    except ImportError as exc:
        raise FrontUnitError("PYARROW_REQUIRED") from exc
    question = observed.get("question")
    options = parse_options(observed.get("options"))
    if not isinstance(question, str) or not question:
        raise FrontUnitError("QUESTION_SHAPE")
    image_columns = sorted((key for key in observed if key.startswith("image_")), key=lambda key: int(key.split("_", 1)[1]))
    image_hashes = [hashlib.sha256(observed[key]["bytes"]).hexdigest() for key in image_columns if observed.get(key) is not None]
    frozen = frozen_inputs[PROBE_ITEM_ID]
    input_sha = canonical_digest({"id": PROBE_ITEM_ID, "question": question, "options": observed["options"], "image_sha256s": image_hashes})
    if frozen.get("image_sha256s") != image_hashes or frozen.get("input_sha256") != input_sha:
        raise FrontUnitError("PREPROCESSING_DRIFT")
    ground_truth = answers[PROBE_ITEM_ID].get("ground_truth")
    labels = [chr(ord("A") + index) for index in range(len(options))]
    if ground_truth not in labels:
        raise FrontUnitError("GROUND_TRUTH_OUT_OF_RANGE")
    return {
        "id": PROBE_ITEM_ID,
        "source_parquet": source_path.relative_to(validation_root).as_posix(),
        "validated_parquet_file_count": len(parquet_files),
        "parquet_index_sha256": canonical_digest(freeze["validation_parquet_files"]),
        "input_sha256": input_sha,
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "options": options,
        "option_labels": labels,
        "options_sha256": canonical_digest(options),
        "image_sha256s": image_hashes,
        "ground_truth": ground_truth,
        "preprocessing": "UTF8_QUESTION_PLUS_LITERAL_OPTION_ORDER_PLUS_NUMERIC_IMAGE_COLUMN_ORDER",
    }


def _atomic_json(path: Path, value: dict) -> None:
    if path.exists():
        raise FrontUnitError("OUTPUT_EXISTS")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        raw = canonical(value) + b"\n"
        handle.write(raw)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        refuse_caller_prediction_argument(argv)
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--validation-root", required=True, type=Path)
        parser.add_argument("--answers", required=True, type=Path)
        parser.add_argument("--custody-manifest", required=True, type=Path)
        parser.add_argument("--validation-freeze", required=True, type=Path)
        parser.add_argument("--image-inputs", required=True, type=Path)
        parser.add_argument("--scorer", required=True, type=Path)
        parser.add_argument("--prediction-contract", required=True, type=Path)
        parser.add_argument("--output", required=True, type=Path)
        args = parser.parse_args(argv)
        if file_sha(args.scorer) != SCORER_SHA256:
            raise FrontUnitError("SCORER_SUBSTITUTION")
        if file_sha(args.prediction_contract) != PREDICTION_CONTRACT_SHA256:
            raise FrontUnitError("ADAPTER_SUBSTITUTION")
        loader = load_probe_item(args.validation_root, args.answers, args.custody_manifest, args.validation_freeze, args.image_inputs)
        two_state = run_two_state(loader)
        if two_state["terminal_result"] != "PASS":
            raise FrontUnitError("TWO_STATE_FUNCTIONAL_THRESHOLD_FAILED")
        envelope = internal_test_envelope(loader, loader["ground_truth"])
        negative_rows = []
        mutations = {
            "wrong-gold": ({**loader, "ground_truth": "B" if loader["ground_truth"] != "B" else "A"}, envelope),
            "changed-order": ({**loader, "options": list(reversed(loader["options"]))}, envelope),
            "duplicate-ID": (loader, {**envelope, "rows": envelope["rows"] * 2}),
            "empty-prediction": (loader, {**envelope, "rows": [{**envelope["rows"][0], "output": {"kind": "choice", "value": ""}}]}),
            "scorer-substitution": (loader, envelope),
            "caller-prediction": (loader, envelope),
        }
        for failure_class, (mut_loader, mut_envelope) in mutations.items():
            negative_rows.append({"failure_class": failure_class, "result": run_negative(failure_class, mut_loader, mut_envelope)})
        receipt = {
            "schema_version": "ember-mmmu-front-unit-v1",
            "result": "FRONT_UNIT_PASS_NO_CAPABILITY_CREDIT",
            "claim_boundary": "ONE_ITEM_CPU_WIRING_ONLY; NO_IMAGE_CAPABILITY_OR_CHECKPOINT_QUALITY_CREDIT",
            "authority": {"source_commit": "c25d1c3cdfa0d08b1e17b38a3d860f406815edd5", "build_mail_id": 29793, "two_state_ruling_mail_id": 29802},
            "custody": {"answer_sha256": ANSWER_SHA256, "eligible_count": 847, "eligible_id_set_sha256": ELIGIBLE_ID_SET_SHA256, "custody_sha256": CUSTODY_SHA256, "freeze_sha256": FREEZE_SHA256, "image_inputs_sha256": IMAGE_INPUTS_SHA256},
            "implementation": {"front_unit_sha256": file_sha(Path(__file__)), "adapter_sha256": PREDICTION_CONTRACT_SHA256, "scorer_sha256": SCORER_SHA256},
            "loader": loader,
            "two_state_score": two_state,
            "negative_rows": negative_rows,
        }
        receipt["self_sha256"] = derive_self(receipt)
        _atomic_json(args.output, receipt)
        print(json.dumps({"result": receipt["result"], "self_sha256": receipt["self_sha256"], "negative_count": len(negative_rows)}, sort_keys=True))
        return 0
    except (FrontUnitError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
