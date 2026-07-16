# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_uncertainty.py'
def test_refuses_to_overwrite_existing_uncertainty_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);rows=root/'rows';out=root/'out';rows.write_text(json.dumps([{'correct':True}]));out.write_text('preserve')
  result=subprocess.run([sys.executable,str(SCRIPT),'--rows',str(rows),'--output',str(out)],capture_output=True,text=True)
  assert result.returncode!=0 and out.read_text()=='preserve'

def test_uncertainty_replace_failure_cleans_real_cli_temporary_output(monkeypatch,tmp_path):
 import importlib.util,pytest
 specification=importlib.util.spec_from_file_location('uncertainty_cleanup',SCRIPT);module=importlib.util.module_from_spec(specification);specification.loader.exec_module(module)
 rows=tmp_path/'rows';output=tmp_path/'output';rows.write_text(json.dumps([{'correct':True}]))
 monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--rows',str(rows),'--output',str(output)])
 monkeypatch.setattr(module.os,'replace',lambda *_: (_ for _ in ()).throw(OSError('replace denied')))
 with pytest.raises(OSError,match='replace denied'):module.main()
 assert not output.exists()
 assert not list(tmp_path.glob('tmp*'))
