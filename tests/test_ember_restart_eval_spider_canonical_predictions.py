# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_spider.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_spider_requires_canonical_tool_predictions():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); spider = root / "spider"; database = root / "database"; spider.mkdir(); database.mkdir()
        gold = root / "gold.sql"; tables = root / "tables.json"; predictions = root / "predictions.json"; custody = root / "custody.json"; score = root / "score.json"
        gold.write_text("select 1\tdb\n", encoding="utf-8"); tables.write_text("[]", encoding="utf-8"); (database / "db.sqlite").write_bytes(b"db")
        (spider / "evaluation.py").write_text('def build_foreign_key_map_from_json(_): return {}\ndef evaluate(*_): print_scores({"all":{"exact":1.0}}, "match")\n', encoding="utf-8")
        custody_payload = {"schema_version": "ember-restart-benchmark-custody-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "spider", "benchmark_version": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c", "upstream_tree_git_sha1": "7687d1f709b5f2a645835d0c6c2ac13796e33491", "license_sha256": "a8d1d88a0f9cce3cdbff73b03a80dc5e5d69e3ba2443946c268815a550c9e0ec", "gold_sha256": digest(gold), "tables_sha256": digest(tables), "database_tree_sha256": hashlib.sha256(b"db.sqlite\0db").hexdigest(), "evaluator": {"path": "evaluation.py", "sha256": digest(spider / "evaluation.py")}, "evaluator_sha256": digest(spider / "evaluation.py"), "source_tree_sha256": hashlib.sha256(b"evaluation.py\0" + (spider / "evaluation.py").read_bytes()).hexdigest(), "scoring_adapter": {"path": "scripts/ember_restart_eval_spider.py", "sha256": digest(SCRIPT), "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE"}, "admission": "NOT_EXECUTABLE_FIXTURE_ONLY"}
        spec = importlib.util.spec_from_file_location("spider_protocol_fixture", SCRIPT); module = importlib.util.module_from_spec(spec); assert spec.loader is not None; spec.loader.exec_module(module)
        custody_payload["protocol_sha256"] = module.spider_protocol_sha256(custody_payload, {"gold_sha256": custody_payload["gold_sha256"], "tables_sha256": custody_payload["tables_sha256"], "database_tree_sha256": custody_payload["database_tree_sha256"], "evaluator_sha256": custody_payload["evaluator_sha256"], "source_tree_sha256": custody_payload["source_tree_sha256"]})
        custody.write_text(json.dumps(custody_payload), encoding="utf-8")
        predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "spider", "version": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c", "capability": "tool", "split_sha256": digest(gold), "protocol_sha256": json.loads(custody.read_text(encoding="utf-8"))["protocol_sha256"]}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "0", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "sql", "sql": "select 1"}}]}), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-sql-manifest", str(custody), "--spider-root", str(spider), "--gold", str(gold), "--canonical-predictions", str(predictions), "--database-dir", str(database), "--tables", str(tables), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(score.read_text(encoding="utf-8"))
        assert payload["predictions_sha256"] == digest(predictions)
        assert payload["benchmark_id"] == "spider"
        assert payload["checkpoint_manifest_sha256"] == "a" * 64
        assert payload["protocol_sha256"] == json.loads(custody.read_text(encoding="utf-8"))["protocol_sha256"]
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["criterion_result"] == "FAILED"

def test_spider_rejects_altered_protocol_identity(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("spider_protocol", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    envelope = {"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "spider", "version": module.SPIDER_VERSION, "capability": "tool", "split_sha256": "e" * 64, "protocol_sha256": "0" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "0", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "sql", "sql": "select 1"}}]}
    with pytest.raises(ValueError, match="canonical Spider predictions"):
        module.canonical_sql(json.dumps(envelope).encode(), "e" * 64, "1" * 64)
def test_spider_custody_requires_protocol_identity_for_canonical_scoring(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("spider_protocol_required", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    source = tmp_path / "spider"; source.mkdir(); (source / "evaluation.py").write_text("# evaluator\n", encoding="utf-8")
    gold = tmp_path / "gold.sql"; gold.write_text("select 1\tdb\n", encoding="utf-8")
    tables = tmp_path / "tables.json"; tables.write_text("[]", encoding="utf-8")
    database = tmp_path / "database"; database.mkdir(); (database / "db.sqlite").write_bytes(b"db")
    manifest = tmp_path / "custody.json"
    manifest.write_text(json.dumps({"schema_version": "ember-restart-benchmark-custody-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "spider", "benchmark_version": module.SPIDER_VERSION, "gold_sha256": digest(gold), "tables_sha256": digest(tables), "database_tree_sha256": hashlib.sha256(b"db.sqlite\0db").hexdigest(), "evaluator_sha256": digest(source / "evaluation.py"), "source_tree_sha256": module.source_tree_sha256(source)}), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol"):
        module.verify_frozen_custody(manifest, source, gold, tables, database, include_protocol=True)

def test_spider_rejects_well_formed_but_wrong_protocol_authority(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("spider_protocol_wrong_hex", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    source = tmp_path / "spider"; source.mkdir(); (source / "evaluation.py").write_text("# evaluator\n", encoding="utf-8")
    gold = tmp_path / "gold.sql"; gold.write_text("select 1\tdb\n", encoding="utf-8")
    tables = tmp_path / "tables.json"; tables.write_text("[]", encoding="utf-8")
    database = tmp_path / "database"; database.mkdir(); (database / "db.sqlite").write_bytes(b"db")
    manifest = tmp_path / "custody.json"
    manifest.write_text(json.dumps({"schema_version": "ember-restart-benchmark-custody-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "spider", "benchmark_version": module.SPIDER_VERSION, "gold_sha256": digest(gold), "tables_sha256": digest(tables), "database_tree_sha256": module.database_tree_sha256(database), "evaluator_sha256": digest(source / "evaluation.py"), "source_tree_sha256": module.source_tree_sha256(source), "protocol_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="protocol"):
        module.verify_frozen_custody(manifest, source, gold, tables, database, include_protocol=True)
