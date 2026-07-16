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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_arc_challenge.py"


def _predictions(*, benchmark_id, version, split_sha256, protocol_sha256, rows):
    return {"schema_version":"ember-owned-predictions-v1","claim_status":"NON_ADMISSIBLE_RAW_PREDICTIONS","checkpoint_manifest_sha256":"a"*64,"model_config_sha256":"b"*64,"tokenizer_sha256":"c"*64,"inference_implementation_sha256":"d"*64,"benchmark":{"id":benchmark_id,"version":version,"capability":"reasoning","split_sha256":split_sha256,"protocol_sha256":protocol_sha256},"decoding":{"strategy":"GREEDY_AUTOREGRESSIVE","teacher_forcing":False,"max_new_tokens":1,"temperature":0,"top_p":1,"stop_token_ids":[2]},"rows":rows}


def test_scores_arc_canonical_predictions_against_byte_bound_frozen_parquet():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary); references=root/'arc.parquet'; manifest=root/'manifest.json'; predictions=root/'predictions.json'; score=root/'score.json'
        choices=pa.array([{"text":["one","two"],"label":["A","B"]},{"text":["three","four"],"label":["A","B"]}])
        pq.write_table(pa.table({"id":["arc-1","arc-2"],"question":["q1","q2"],"choices":choices,"answerKey":["A","B"]}),references)
        reference_sha256=hashlib.sha256(references.read_bytes()).hexdigest(); protocol_sha256='e'*64; version='210d026faf9955653af8916fad021475a3f00453'
        manifest.write_text(json.dumps({"result":"PREFLIGHT_ONLY","benchmark_id":"arc-challenge","benchmark_version":version,"capability":"reasoning","references_sha256":reference_sha256,"split_sha256":reference_sha256,"protocol_sha256":protocol_sha256,"task_count":2}),encoding='utf-8')
        predictions.write_text(json.dumps(_predictions(benchmark_id='arc-challenge',version=version,split_sha256=reference_sha256,protocol_sha256=protocol_sha256,rows=[{"id":"arc-1","input_sha256":"0"*64,"generated_token_ids":[2],"stop_reason":"eos","output":{"kind":"text","text":"A"}},{"id":"arc-2","input_sha256":"1"*64,"generated_token_ids":[2],"stop_reason":"eos","output":{"kind":"text","text":"A"}}])),encoding='utf-8')
        completed=subprocess.run([sys.executable,str(SCRIPT),'--frozen-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(score)],capture_output=True,text=True)
        assert completed.returncode==0,completed.stderr
        payload=json.loads(score.read_text(encoding='utf-8'))
        assert payload['result']=='PREFLIGHT_ONLY' and payload['claim_status']=='NON_ADMISSIBLE_FROZEN_ARC_CHALLENGE_SCORER'
        assert payload['metrics']=={'accuracy':0.5} and payload['sample_count']==2
        assert payload['predictions_sha256']==hashlib.sha256(predictions.read_bytes()).hexdigest()


def test_rejects_arc_predictions_with_detached_frozen_split_identity():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary); references=root/'arc.parquet'; manifest=root/'manifest.json'; predictions=root/'predictions.json'; score=root/'score.json'
        choices=pa.array([{"text":["one","two"],"label":["A","B"]}]); pq.write_table(pa.table({"id":["arc-1"],"question":["q1"],"choices":choices,"answerKey":["A"]}),references)
        reference_sha256=hashlib.sha256(references.read_bytes()).hexdigest(); version='210d026faf9955653af8916fad021475a3f00453'
        manifest.write_text(json.dumps({"result":"PREFLIGHT_ONLY","benchmark_id":"arc-challenge","benchmark_version":version,"capability":"reasoning","references_sha256":reference_sha256,"split_sha256":reference_sha256,"protocol_sha256":"e"*64,"task_count":1}),encoding='utf-8')
        predictions.write_text(json.dumps(_predictions(benchmark_id='arc-challenge',version=version,split_sha256='f'*64,protocol_sha256='e'*64,rows=[{"id":"arc-1","input_sha256":"0"*64,"generated_token_ids":[2],"stop_reason":"eos","output":{"kind":"text","text":"A"}}])),encoding='utf-8')
        completed=subprocess.run([sys.executable,str(SCRIPT),'--frozen-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(score)],capture_output=True,text=True)
        assert completed.returncode!=0 and not score.exists()