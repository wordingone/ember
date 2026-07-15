# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
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
        "result": "PREFLIGHT_ONLY",
        "benchmark_id": "spider",
        "benchmark_version": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c",
        "gold_sha256": sha(gold),
        "tables_sha256": sha(tables),
        "database_tree_sha256": hashlib.sha256(b"fixture.sqlite\0" + database_file.read_bytes()).hexdigest(),
        "evaluator_sha256": sha(spider / "evaluation.py"),
    }), encoding="utf-8")
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