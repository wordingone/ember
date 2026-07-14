# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Manifest-bound non-claim-bearing owned-model prediction entrypoint."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import torch
from batch import decode_owned_batch
from checkpoint_artifacts import load_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder

def sha(path: Path) -> str:
 d=hashlib.sha256()
 with path.open('rb') as h:
  for b in iter(lambda:h.read(1024*1024),b''): d.update(b)
 return d.hexdigest()
def main() -> None:
 p=argparse.ArgumentParser(); p.add_argument('--checkpoint',type=Path,required=True); p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--device',default='cuda'); a=p.parse_args()
 root=Path(__file__).resolve().parents[2]; config_path=root/'configs'/'ember-restart-3b.json'; config=RestartDecoderConfig.from_contract(config_path)
 manifest_path=a.checkpoint/'checkpoint-manifest.json'; manifest=json.loads(manifest_path.read_text()); receipt={**manifest,'checkpoint_manifest_sha256':sha(manifest_path)}
 model=UnifiedDecoder(config,device=a.device,allow_production_allocation=True).eval(); load_checkpoint_artifacts(model,None,a.checkpoint,receipt)
 record=json.loads(a.input.read_text()); batch=decode_owned_batch(record,config,device=torch.device(a.device))
 with torch.inference_mode(): logits=model(batch['input_ids'],image_patches=batch['image_patches'],audio_frames=batch['audio_frames'],image_coordinates=batch['image_coordinates'],spans=batch['spans'],active_expert=batch['active_expert'])
 output={'schema_version':'ember-owned-prediction-v1','claim_status':'NON_CLAIM_BOOTSTRAP','checkpoint_manifest_sha256':receipt['checkpoint_manifest_sha256'],'input_sha256':sha(a.input),'active_expert':batch['active_expert'],'token_predictions':logits.argmax(dim=-1).tolist(),'logits_finite':bool(torch.isfinite(logits).all())}
 a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(output,sort_keys=True)+'\n'); print(json.dumps(output,sort_keys=True))
if __name__=='__main__': main()