# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""prov_const.py OUT.jsonl FETCH_TS LICENSE DOCS1=RAW1 [DOCS2=RAW2 ...] : per-doc provenance rows (doc_id, raw_sha256, fetched_ts, license_url) for sources whose raw file is a dump/shard."""
import sys, io, json, hashlib, zstandard, os
OUT, FT, LIC = sys.argv[1:4]
def shaf(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()
n = 0
with open(OUT, "w") as fo:
    for pair in sys.argv[4:]:
        dp, rp = pair.split("=", 1); rs = shaf(rp)
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(dp, "rb")), encoding="utf-8"):
            fo.write(json.dumps(dict(doc_id=json.loads(line)["id"], raw_sha256=rs, raw_file=os.path.basename(rp), fetched_ts=FT, license_url=LIC)) + "\n"); n += 1
print(n)
