#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute a pinned Spider scorer only from canonical checkpoint predictions."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ember_restart.prediction_contract import ContractError, validate_predictions


SPIDER_VERSION = "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c"


def rows(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def legacy_sql_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [line for line in raw.splitlines() if line.strip()]
    if not isinstance(value, list) or not value:
        raise ValueError("legacy Spider predictions must be non-empty SQL lines or a JSON list")
    result = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or row.get("index") != index or not isinstance(row.get("sql"), str):
            raise ValueError("legacy Spider JSON predictions require contiguous index and sql")
        result.append(row["sql"])
    return result


def canonical_sql(data: bytes, gold_sha256: str, protocol_sha256: str | None = None) -> tuple[dict, list[str]]:
    try:
        envelope = validate_predictions(json.loads(data.decode("utf-8")))
    except (ContractError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical checkpoint predictions are required") from error
    benchmark = envelope["benchmark"]
    if benchmark.get("id") != "spider" or benchmark.get("version") != SPIDER_VERSION or benchmark.get("capability") != "tool" or benchmark.get("split_sha256") != gold_sha256 or (protocol_sha256 is not None and benchmark.get("protocol_sha256") != protocol_sha256):
        raise ValueError("canonical Spider predictions do not bind frozen benchmark identity")
    result = []
    for index, row in enumerate(envelope["rows"]):
        output = row.get("output")
        if row.get("id") != str(index) or not isinstance(output, dict) or output.get("kind") != "sql" or not isinstance(output.get("sql"), str):
            raise ValueError("canonical Spider rows require contiguous SQL outputs")
        result.append(output["sql"])
    if not result:
        raise ValueError("canonical Spider predictions must be non-empty")
    return envelope, result


def load_evaluator(root: Path):
    source = root / "evaluation.py"
    if not source.is_file():
        raise ValueError("pinned Spider evaluation.py is required")
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.spec_from_file_location("ember_restart_pinned_spider", source)
        if spec is None or spec.loader is None:
            raise ValueError("could not load pinned Spider evaluation.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    if not files:
        raise ValueError("frozen Spider evaluator directory must contain files")
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()

def database_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError("frozen Spider database directory must contain files")
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def snapshot_spider_inputs(source: Path, gold: Path, tables: Path, database: Path, stage: Path) -> tuple[Path, Path, Path, Path]:
    staged_source = stage / "spider"
    staged_gold = stage / "gold.sql"
    staged_tables = stage / "tables.json"
    staged_database = stage / "database"
    shutil.copytree(source, staged_source, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(gold, staged_gold)
    shutil.copy2(tables, staged_tables)
    shutil.copytree(database, staged_database)
    return staged_source, staged_gold, staged_tables, staged_database

def verify_frozen_custody(path: Path, source: Path, gold: Path, tables: Path, database: Path, include_protocol: bool = False) -> str:
    try:
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid frozen Spider custody manifest: {error}") from error
    expected = {"gold_sha256": sha256_file(gold), "tables_sha256": sha256_file(tables), "database_tree_sha256": database_tree_sha256(database), "evaluator_sha256": sha256_file(source / "evaluation.py"), "source_tree_sha256": source_tree_sha256(source)}
    if not isinstance(manifest, dict) or manifest.get("result") != "PREFLIGHT_ONLY" or manifest.get("benchmark_id") != "spider" or manifest.get("benchmark_version") != SPIDER_VERSION or any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("frozen Spider custody manifest does not bind supplied evaluator assets")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return (digest, manifest.get("protocol_sha256")) if include_protocol else digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-sql-manifest", required=True, type=Path)
    parser.add_argument("--spider-root", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    predictions = parser.add_mutually_exclusive_group(required=True)
    predictions.add_argument("--canonical-predictions", type=Path)
    predictions.add_argument("--predictions", type=Path, help="legacy detached fixture input; produces SELFTEST only")
    parser.add_argument("--database-dir", required=True, type=Path)
    parser.add_argument("--tables", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.score_output.exists():
        parser.error("score output must not pre-exist")
    if not arguments.gold.is_file() or not arguments.tables.is_file() or not arguments.database_dir.is_dir():
        parser.error("gold, tables, and database directory are required")
    selected = arguments.canonical_predictions or arguments.predictions
    envelope = None
    if not selected.is_file():
        parser.error("prediction input must be a file")
    try:
        custody_sha256, protocol_sha256 = verify_frozen_custody(arguments.frozen_sql_manifest, arguments.spider_root, arguments.gold, arguments.tables, arguments.database_dir, include_protocol=True)
        if arguments.canonical_predictions is not None:
            prediction_bytes = arguments.canonical_predictions.read_bytes()
            envelope, sql = canonical_sql(prediction_bytes, sha256_file(arguments.gold), protocol_sha256)
        else:
            sql = legacy_sql_lines(arguments.predictions)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid Spider predictions: {error}")
    if len(sql) != rows(arguments.gold):
        parser.error("non-empty predictions must exactly cover the frozen gold rows")
    with tempfile.TemporaryDirectory(dir=selected.parent, prefix="ember-spider-inputs-") as scratch:
        staged_source, staged_gold, staged_tables, staged_database = snapshot_spider_inputs(
            arguments.spider_root, arguments.gold, arguments.tables, arguments.database_dir, Path(scratch)
        )
        if verify_frozen_custody(
            arguments.frozen_sql_manifest, staged_source, staged_gold, staged_tables, staged_database
        ) != custody_sha256:
            parser.error("staged Spider evaluator assets do not match frozen custody")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=scratch, prefix=selected.name + ".", suffix=".spider.tmp", delete=False) as handle:
            handle.write("\n".join(sql) + "\n")
            temporary = Path(handle.name)
        try:
            evaluator = load_evaluator(staged_source)
            foreign_keys = evaluator.build_foreign_key_map_from_json(str(staged_tables))
            captured = {}
            evaluator.print_scores = lambda scores, _etype: captured.update(scores)
            evaluator.evaluate(str(staged_gold), str(temporary), str(staged_database), "match", foreign_keys)
            exact = captured["all"]["exact"]
        except Exception as error:
            parser.error(f"pinned Spider scorer failed: {error}")
        finally:
            temporary.unlink(missing_ok=True)
    if isinstance(exact, bool) or not isinstance(exact, (int, float)) or not math.isfinite(exact):
        parser.error("pinned Spider scorer did not return finite exact match")
    payload = {"result": "PREFLIGHT_ONLY", "claim_status": "NON_ADMISSIBLE_FROZEN_SPIDER_SCORER", "metrics": {"exact_match": float(exact)}, "sample_count": len(sql), "criterion_id": "ember-3b-tool-capability-v1", "criterion_result": "FAILED", "frozen_sql_manifest_sha256": custody_sha256, "upstream": "pinned local Spider exact-match scorer"}
    if arguments.canonical_predictions is not None:
        payload.update({"benchmark_id": envelope["benchmark"]["id"], "benchmark_version": envelope["benchmark"]["version"], "split_sha256": envelope["benchmark"]["split_sha256"], "protocol_sha256": envelope["benchmark"]["protocol_sha256"], "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "predictions_sha256": hashlib.sha256(prediction_bytes).hexdigest()})
    else:
        payload["result"] = "SELFTEST"
    arguments.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.score_output.parent, prefix=arguments.score_output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.score_output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())