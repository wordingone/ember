# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_execution_runner.py"
def base(root,predictions,score,out):
 checkpoint=root/"checkpoint";split=root/"split";harness=root/"harness";protocol=root/"protocol"
 for x in(checkpoint,split,harness,protocol):x.write_text(x.name)
 return[sys.executable,str(SCRIPT),"--capability","text","--checkpoint-manifest",str(checkpoint),"--benchmark-id","x","--benchmark-version","v1","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(predictions),"--result-artifact",str(score),"--output",str(out)]
def test_derives_criterion_from_evaluator_score_envelope():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);pred=root/"p";score=root/"s";out=root/"o";runner=root/"r.py";runner.write_text("import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps([{'id':'1'}]))\nPath(sys.argv[2]).write_text(json.dumps({'metrics':{'accuracy':1.0},'criterion_id':'ember-3b-text-capability-v1','criterion_result':'PASSED','sample_count':1}))\n")
  r=subprocess.run(base(root,pred,score,out)+["--",sys.executable,str(runner),str(pred),str(score)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr;assert json.loads(out.read_text())["criterion_result"]=="PASSED"
def test_timeout_fails_closed_without_publishing_output():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);pred=root/"p";score=root/"s";out=root/"o";runner=root/"r.py";runner.write_text("import time\ntime.sleep(2)\n");r=subprocess.run(base(root,pred,score,out)+["--timeout-seconds","1","--",sys.executable,str(runner)],text=True,capture_output=True,check=False);assert r.returncode!=0 and not out.exists()
