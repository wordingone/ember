# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_spider.py"


def frozen_manifest(root, spider, gold, tables, database):
    database_file = database / "fixture.sqlite"
    database_file.write_bytes(b"sqlite-fixture")
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = root / "frozen-sql.json"
    manifest.write_text(json.dumps({
        "schema_version": "ember-restart-benchmark-custody-v1",
        "result": "PREFLIGHT_ONLY",
        "benchmark_id": "spider",
        "benchmark_version": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c",
        "upstream_tree_git_sha1": "7687d1f709b5f2a645835d0c6c2ac13796e33491",
        "license_sha256": "a8d1d88a0f9cce3cdbff73b03a80dc5e5d69e3ba2443946c268815a550c9e0ec",
        "gold_sha256": sha(gold),
        "tables_sha256": sha(tables),
        "database_tree_sha256": hashlib.sha256(b"fixture.sqlite\0" + database_file.read_bytes()).hexdigest(),
        "evaluator": {"path": "evaluation.py", "sha256": sha(spider / "evaluation.py")},
        "evaluator_sha256": sha(spider / "evaluation.py"),
        "source_tree_sha256": hashlib.sha256(b"".join(path.relative_to(spider).as_posix().encode("utf-8") + b"\0" + path.read_bytes() for path in sorted(spider.rglob("*")) if path.is_file() and "__pycache__" not in path.parts)).hexdigest(),
        "scoring_adapter": {"path": "scripts/ember_restart_eval_spider.py", "sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(), "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE"},
        "admission": "NOT_EXECUTABLE_FIXTURE_ONLY",
    }), encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location("spider_protocol_helper", SCRIPT)
    module = importlib.util.module_from_spec(spec); assert spec.loader is not None; spec.loader.exec_module(module)
    payload = json.loads(manifest.read_text(encoding="utf-8")); payload["protocol_sha256"] = module.spider_protocol_sha256(payload, {"gold_sha256": payload["gold_sha256"], "tables_sha256": payload["tables_sha256"], "database_tree_sha256": payload["database_tree_sha256"], "evaluator_sha256": payload["evaluator_sha256"], "source_tree_sha256": payload["source_tree_sha256"]}); manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def test_executes_local_spider_scorer_and_derives_coverage_from_predictions():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        spider = root / "spider"
        spider.mkdir()
        predictions = root / "predictions.sql"
        gold = root / "gold.sql"
        tables = root / "tables.json"
        database = root / "database"
        database.mkdir()
        score = root / "score.json"
        predictions.write_text("select 1\ndrop table nope\n", encoding="utf-8")
        gold.write_text("select 1\tdb\nselect 2\tdb\n", encoding="utf-8")
        tables.write_text("[]", encoding="utf-8")
        (spider / "evaluation.py").write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(gold,pred,db,etype,kmaps):\n print_scores({'all':{'count':2,'exact':0.5}},etype)\n", encoding="utf-8")
        manifest = frozen_manifest(root, spider, gold, tables, database)
        result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-sql-manifest", str(manifest), "--spider-root", str(spider), "--gold", str(gold), "--predictions", str(predictions), "--database-dir", str(database), "--tables", str(tables), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(score.read_text(encoding="utf-8"))
        assert payload["metrics"] == {"exact_match": 0.5}
        assert payload["sample_count"] == 2
        assert payload["criterion_id"] == "ember-3b-tool-capability-v1"
        assert payload["criterion_result"] == "FAILED"
        assert payload["result"] == "SELFTEST"


def test_upstream_scorer_exception_fails_closed_without_score_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        spider = root / "spider"
        spider.mkdir()
        predictions = root / "predictions.sql"
        gold = root / "gold.sql"
        tables = root / "tables.json"
        database = root / "database"
        database.mkdir()
        score = root / "score.json"
        predictions.write_text("select 1\n", encoding="utf-8")
        gold.write_text("select 1\tdb\n", encoding="utf-8")
        tables.write_text("[]", encoding="utf-8")
        (spider / "evaluation.py").write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(*args): raise RuntimeError('bad upstream')\n", encoding="utf-8")
        manifest = frozen_manifest(root, spider, gold, tables, database)
        result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-sql-manifest", str(manifest), "--spider-root", str(spider), "--gold", str(gold), "--predictions", str(predictions), "--database-dir", str(database), "--tables", str(tables), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode != 0 and "pinned Spider scorer failed" in result.stderr and not score.exists()

def test_canonical_spider_evaluator_cannot_swap_gold_after_custody_check():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        spider = root / "spider"; spider.mkdir()
        gold = root / "gold.sql"; tables = root / "tables.json"
        database = root / "database"; database.mkdir()
        predictions = root / "predictions.json"; score = root / "score.json"
        gold.write_text("select 1\tdb\n", encoding="utf-8")
        tables.write_text("[]", encoding="utf-8")
        (database / "fixture.sqlite").write_bytes(b"sqlite-fixture")
        evaluation = spider / "evaluation.py"
        evaluation.write_text(
            "def build_foreign_key_map_from_json(path):\n"
            " open(path, 'w', encoding='utf-8').write('[]')\n"
            f" open({str(gold)!r}, 'w', encoding='utf-8').write('swapped\\tdb\\n')\n"
            " return {}\n"
            "def evaluate(gold,pred,db,etype,kmaps):\n"
            " exact = 1.0 if open(gold, encoding='utf-8').read().startswith('select 1') else 0.0\n"
            " print_scores({'all': {'exact': exact}}, etype)\n",
            encoding="utf-8",
        )
        manifest = frozen_manifest(root, spider, gold, tables, database)
        predictions.write_text(json.dumps({
            "schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
            "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64,
            "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64,
            "benchmark": {"id": "spider", "version": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c", "capability": "tool", "split_sha256": hashlib.sha256(gold.read_bytes()).hexdigest(), "protocol_sha256": json.loads(manifest.read_text(encoding="utf-8"))["protocol_sha256"]},
            "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
            "rows": [{"id": "0", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "sql", "sql": "select 1"}}],
        }), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-sql-manifest", str(manifest), "--spider-root", str(spider), "--gold", str(gold), "--canonical-predictions", str(predictions), "--database-dir", str(database), "--tables", str(tables), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(score.read_text(encoding="utf-8"))["metrics"] == {"exact_match": 1.0}

def test_custody_manifest_is_read_once_for_validation_and_receipt_hash(monkeypatch):
    spec = importlib.util.spec_from_file_location("ember_restart_eval_spider", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        spider = root / "spider"; spider.mkdir()
        gold = root / "gold.sql"; tables = root / "tables.json"
        database = root / "database"; database.mkdir()
        gold.write_text("select 1\tdb\n", encoding="utf-8")
        tables.write_text("[]", encoding="utf-8")
        (spider / "evaluation.py").write_text("# fixture\n", encoding="utf-8")
        manifest = frozen_manifest(root, spider, gold, tables, database)
        original_read_bytes = Path.read_bytes
        original_read_text = Path.read_text
        reads = 0
        def once(self, *args, **kwargs):
            nonlocal reads
            if self == manifest:
                reads += 1
                if reads > 1:
                    raise AssertionError("custody manifest reopened after validation")
            if args or kwargs:
                return original_read_text(self, *args, **kwargs)
            return original_read_bytes(self)
        monkeypatch.setattr(Path, "read_bytes", once)
        monkeypatch.setattr(Path, "read_text", once)
        assert module.verify_frozen_custody(manifest, spider, gold, tables, database) == hashlib.sha256(original_read_bytes(manifest)).hexdigest()
        assert reads == 1

def test_spider_custody_rejects_imported_helper_drift_after_manifest_binding():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); spider = root / "spider"; spider.mkdir(); gold = root / "gold.sql"; tables = root / "tables.json"; database = root / "database"; database.mkdir(); predictions = root / "predictions.sql"; score = root / "score.json"
        gold.write_text("select 1\tdb\n", encoding="utf-8"); tables.write_text("[]", encoding="utf-8"); predictions.write_text("select 1\n", encoding="utf-8")
        (spider / "helper.py").write_text("EXACT = 1.0\n", encoding="utf-8")
        (spider / "evaluation.py").write_text("from helper import EXACT\ndef build_foreign_key_map_from_json(path): return {}\ndef evaluate(gold,pred,db,etype,kmaps): print_scores({'all':{'exact':EXACT}},etype)\n", encoding="utf-8")
        manifest = frozen_manifest(root, spider, gold, tables, database)
        (spider / "helper.py").write_text("EXACT = 0.0\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-sql-manifest", str(manifest), "--spider-root", str(spider), "--gold", str(gold), "--predictions", str(predictions), "--database-dir", str(database), "--tables", str(tables), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not score.exists()
def test_spider_score_replace_failure_cleans_real_cli_temporary_output(monkeypatch, tmp_path):
    import pytest
    spec = importlib.util.spec_from_file_location("spider_cleanup", SCRIPT); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    spider = tmp_path / "spider"; spider.mkdir(); gold = tmp_path / "gold.sql"; tables = tmp_path / "tables.json"; database = tmp_path / "database"; database.mkdir(); predictions = tmp_path / "predictions.sql"; score = tmp_path / "score.json"
    gold.write_text("select 1\tdb\n", encoding="utf-8"); tables.write_text("[]", encoding="utf-8"); predictions.write_text("select 1\n", encoding="utf-8")
    (spider / "evaluation.py").write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(gold,pred,db,etype,kmaps): print_scores({'all': {'exact': 1.0}}, etype)\n", encoding="utf-8")
    manifest = frozen_manifest(tmp_path, spider, gold, tables, database)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--frozen-sql-manifest", str(manifest), "--spider-root", str(spider), "--gold", str(gold), "--predictions", str(predictions), "--database-dir", str(database), "--tables", str(tables), "--score-output", str(score)])
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace denied")))
    with pytest.raises(OSError, match="replace denied"):
        module.main()
    assert not score.exists()
    assert not list(tmp_path.glob("score.json.*.tmp"))
