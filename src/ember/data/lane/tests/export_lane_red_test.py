# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for export_lane.py: the exporter must turn machine roots and seat ids into lane_config expressions WITHOUT changing program meaning, and its AST-equivalence proof must fail on any other difference.
Uses a made-up root and seat; nothing here names a real machine."""
import os, sys, argparse, ast
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import export_lane as X
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


M = "Z" + ":/Q"                      # a made-up machine root, built at run time so no path literal sits in this file
args = argparse.Namespace(m_root=M, lane_dir="lane", seat=["zed=SEAT_X"], word=["Zed=role"], repo=["priv-a=HF_A", "priv-b=HF_B"])
c = X.Cfg(args)
SRC = ('"""Notes from Zed about %s/lane."""\n'
       'import os, sys\n'
       'ROOT = "%s/lane"\n'
       'sys.path.insert(0, ROOT + "/scripts")\n'
       'sys.path.insert(0, ROOT + "/vendor")\n'
       'LOGS = ROOT + "/logs"\n'
       'WHO = "zed"\n'
       'LEVEL = 3\n'
       'REPO_A = "acct/priv-a"\n'
       'REPO_B = "priv-b"    # the priv-b repo holds the raw sources\n'
       'URL = f"https://hub.example/{REPO_A}/tree/main"\n'
       'def f(x):\n'
       '    return os.path.join("%s/other", x)    # reads Zed state\n') % (M, M, M)
new, used = X.export_py(c, SRC, 0, [], "sample.py")
chk("GREEN no machine root and no seat id survives in the exported text", M not in new and "zed" not in new.lower().replace("seat_x", "") and "Zed" not in new)
chk("GREEN the exported code reads the lane_config names", "lane_config" in new and {"LANE_ROOT", "M_ROOT", "SEAT_X"} <= set(used) | {"SEAT_X"})
chk("GREEN the faithful export passes the AST-equivalence proof", X.verify(c, SRC, new))
chk("RED a changed constant (LEVEL 3 -> 4) fails the proof", not X.verify(c, SRC, new.replace("LEVEL = 3", "LEVEL = 4")))
chk("GREEN a root-like constant becomes an in-place lane_config import, not a path assignment", "import LANE_ROOT as ROOT" in new and "ROOT = LANE_ROOT" not in new)
chk("GREEN the redundant scripts-dir sys.path.insert is dropped, another insert stays", '"/scripts"' not in new and '"/vendor"' in new)
chk("RED a different lane_config name (LANE_ROOT -> M_ROOT) fails the proof", not X.verify(c, SRC, new.replace("import LANE_ROOT as ROOT", "import M_ROOT as ROOT", 1)))
chk("RED dropping a non-scripts sys.path.insert fails the proof", not X.verify(c, SRC, new.replace('sys.path.insert(0, ROOT + "/vendor")', "pass", 1)))
chk("RED an extra scripts-dir sys.path.insert in the export fails the proof", not X.verify(c, SRC, new + "\nsys.path.insert(0, ROOT + '/scripts')\n"))
chk("RED a different seat (SEAT_X -> a literal) fails the proof", "WHO = SEAT_X" in new and not X.verify(c, SRC, new.replace("WHO = SEAT_X", 'WHO = "other"', 1)))
chk("RED a renamed variable fails the proof", not X.verify(c, SRC, new.replace("LOGS", "LOGZ")))
chk("RED an extra statement fails the proof", not X.verify(c, SRC, new + "\nos.remove(ROOT)\n"))
chk("GREEN a documentary-only change (comment text) still passes", X.verify(c, SRC, new.replace("reads role state", "reads other state")))
chk("GREEN the exported file parses", bool(ast.parse(new)))
chk("GREEN no private repo name survives in the exported text (code strings and comments)", "priv-a" not in new and "priv-b" not in new)
chk("GREEN code strings read the lane_config repo names, comments get a placeholder", 'REPO_A = ("acct/" + HF_A)' in new and "REPO_B = HF_B" in new and "the <b> repo holds" in new and "from lane_config import HF_A, HF_B" in new)
chk("GREEN the repo export passes the proof", X.verify(c, SRC, new))
chk("RED swapping the two private repos (HF_A <-> HF_B) fails the proof", not X.verify(c, SRC, new.replace("acct/\" + HF_A", "acct/\" + HF_B", 1)))
chk("RED a repo name restored as a literal in code changes the value and fails the proof", not X.verify(c, SRC, new.replace("REPO_B = HF_B", 'REPO_B = "priv-a"', 1)))
chk("GREEN a comment-only mention of a repo name is reworded and still passes", "priv-b" not in new and X.verify(c, SRC.replace("the priv-b repo holds", "the other repo holds"), new))
S2 = 'ROOT = "x"\nAUD = ROOT + "/audit/secret-audit-priv-a.done"\n"""first docstring-like statement mentions priv-b."""\n"""second statement."""\n'
w2 = []; n2, _ = X.export_py(c, S2, 0, w2, "s2.py")
chk("GREEN a repo name embedded in a hyphenated file name is replaced and the proof passes", "priv-a" not in n2 and "HF_A" in n2 and X.verify(c, S2, n2))
chk("GREEN two adjacent string STATEMENTS are not reported as an implicit concatenation", not w2)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
