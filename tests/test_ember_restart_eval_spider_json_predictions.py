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


def test_converts_central_json_list_predictions_to_private_spider_sql_lines():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        spider = root / "spider"
        spider.mkdir()
        gold = root / "gold.sql"
        predictions = root / "predictions.json"
        tables = root / "tables.json"
        database = root / "database"
        database.mkdir()
        score = root / "score.json"
        gold.write_text("select 1\tdb\n", encoding="utf-8")
        predictions.write_text(json.dumps([{"index": 0, "sql": "select 1"}]), encoding="utf-8")
        tables.write_text("[]", encoding="utf-8")
        evaluator = spider / "evaluation.py"
        evaluator.write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(gold,pred,db,etype,kmaps):\n assert open(pred).read()=='select 1\\n'\n print_scores({'all':{'count':1,'exact':1.0}},etype)\n", encoding="utf-8")
        database_file = database / "fixture.sqlite"
        database_file.write_bytes(b"sqlite-fixture")
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = root / "frozen-sql.json"
        manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "spider", "benchmark_version": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c", "gold_sha256": sha(gold), "tables_sha256": sha(tables), "database_tree_sha256": hashlib.sha256(b"fixture.sqlite\0" + database_file.read_bytes()).hexdigest(), "evaluator_sha256": sha(evaluator), "source_tree_sha256": hashlib.sha256(b"evaluation.py\0" + evaluator.read_bytes()).hexdigest()}), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-sql-manifest", str(manifest), "--spider-root", str(spider), "--gold", str(gold), "--predictions", str(predictions), "--database-dir", str(database), "--tables", str(tables), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(score.read_text(encoding="utf-8"))["sample_count"] == 1