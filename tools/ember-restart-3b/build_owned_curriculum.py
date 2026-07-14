# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generate deterministic owned multimodal curriculum records with local receipts."""
from __future__ import annotations
import argparse, base64, hashlib, json, random
from pathlib import Path
from verify_capability_record import expected_receipt

def _raw(seed: int, size: int) -> bytes:
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(size))

def records(count_per_domain: int) -> list[dict[str, object]]:
    if count_per_domain <= 0: raise ValueError('count_per_domain must be positive')
    result=[]
    for index in range(count_per_domain):
        image=_raw(index,48*48*3); audio=_raw(100000+index,640*2)
        result.append({'schema_version':'ember-owned-bootstrap-batch-v1','sample_id':f'owned-vision-{index:08d}','token_ids':[1,31998,10+(index%30000)],'target_ids':[2,11+(index%30000),12+(index%30000)],'active_expert':'vision','image_patches_u8_base64':[base64.b64encode(image).decode('ascii')],'image_coordinates':[[index%48,(index//48)%48]],'multimodal_spans':[{'start':1,'length':1,'modality':'image','attention_mode':'isolated'}]})
        result.append({'schema_version':'ember-owned-bootstrap-batch-v1','sample_id':f'owned-audio-{index:08d}','token_ids':[1,31999,20+(index%30000)],'target_ids':[2,21+(index%30000),22+(index%30000)],'active_expert':'audio','audio_frames_i16le_base64':[base64.b64encode(audio).decode('ascii')],'image_coordinates':[],'multimodal_spans':[{'start':1,'length':1,'modality':'audio','attention_mode':'causal'}]})
        a=index+1; b=(index*7)%997+1; target=a+b
        reasoning={'schema_version':'ember-owned-bootstrap-batch-v1','sample_id':f'owned-reasoning-{index:08d}','token_ids':[30+(index%30000),31+(index%30000),32+(index%30000)],'target_ids':[31+(index%30000),32+(index%30000),33+(index%30000)],'active_expert':'reasoning','image_coordinates':[],'multimodal_spans':[],'capability_evidence':{'reasoning':{'operands':[a,b],'target':target,'trace':[a,b,target]}}}; reasoning['capability_receipt']=expected_receipt(reasoning); result.append(reasoning)
        tool={'schema_version':'ember-owned-bootstrap-batch-v1','sample_id':f'owned-tool-{index:08d}','token_ids':[40+(index%30000),41+(index%30000),42+(index%30000)],'target_ids':[41+(index%30000),42+(index%30000),43+(index%30000)],'active_expert':'tool','image_coordinates':[],'multimodal_spans':[],'capability_evidence':{'tool':{'name':'owned_calculator','arguments':{'expression':f'{a}+{b}'},'observation':{'value':target}}}}; tool['capability_receipt']=expected_receipt(tool); result.append(tool)
    return result

def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument('--count-per-domain',type=int,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args(); payload={'schema_version':'ember-owned-pretraining-shard-v1','generator':'tools/ember-restart-3b/build_owned_curriculum.py','records':records(a.count_per_domain)}; raw=(json.dumps(payload,sort_keys=True,separators=(',',':'))+'\n').encode(); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_bytes(raw); print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'records':len(payload['records'])},sort_keys=True))
if __name__=='__main__': main()