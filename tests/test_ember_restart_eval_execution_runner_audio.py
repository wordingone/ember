# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import subprocess,sys,tempfile
from pathlib import Path

SCRIPT=Path(__file__).parents[1]/'scripts'/'ember_restart_eval_execution_runner.py'
def test_accepts_audiobench_closed_run_argument_before_command_validation():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';run=root/'run';raw=root/'raw';score=root/'score';output=root/'output'
  for path in(checkpoint,split,harness,protocol,run):path.write_text(path.name)
  result=subprocess.run([sys.executable,str(SCRIPT),'--capability','audio','--checkpoint-manifest',str(checkpoint),'--benchmark-id','audiobench','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(raw),'--closed-run-artifact',str(run),'--result-artifact',str(score),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and 'evaluator command is required after --' in result.stderr

def test_forwards_closed_run_before_preflight_subprocess():
 source=SCRIPT.read_text()
 assert 'return subprocess.run(command,check=False).returncode\n if a.closed_run_artifact' not in source
 assert 'if a.closed_run_artifact is not None:command.extend(["--closed-run-artifact",str(a.closed_run_artifact)])\n return subprocess.run(command,check=False).returncode' in source
