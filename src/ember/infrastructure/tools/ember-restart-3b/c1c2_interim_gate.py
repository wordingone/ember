# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C1/C2 INTERIM script gate.
C1: every span object in the candidate extension rows has an admitted source edge
    (present in --sources map sha256 -> {origin,licence,content_date_max <= 2022-10-31,...}) and is not one of the 4 excluded objects.
C2: >= 80% of candidate span tokens come from objects never in the trained stream [0, --trained-end).
Usage: python -I c1c2_interim_gate_v1.py --trained LEDGER --trained-end N --candidate ROWS --sources MAP.json --out RECEIPT.json
rc 0 PASS, rc 17 REFUSE. Never edits inputs."""
import argparse, hashlib, json, sys
EXCL = ('1983e86362bc0a3d', 'a6ac037d54ad0e95', '3bc93f29e60a2637', '0d544e19a34b182f')
ap = argparse.ArgumentParser()
for a in ('--trained', '--candidate', '--sources', '--out'): ap.add_argument(a, required=True)
ap.add_argument('--trained-end', type=int, required=True)
ap.add_argument('--min-new', type=float, default=0.80)
x = ap.parse_args()
sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
trained = set(); pos = 0
for line in open(x.trained):
    r = json.loads(line); b0 = r['spans'][0]['token_start']
    for s in r['spans']:
        if pos + s['token_start'] - b0 < x.trained_end: trained.add(s['sha256'])
    pos += r['n_tokens']
    if pos >= x.trained_end: break
if x.sources.endswith('.jsonl'):
    src = {}
    for l in open(x.sources):
        m = json.loads(l)
        if m.get('object_sha256') and m.get('origin') and m.get('licence'): src[m['object_sha256']] = m
else: src = json.load(open(x.sources))
# C1 date check: a source edge passes only with content_date_max <= the date wall.
WALL = '2022-10-31'
undated = sorted(k for k, m in src.items() if not str(m.get('content_date_max', ''))[:10] or str(m['content_date_max'])[:10] > WALL)
for k in undated: src.pop(k)
tot = new = 0; c1_bad = []; excl_hit = []; objs = set()
for line in open(x.candidate):
    r = json.loads(line)
    for s in r['spans']:
        n = s['token_end'] - s['token_start']; o = s['sha256']; objs.add(o); tot += n
        if o[:16] in EXCL: excl_hit.append(o)
        if o not in src: c1_bad.append(o)
        if o not in trained: new += n
frac = new / tot if tot else 0.0
c1 = not c1_bad and not excl_hit; c2 = tot > 0 and frac >= x.min_new
rec = {'schema': 'c1c2-interim-gate-v1', 'verdict': 'PASS' if c1 and c2 else 'REFUSE',
       'C1': {'pass': c1, 'objects': len(objs), 'unsourced': len(set(c1_bad)), 'unsourced_sample': sorted(set(c1_bad))[:10],
              'excluded_hits': sorted(set(excl_hit)), 'date_wall': WALL, 'undated_or_post_wall': undated[:10]},
       'C2': {'pass': c2, 'candidate_tokens': tot, 'never_trained_tokens': new, 'frac': round(frac, 6), 'min': x.min_new},
       'inputs': {'trained': x.trained, 'trained_sha256': sha(x.trained), 'trained_end': x.trained_end,
                  'trained_objects': len(trained), 'candidate': x.candidate, 'candidate_sha256': sha(x.candidate),
                  'sources': x.sources, 'sources_sha256': sha(x.sources)},
       'script_sha256': sha(__file__)}
json.dump(rec, open(x.out, 'w'), indent=1); print(json.dumps({k: rec[k] for k in ('verdict', 'C1', 'C2')}))
sys.exit(0 if rec['verdict'] == 'PASS' else 17)
