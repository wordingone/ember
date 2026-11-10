# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test (2026-11-10): the text lanes' doc-level overlap gate must look up ns_key ids, the form the union index stores.
arxiv_papers escaped the zero-overlap gate because flush() queried raw 'arxiv-0807.3315v2'-style ids while the index holds 'arxiv:0807.3315'. Run: python scripts/tests/text_lane_nskey_red_test.py"""
import os, sys, re, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import overlap_gate as G
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


d = tempfile.mkdtemp(); G.DB = os.path.join(d, "docs.sqlite")
c = G._db(); c.execute("insert into docs values(?,?,?,?)", ("arxiv:0807.3315", G.norm_hash("alpha beta gamma"), "arxiv-pdf-prewall-00001", 10)); c.commit(); c.close()
raw = "arxiv-0807.3315"
chk("ns_key of an arxiv lane doc id is the indexed form", G.ns_key("arxiv_papers", raw) == "arxiv:0807.3315")
chk("RED the raw id misses the index (what the old gate did)", not G.check_docs([(raw, "different text entirely one")], "arxiv_papers"))
chk("GREEN the ns_key id hits the index", [k for k, _, _ in G.check_docs([(G.ns_key("arxiv_papers", raw), "different text entirely two")], "arxiv_papers")] == ["arxiv:0807.3315"])
chk("GREEN a non-arxiv namespaced id is unchanged by ns_key (pes2o-1)", G.ns_key("pes2o", "pes2o-1") == "pes2o-1")
src = open(os.path.join(HERE, "text_lane.py"), encoding="utf-8").read()
m = re.search(r"def flush\(.*?\n(?=    def |\n    with |\Z)", src, re.S)
chk("GREEN text_lane flush() queries G.ns_key ids and compares ns_key ids", 'G.check_docs([(G.ns_key(LANE, r["id"]), r["text"])' in src and 'if G.ns_key(LANE, r["id"]) in dups' in src)
chk("RED no raw-id query to check_docs remains in text_lane", 'check_docs([(r["id"]' not in src)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
