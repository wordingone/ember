# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_execution_runner.py"

def base_args(root, predictions, score, output):
    checkpoint=root/"checkpoint-manifest.json"; split=root/"split"; harness=root/"harness"; protocol=root/"protocol"
    for path in (checkpoint,split,harness,protocol): path.write_text(path.name)
    return [sys.executable,str(SCRIPT),"--capability","text","--checkpoint-manifest",str(checkpoint),"--benchmark-id","unit","--benchmark-version","v1","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(predictions),"--result-artifact",str(score),"--output",str(output)]

def test_derives_criterion_from_evaluator_score_envelope():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); predictions=root/"predictions.json"; score=root/"score.json"; output=root/"result.json"; runner=root/"runner.py"
        runner.write_text("import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps([{'id':'1'}]))\nPath(sys.argv[2]).write_text(json.dumps({'metrics':{'accuracy':1.0},'criterion_result':'PASSED'}))\n")
        result=subprocess.run(base_args(root,predictions,score,output)+["--",sys.executable,str(runner),str(predictions),str(score)],text=True,capture_output=True,check=False)
        assert result.returncode==0,result.stderr
        assert json.loads(output.read_text())["criterion_result"]=="PASSED"

def test_timeout_fails_closed_without_publishing_output():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); predictions=root/"predictions.json"; score=root/"score.json"; output=root/"result.json"; runner=root/"slow.py"
        runner.write_text("import time\ntime.sleep(2)\n")
        result=subprocess.run(base_args(root,predictions,score,output)+["--timeout-seconds","1","--",sys.executable,str(runner)],text=True,capture_output=True,check=False)
        assert result.returncode != 0
        assert not output.exists()
