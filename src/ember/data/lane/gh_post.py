# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""gh_post.py CHAINS.jsonl OUTPREFIX : chains jsonl -> zst docs for scrub/dedup (utf-8). Prints chain count / token stats from the FILE (not the Counter)."""
import sys, json, statistics, zstandard
src, pre = sys.argv[1:3]
L = [json.loads(l) for l in open(src, encoding="utf-8")]
c = zstandard.ZstdCompressor(level=6)
with open(pre + ".jsonl.zst", "wb") as fo, c.stream_writer(fo) as w:
    for d in L:
        d.setdefault("origin", "human-source (GitHub issue/PR lifecycle, user text; bots dropped)"); d.setdefault("license", "per-repo permissive (licence-now caveat)")
        w.write((json.dumps(d, ensure_ascii=False) + "\n").encode())
t = [d["tokens"] for d in L]
print(json.dumps(dict(chains=len(L), tok_total=sum(t), tok_mean=round(statistics.mean(t)), tok_median=statistics.median(t), tok_max=max(t))))
