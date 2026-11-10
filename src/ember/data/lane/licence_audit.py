# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1581 custody: licence / public-rehost audit over every packed/<name>/source-manifest.jsonl (read-only). Per pack: unique licence strings, origin (+version hash present?), fetch_date range, raw_set_sha256 present, content_date_max,
public-rehost class: PUBLIC_OK (PD/CC0), PUBLIC_WITH_CONDITIONS (CC BY / BY-SA / GFDL: attribution, share-alike), PRIVATE_ONLY (anything else / unknown / NC / ND). Out: logs/licence-audit-20261109.json + data/state/licence-audit-20261109.md. Classification is a proposal for lead's written yes, never a visibility change."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT, SEAT_DATA
import os, sys, json, glob, re, collections
OUT = (LANE_ROOT + "/logs/licence-audit-20261109.json"); MD = (M_ROOT + "/avir/" + SEAT_DATA + "/state/licence-audit-20261109.md")
def cls(l):
    x = l.lower()
    if re.search(r"non[\s_-]?commercial|no[\s_-]?deriv|noderiv|-nc|-nd|proprietary|unknown|unspecified", x): return "PRIVATE_ONLY"
    if re.search(r"public[\s_-]?domain|\bpd\b|cc0|cc-0|publicdomain/zero|\bpd-", x) and not re.search(r"by", re.sub(r"public[\s_-]?domain", "", x)): return "PUBLIC_OK"
    if re.search(r"cc[\s-]?by|ccby|creative[\s]?commons|licenses/by|gfdl|open parliament|apache|mit\b|bsd", x): return "PUBLIC_WITH_CONDITIONS"
    return "PRIVATE_ONLY"
HASH = re.compile(r"@[0-9a-f]{7,40}|\b[0-9a-f]{40}\b|revision|sha1-verified|sha256")
rows = {}
for d in sorted(glob.glob((LANE_ROOT + "/packed/*/"))):
    d = d.replace(chr(92), "/").rstrip("/"); n = os.path.basename(d); p = d + "/source-manifest.jsonl"
    if not os.path.exists(p): continue
    lic = collections.Counter(); org = set(); fd = set(); raw = 0; tot = 0; cdm = set(); tok = 0
    for l in open(p, encoding="utf-8"):
        if not l.strip(): continue
        r = json.loads(l); tot += 1; tok += r.get("tokens", 0)
        for x in (r.get("licence") or []): lic[x] += 1
        org.add(r.get("origin") or ""); fd.add(r.get("fetch_date") or ""); raw += bool(r.get("raw_set_sha256")); cdm.add(r.get("content_date_max") or "")
    cl = sorted({cls(x) for x in lic}); worst = "PRIVATE_ONLY" if "PRIVATE_ONLY" in cl or not cl else ("PUBLIC_WITH_CONDITIONS" if "PUBLIC_WITH_CONDITIONS" in cl else "PUBLIC_OK")
    rows[n] = dict(tokens=tok, licences=sorted(lic)[:6], rehost=worst, origin=[o[:160] for o in sorted(org)[:2]], version_hash=any(HASH.search(o) for o in org), fetch_dates=sorted(fd)[:2], raw_set_sha=f"{raw}/{tot}", content_date_max=sorted(cdm)[-1] if cdm else "")
json.dump(rows, open(OUT, "w"), indent=1)
by = collections.defaultdict(lambda: [0, 0])
for r in rows.values(): by[r["rehost"]][0] += 1; by[r["rehost"]][1] += r["tokens"]
with open(MD, "w", encoding="utf-8") as f:
    f.write("# Licence / public-rehost audit 2026-11-09 (proposal; no visibility change)\n\n| pack | tokens | rehost class | licences | version hash | raw_set_sha |\n|---|---|---|---|---|---|\n")
    for n, r in rows.items(): f.write("| %s | %.2fB | %s | %s | %s | %s |\n" % (n, r["tokens"] / 1e9, r["rehost"], "; ".join(r["licences"])[:90], "yes" if r["version_hash"] else "NO", r["raw_set_sha"]))
print({k: (v[0], round(v[1] / 1e9, 2)) for k, v in by.items()}, "| no version hash:", [n for n, r in rows.items() if not r["version_hash"]])
