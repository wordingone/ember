# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,hashlib,json,os,tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from ember_restart.prediction_contract import ContractError,validate_predictions
def h(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--frozen-manifest',type=Path,required=True);p.add_argument('--references',type=Path,required=True);p.add_argument('--predictions',type=Path,required=True);p.add_argument('--score-output',type=Path,required=True);a=p.parse_args()
 if a.score_output.exists():p.error('score output must not pre-exist')
 try:
  mb=a.frozen_manifest.read_bytes();rb=a.references.read_bytes();pb=a.predictions.read_bytes();m=json.loads(mb);rows=pq.read_table(pa.BufferReader(rb),columns=['question','answer']).to_pylist();refs={str(i):r['answer'].rsplit('####',1)[1].strip() for i,r in enumerate(rows)};e=validate_predictions(json.loads(pb));b=e['benchmark'];pred={r['id']:r['output']['text'].rsplit('####',1)[-1].strip() for r in e['rows'] if r['output'].get('kind')=='text'}
  if not refs or len(pred)!=len(e['rows']) or set(refs)!=set(pred) or not isinstance(m,dict) or m.get('result')!='PREFLIGHT_ONLY' or m.get('benchmark_id')!='gsm8k' or m.get('references_sha256')!=h(rb) or m.get('split_sha256')!=h(rb) or m.get('task_count')!=len(refs) or any(b.get(x)!=m.get(y) for x,y in {'id':'benchmark_id','version':'benchmark_version','split_sha256':'split_sha256','protocol_sha256':'protocol_sha256'}.items()):raise ValueError('frozen GSM8K manifest does not bind canonical prediction identity')
 except (OSError,ValueError,KeyError,UnicodeDecodeError,json.JSONDecodeError,ContractError,pa.ArrowException) as x:p.error(str(x))
 out={'result':'PREFLIGHT_ONLY','claim_status':'NON_ADMISSIBLE_FROZEN_GSM8K_SCORER','criterion_id':'ember-3b-reasoning-capability-v1','criterion_result':'FAILED','metrics':{'exact_match':sum(pred[k]==v for k,v in refs.items())/len(refs)},'sample_count':len(refs),'predictions_sha256':h(pb),'references_sha256':h(rb),'frozen_manifest_sha256':h(mb)};a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.score_output.parent,delete=False) as f:json.dump(out,f,sort_keys=True);f.write('\n');t=Path(f.name)
 try:os.replace(t,a.score_output)
 finally:t.unlink(missing_ok=True)
if __name__=='__main__':main()