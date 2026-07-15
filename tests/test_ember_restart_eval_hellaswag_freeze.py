# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_hellaswag_freeze.py"
def test_freezes_exact_hellaswag_test_bytes_with_explicit_mit_card_evidence():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);(root/"README.md").write_text("# HellaSwag\n\n## Licensing Information\n\nMIT https://example.invalid/LICENSE\n",encoding="utf-8"); split=root/"data"/"test-00000-of-00001.parquet";split.parent.mkdir();pq.write_table(pa.table({"ind":[1,1],"source_id":["a","b"],"ctx":["a","b"],"endings":[["x","y"],["q","r"]],"label":["",""]}),split);out=root/'frozen';run=subprocess.run([sys.executable,str(SCRIPT),'--dataset-root',str(root),'--revision','218ec52e09a7e7462a5400043bb9a69a41d06b76','--protocol-sha256','a'*64,'--output',str(out)],capture_output=True,text=True);assert run.returncode==0,run.stderr;payload=json.loads(out.read_text());assert payload['result']=='PREFLIGHT_ONLY' and payload['admission']=='NOT_EXECUTABLE_NO_FROZEN_LABELS' and payload['claim_status']=='FROZEN_HELLASWAG_TEST_INPUTS_NO_FROZEN_LABELS' and payload['task_count']==2 and payload['split_sha256']==hashlib.sha256(split.read_bytes()).hexdigest()
def test_refuses_invalid_hellaswag_labels_or_duplicate_ids():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);(root/"README.md").write_text("MIT\n",encoding="utf-8");split=root/"data"/"test-00000-of-00001.parquet";split.parent.mkdir();pq.write_table(pa.table({"ind":[1,1],"source_id":["a","a"],"ctx":["a","b"],"endings":[["x"],["y"]],"label":["1","0"]}),split);out=root/'frozen';run=subprocess.run([sys.executable,str(SCRIPT),'--dataset-root',str(root),'--revision','218ec52e09a7e7462a5400043bb9a69a41d06b76','--protocol-sha256','a'*64,'--output',str(out)],capture_output=True,text=True);assert run.returncode!=0 and not out.exists()