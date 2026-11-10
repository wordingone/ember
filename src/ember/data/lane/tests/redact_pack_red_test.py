# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test (lead 81693): a planted fake credential comes out REDACTED in a train-ready pack, the count is recorded in receipt.json, and no value appears in the log/receipt."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, subprocess, tempfile, io, glob
import zstandard
from lane_config import LANE_ROOT as ROOT; pass
import secret_scan as S
ok = True
def chk(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok &= bool(c)
PW = "fakepass123"; AK = "AKIA" + "ABCDEFGHIJKLMNOP"; KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKfakefakefake\n-----END RSA PRIVATE KEY-----"
doc = ("Setup notes. conn = 'mongodb+srv://user1:" + PW + "@cluster0.example.invalid/db'\naws " + AK + "\n" + KEY + "\nplain prose continues here. " * 5)
c = {}; out = S.redact(doc, c)
chk("redact(): mongodb URI, AWS key and private-key block replaced", PW not in out and AK not in out and "MIIBOgIB" not in out and out.count(S.PLACEHOLDER) >= 3)
chk("redact(): counts recorded per pattern", c.get("mongodb_uri") == 1 and c.get("aws_access_key") == 1 and c.get("private_key_block") == 1)
chk("redact(): clean text returned unchanged (same object)", S.redact("nothing secret here", {}) == "nothing secret here")
d = tempfile.mkdtemp(); inp = d + "/in.jsonl.zst"
with open(inp, "wb") as f:
    w = zstandard.ZstdCompressor().stream_writer(f)
    for i, t in enumerate([doc, "A perfectly ordinary document about gardens. " * 30]):
        w.write((json.dumps(dict(id=f"t-{i}", text=t)) + "\n").encode())
    w.close()
r = subprocess.run([sys.executable, ROOT + "/scripts/pack.py", d, "redtest", inp], capture_output=True, text=True)
chk("pack.py ran", r.returncode == 0)
rec = json.load(open(d + "/redtest/receipt.json"))
chk("receipt records redaction counts", rec["secret_redaction"]["spans_total"] == 3 and rec["secret_redaction"]["docs_with_redactions"] == 1)
txt = ""
for p in glob.glob(d + "/redtest/objects/*.zst"):
    with open(p, "rb") as f: txt += io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8").read()
chk("pack object holds the placeholder and no secret value", S.PLACEHOLDER in txt and PW not in txt and AK not in txt and "MIIBOgIB" not in txt)
logs = r.stdout + r.stderr + open(d + "/redtest/receipt.json").read()
chk("no secret value in pack log or receipt", PW not in logs and AK not in logs and "MIIBOgIB" not in logs)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
