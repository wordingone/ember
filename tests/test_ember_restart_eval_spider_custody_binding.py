# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_spider.py"


def test_spider_refuses_scoring_without_a_frozen_custody_manifest_binding():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "spider"
        source.mkdir()
        (source / "evaluation.py").write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(*args): print_scores({\"all\": {\"exact\": 1.0}}, \"match\")\n", encoding="utf-8")
        gold = root / "gold.sql"
        predictions = root / "predictions.json"
        tables = root / "tables.json"
        database = root / "database"
        output = root / "score.json"
        gold.write_text("select 1\n", encoding="utf-8")
        predictions.write_text('[{"index": 0, "sql": "select 1"}]', encoding="utf-8")
        tables.write_text("[]", encoding="utf-8")
        database.mkdir()

        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--spider-root",
                str(source),
                "--gold",
                str(gold),
                "--predictions",
                str(predictions),
                "--database-dir",
                str(database),
                "--tables",
                str(tables),
                "--score-output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )

        assert completed.returncode != 0
        assert not output.exists()


def test_spider_scores_only_assets_bound_by_frozen_custody_manifest():
    import hashlib

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "spider"
        source.mkdir()
        evaluator = source / "evaluation.py"
        evaluator.write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(*args): print_scores({\"all\": {\"exact\": 1.0}}, \"match\")\n", encoding="utf-8")
        gold = root / "gold.sql"
        predictions = root / "predictions.json"
        tables = root / "tables.json"
        database = root / "database"
        database.mkdir()
        database_file = database / "fixture.sqlite"
        manifest = root / "frozen-sql.json"
        output = root / "score.json"
        gold.write_text("select 1\n", encoding="utf-8")
        predictions.write_text('[{"index": 0, "sql": "select 1"}]', encoding="utf-8")
        tables.write_text("[]", encoding="utf-8")
        database_file.write_bytes(b"sqlite-fixture")
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.write_text(json.dumps({
            "result": "PREFLIGHT_ONLY",
            "benchmark_id": "spider",
            "benchmark_version": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c",
            "gold_sha256": sha(gold),
            "tables_sha256": sha(tables),
            "database_tree_sha256": hashlib.sha256(b"fixture.sqlite\0" + database_file.read_bytes()).hexdigest(),
            "evaluator_sha256": sha(evaluator),
        }), encoding="utf-8")

        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--frozen-sql-manifest", str(manifest),
                "--spider-root", str(source), "--gold", str(gold),
                "--predictions", str(predictions), "--database-dir", str(database),
                "--tables", str(tables), "--score-output", str(output),
            ],
            capture_output=True, text=True,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["metrics"] == {"exact_match": 1.0}