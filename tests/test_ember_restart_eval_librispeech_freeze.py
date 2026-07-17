# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_librispeech_freeze.py"


def test_freezes_exact_librispeech_clean_test_references_as_nonadmissible_audio_inputs():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense:\n- cc-by-4.0\n---\n", encoding="utf-8")
        split = root / "clean" / "test" / "0000.parquet"
        split.parent.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["1-2-3", "1-2-4"], "text": ["FIRST WORDS", "SECOND WORDS"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--dataset-root", str(root),
            "--revision", "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1",
            "--protocol-sha256", "a" * 64, "--output", str(output),
        ], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "FROZEN_LIBRISPEECH_CLEAN_TEST_REFERENCES_NO_CHECKPOINT_BOUND_PREDICTIONS"
        assert payload["benchmark_id"] == "librispeech-clean-test"
        assert payload["capability"] == "audio"
        assert payload["task_count"] == 2
        assert payload["references_sha256"] == hashlib.sha256(split.read_bytes()).hexdigest()


def test_refuses_librispeech_duplicate_ids_or_blank_transcripts():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: cc-by-4.0\n---\n", encoding="utf-8")
        split = root / "clean" / "test" / "0000.parquet"
        split.parent.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["1-2-3", "1-2-3"], "text": ["", "WORDS"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--dataset-root", str(root),
            "--revision", "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1",
            "--protocol-sha256", "a" * 64, "--output", str(output),
        ], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()

def test_librispeech_freeze_replace_failure_cleans_real_cli_temporary_output(monkeypatch, tmp_path):
 import importlib.util,pytest
 spec=importlib.util.spec_from_file_location('librispeech_cleanup',SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 (tmp_path/'README.md').write_text('---\nlicense: cc-by-4.0\n---\n',encoding='utf-8');split=tmp_path/'clean'/'test'/'0000.parquet';split.parent.mkdir(parents=True);pq.write_table(pa.table({'id':['1-2-3'],'text':['WORDS']}),split);output=tmp_path/'frozen'
 monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--dataset-root',str(tmp_path),'--revision','a'*40,'--protocol-sha256','b'*64,'--output',str(output)]);monkeypatch.setattr(module.os,'replace',lambda *_: (_ for _ in ()).throw(OSError('replace denied')))
 with pytest.raises(OSError,match='replace denied'):module.main()
 assert not output.exists() and not list(tmp_path.glob('frozen.*.tmp'))

def test_librispeech_protocol_identity_is_not_caller_attested():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: cc-by-4.0\n---\n", encoding="utf-8")
        split = root / "clean" / "test" / "0000.parquet"
        split.parent.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["1-2-3"], "text": ["WORDS"]}), split)
        protocols = []
        for supplied in ("a" * 64, "b" * 64):
            output = root / ("freeze-" + supplied[0] + ".json")
            result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1", "--protocol-sha256", supplied, "--output", str(output)], text=True, capture_output=True, check=False)
            assert result.returncode == 0, result.stderr
            protocols.append(json.loads(output.read_text(encoding="utf-8"))["protocol_sha256"])
        assert protocols[0] == protocols[1]