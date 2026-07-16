# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_result_surface.py'
def test_refuses_to_overwrite_existing_result_surface():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);source=root/'source';output=root/'output';source.write_text(json.dumps({'result':'PREFLIGHT_ONLY'}));output.write_text('preserve')
  result=subprocess.run([sys.executable,str(SCRIPT),'--input',str(source),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and output.read_text()=='preserve'

def test_result_surface_replace_failure_cleans_real_cli_temporary_output(monkeypatch,tmp_path):
 import importlib.util,pytest
 specification=importlib.util.spec_from_file_location('result_surface_cleanup',SCRIPT);module=importlib.util.module_from_spec(specification);specification.loader.exec_module(module)
 source=tmp_path/'source';output=tmp_path/'output';source.write_text(json.dumps({'result':'PREFLIGHT_ONLY','capability':'audio'}))
 monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--input',str(source),'--output',str(output)])
 monkeypatch.setattr(module.os,'replace',lambda *_: (_ for _ in ()).throw(OSError('replace denied')))
 with pytest.raises(OSError,match='replace denied'):module.main()
 assert not output.exists()
 assert not list(tmp_path.glob('tmp*'))