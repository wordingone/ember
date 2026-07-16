# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_mmlu_pro_freeze.py"
def test_freezes_exact_mmlu_pro_test_bytes_without_replacing_inherited_hash_pin():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);(root/'README.md').write_text('---\nlicense: mit\n---\n',encoding='utf-8');split=root/'data'/'test-00000-of-00001.parquet';split.parent.mkdir();pq.write_table(pa.table({'question_id':[1,2],'question':['q1','q2'],'options':[['a','b'],['c','d']],'answer':['A','B'],'answer_index':[0,1],'cot_content':['x','y'],'category':['x','y'],'src':['x','y']}),split);out=root/'frozen';run=subprocess.run([sys.executable,str(SCRIPT),'--dataset-root',str(root),'--revision','b189ec765aa7ed75c8acfea42df31fdae71f97be','--protocol-sha256','a'*64,'--output',str(out)],capture_output=True,text=True);assert run.returncode==0,run.stderr;payload=json.loads(out.read_text());assert payload['result']=='PREFLIGHT_ONLY' and payload['claim_status']=='FROZEN_MMLU_PRO_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS' and payload['task_count']==2 and payload['split_sha256']==hashlib.sha256(split.read_bytes()).hexdigest()
def test_refuses_mmlu_pro_rows_with_duplicate_ids_or_unmatched_answers():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);(root/'README.md').write_text('---\nlicense: mit\n---\n',encoding='utf-8');split=root/'data'/'test-00000-of-00001.parquet';split.parent.mkdir();pq.write_table(pa.table({'question_id':[1,1],'question':['q1','q2'],'options':[['a'],['b']],'answer':['B','A'],'answer_index':[0,0],'cot_content':['x','y'],'category':['x','y'],'src':['x','y']}),split);out=root/'frozen';run=subprocess.run([sys.executable,str(SCRIPT),'--dataset-root',str(root),'--revision','b189ec765aa7ed75c8acfea42df31fdae71f97be','--protocol-sha256','a'*64,'--output',str(out)],capture_output=True,text=True);assert run.returncode!=0 and not out.exists()
def test_mmlu_pro_freeze_replace_failure_cleans_real_cli_temporary_output(monkeypatch, tmp_path):
 import importlib.util,pytest
 spec=importlib.util.spec_from_file_location("mmlu_cleanup",SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 (tmp_path/'README.md').write_text('---\nlicense: mit\n---\n',encoding='utf-8');split=tmp_path/'data'/'test-00000-of-00001.parquet';split.parent.mkdir();pq.write_table(pa.table({'question_id':[1],'question':['q1'],'options':[['a','b']],'answer':['A'],'answer_index':[0],'cot_content':['x'],'category':['x'],'src':['x']}),split);output=tmp_path/'frozen'
 monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--dataset-root',str(tmp_path),'--revision','a'*40,'--protocol-sha256','b'*64,'--output',str(output)])
 monkeypatch.setattr(module.os,'replace',lambda *_: (_ for _ in ()).throw(OSError('replace denied')))
 with pytest.raises(OSError,match='replace denied'):module.main()
 assert not output.exists() and not list(tmp_path.glob('frozen.*.tmp'))
