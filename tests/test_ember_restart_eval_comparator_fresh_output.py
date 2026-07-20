# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_comparator_preflight.py'
def test_refuses_to_overwrite_existing_comparison_preflight():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);target=root/'t';comparator=root/'c';output=root/'o';shared={'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':'text','benchmark_id':'x','benchmark_version':'v1','split_sha256':'a'*64,'harness_sha256':'b'*64,'protocol_sha256':'c'*64};target.write_text(json.dumps({**shared,'subject_checkpoint_sha256':'d'*64}));comparator.write_text(json.dumps({**shared,'subject_checkpoint_sha256':'e'*64,'subject_kind':'open_comparator','comparator_revision':'f'*40,'comparator_size_class':'open_3b'}));output.write_text('preserve')
  result=subprocess.run([sys.executable,str(SCRIPT),'--target',str(target),'--comparator',str(comparator),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and output.read_text()=='preserve'
