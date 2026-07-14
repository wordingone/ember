#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,json,os,tempfile
from pathlib import Path
from tokenizers import Tokenizer
def main():
 p=argparse.ArgumentParser();p.add_argument('--tokenizer',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 try:Tokenizer.from_file(str(a.tokenizer))
 except Exception as e:p.error(f'invalid tokenizer: {e}')
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.output.parent,delete=False)as h:json.dump({'goal_id':'EMBER-02','workstream_id':'EMBER-02C','next_executed_outcome':'EMBER-02 first sufficiently pretrained clean-genesis 3B Ember','result':'PREFLIGHT_ONLY','tokenizer_sha256':__import__('hashlib').sha256(a.tokenizer.read_bytes()).hexdigest()},h);h.write('\n');n=h.name
 os.replace(n,a.output)
if __name__=='__main__':main()
