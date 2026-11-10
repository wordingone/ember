# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for dedupe_repack (2026-11-10, #2449): documents whose ns_key/text hit ANY other pack are dropped, the pack's own index rows are not a reason to drop, run-internal repeats are dropped,
originals are never modified by filter_final. Temp index, no real data. Run: python scripts/tests/dedupe_repack_red_test.py"""
import os, sys, io, json, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import zstandard, overlap_gate as G, dedupe_repack as D
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


d = tempfile.mkdtemp(); G.DB = os.path.join(d, "docs.sqlite")
c = G._db()
c.execute("insert into docs values(?,?,?,?)", ("arxiv:1111.0001", G.norm_hash("prewall text one"), "arxiv-pdf-prewall", 10))      # external pack, same id as a lane doc
c.execute("insert into docs values(?,?,?,?)", ("arxiv:2222.0002", G.norm_hash("the pack's own text two"), "arxiv_papers-0", 10))   # the pack itself (old index rows)
c.execute("insert into docs values(?,?,?,?)", ("other:9", G.norm_hash("shared text three"), "pes2o-x", 10)); c.commit(); c.close()
docs = [dict(id="arxiv-1111.0001v2", text="totally different words alpha"),     # id overlap with the external pack -> drop
        dict(id="arxiv-2222.0002", text="the pack's own text two"),               # own pack rows only -> keep
        dict(id="arxiv-3333.0003", text="shared   TEXT three"),                   # text-hash overlap with another pack -> drop
        dict(id="arxiv-4444.0004", text="fresh doc four"),                        # clean -> keep
        dict(id="arxiv-4444.0004v3", text="fresh doc four again")]                # same key as the previous kept doc -> run-dup drop
src = os.path.join(d, "final-0.jsonl.zst")
with open(src, "wb") as fo, zstandard.ZstdCompressor().stream_writer(fo) as w:
    for r in docs: w.write((json.dumps(r) + "\n").encode())
sha0 = open(src, "rb").read()
dst = os.path.join(d, "out.jsonl.zst"); seen = set(); log = io.StringIO()
n_in, n_keep = D.filter_final(src, dst, "arxiv_papers", {"arxiv_papers-0"}, seen, gate=False, drop_log=log)
out = [json.loads(l) for l in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(dst, "rb")), encoding="utf-8")]
drops = {json.loads(l)["id"]: json.loads(l)["why"] for l in log.getvalue().splitlines()}
chk("5 in, 2 kept", (n_in, n_keep) == (5, 2) and [r["id"] for r in out] == ["arxiv-2222.0002", "arxiv-4444.0004"])
chk("RED id overlap with an external pack is dropped (raw id had a version suffix)", drops.get("arxiv-1111.0001v2") == "id")
chk("RED text-hash overlap with another pack is dropped", drops.get("arxiv-3333.0003") == "text")
chk("GREEN a doc matching only the pack's own old index rows is kept", "arxiv-2222.0002" in [r["id"] for r in out])
chk("RED a repeat of an already kept key in the same run is dropped", drops.get("arxiv-4444.0004v3") == "run-dup")
chk("GREEN the original final is untouched", open(src, "rb").read() == sha0)
seen2 = set(); k2, dr2 = D.keep_batch(docs, "arxiv_papers", set(), seen2)
chk("RED with no self source the pack's own rows count as overlap too (extra finals)", [r["id"] for r in k2] == ["arxiv-4444.0004"] and any(x[0] == "arxiv-2222.0002" for x in dr2))
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
