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

import pytest

import pyarrow as pa
import pyarrow.parquet as pq

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_spider_validation_freeze.py"

REVISION = "0c350918f3f29ec754f1181c65cdce76cd6c133c"


def expected_protocol(dataset_root: Path) -> str:
    spec = importlib.util.spec_from_file_location("spider_validation_protocol", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    split = dataset_root / "spider" / "validation-00000-of-00001.parquet"
    return module.derived_protocol_sha256(REVISION, hashlib.sha256(split.read_bytes()).hexdigest(), hashlib.sha256((dataset_root / "README.md").read_bytes()).hexdigest())



def test_freezes_exact_spider_validation_pairs_without_claiming_runnable_sql_scoring():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense:\n- cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "spider" / "validation-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"db_id": ["a", "b"], "question": ["one", "two"], "query": ["select 1", "select 2"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", REVISION, "--protocol-sha256", expected_protocol(root), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["admission"] == "NOT_EXECUTABLE_NO_FROZEN_DATABASE_ASSETS"
        assert payload["task_count"] == 2
        assert payload["split_sha256"] == hashlib.sha256(split.read_bytes()).hexdigest()
        assert payload["references_sha256"] == payload["split_sha256"]
        assert payload["scoring_adapter"]["path"] == "scripts/ember_restart_eval_spider.py"
        assert payload["scoring_adapter"]["sha256"] == hashlib.sha256((SCRIPT.parents[1] / "scripts" / "ember_restart_eval_spider.py").read_bytes()).hexdigest()


def test_refuses_spider_validation_pairs_without_unique_nonempty_sql_rows():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "spider" / "validation-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"db_id": ["a", "a"], "question": ["one", "one"], "query": ["select 1", "select 1"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", REVISION, "--protocol-sha256", expected_protocol(root), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()

def test_cleans_temporary_payload_when_final_spider_validation_publication_fails(monkeypatch):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "spider" / "validation-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"db_id": ["a"], "question": ["one"], "query": ["select 1"]}), split)
        output = root / "frozen.json"
        spec = importlib.util.spec_from_file_location("spider_validation_publication", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--dataset-root", str(root), "--revision", REVISION, "--protocol-sha256", expected_protocol(root), "--output", str(output)])
        monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace denied")))
        with pytest.raises(OSError, match="replace denied"):
            module.main()
        assert not output.exists()
        assert not list(root.glob("frozen.json.*.tmp"))

def test_spider_validation_freezer_rejects_caller_protocol_substitution():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense:\n- cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "spider" / "validation-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"db_id": ["a"], "question": ["one"], "query": ["select 1"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", REVISION, "--protocol-sha256", "0" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()

def test_public_spider_validation_protocol_binds_split_license_and_adapter():
    payload = json.loads((SCRIPT.parents[1] / "manifests" / "ember-restart-spider-validation-pairs-protocol-v1.json").read_text(encoding="utf-8"))
    assert payload["benchmark_version"] == REVISION
    assert payload["split_sha256"] == payload["references_sha256"]
    assert payload["scoring_adapter"]["sha256"] == hashlib.sha256((SCRIPT.parents[1] / "scripts" / "ember_restart_eval_spider.py").read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("spider_validation_public_protocol", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert payload["protocol_sha256"] == module.derived_protocol_sha256(REVISION, payload["split_sha256"], payload["license_sha256"])
