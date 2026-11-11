# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red (lead 83120): the REFUSED line carries the total plus the top 5 detector types and the path of the full table, never the whole table. Run: python tests/hit_summary_red_test.py"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pack_scan_status as P
ok = True
def chk(n, c):
    global ok; ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)
big = {"T%03d" % i: i + 1 for i in range(150)}
s = P.hit_summary(big, 39, "X:/rows/train-p.json")
chk("total 11325 and 150 types named", "11325 hits in 150 types" in s)
chk("top 5 by count, highest first", "top 5: T149 150, T148 149, T147 148, T146 147, T145 146" in s and "T144" not in s and "T000" not in s)
chk("further types counted, path present, short", "+145 more types" in s and "X:/rows/train-p.json" in s and len(s) < 260)
chk("small table: all types, no 'more'", "more types" not in P.hit_summary({"A": 2, "B": 5}, 1, "p") and "top 2: B 5, A 2" in P.hit_summary({"A": 2, "B": 5}, 1, "p"))
d = tempfile.mkdtemp(); json.dump({"signature": "S", "hits": big, "hit_files": ["f"] * 3, "clean": False}, open(d + "/train-p.json", "w"))
st, det = P.pack_scan_status("train-p", "L", d, lambda l: "S", lambda n: [])
chk("pack_scan_status refused_hits uses the capped text", st == "refused_hits" and "T149 150" in det and "T000" not in det and len(det) < 260)
line = P.status_line("train-p", st, det)
chk("mail line is one short line", "\n" not in line and len(line) < 320)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
