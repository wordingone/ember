# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Draft ATTRIBUTION.md + LICENSES/<pack>.md for the public ember-corpus repo from logs/licence-audit-20261109.json (lead 82083 step 4). Writes only under publish/ember-corpus-attribution/ (local draft; upload is a separate step)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, os
A = json.load(open((LANE_ROOT + "/logs/licence-audit-20261109.json"))); O = (LANE_ROOT + "/publish/ember-corpus-attribution"); os.makedirs(O + "/LICENSES", exist_ok=True)
cls = {"PUBLIC_OK": "public domain / CC0", "PUBLIC_WITH_CONDITIONS": "open licence with attribution and/or share-alike conditions (see the pack file)"}
rows = []
for name, r in sorted(A.items()):
    lic = "\n".join(f"- {x}" for x in r.get("licences") or ["(none recorded)"]); org = "\n".join(f"- {x}" for x in r.get("origin") or ["(not recorded)"])
    open(f"{O}/LICENSES/{name}.md", "w", encoding="utf-8").write(
        f"# {name}\n\nRe-host class (internal licence audit 2026-11-09): **{r['rehost']}** - {cls.get(r['rehost'], '')}\n\n## Licences recorded in the source manifest\n{lic}\n\n## Origin\n{org}\n\n"
        f"Tokens (this pack): {r['tokens']:,}. Latest content date admitted: {r.get('content_date_max')}. Exact upstream revision pinned: {'yes' if r.get('version_hash') else 'see provenance addendum / revision sidecar'}.\n\n"
        "Attribution: credit the original authors/publishers named in the origin above; share-alike licences (CC BY-SA, GFDL) require derivatives to carry the same licence. This file is a good-faith notice from an internal audit, not legal advice.\n")
    rows.append(f"| {name} | {r['rehost']} | {'; '.join(r.get('licences') or [])[:140]} | {r['tokens']:,} |")
open(O + "/ATTRIBUTION.md", "w", encoding="utf-8").write(
    "# Attribution and licences for wordingone/ember-corpus\n\nEvery text/media pack in this corpus keeps its source licence. Per-pack notices are in `LICENSES/<pack>.md`; the table below summarises the internal licence audit of 2026-11-09 "
    f"({len(A)} packs: {sum(1 for r in A.values() if r['rehost']=='PUBLIC_OK')} public-domain/CC0, {sum(1 for r in A.values() if r['rehost']=='PUBLIC_WITH_CONDITIONS')} with attribution or share-alike conditions).\n\n"
    "| pack | re-host class | licence(s) | tokens |\n|---|---|---|---|\n" + "\n".join(rows) +
    "\n\n## Sources outside the packed-text audit (not covered by the table above)\n- `sources/librispeech-seed`: CC BY 4.0 (LibriSpeech / LibriVox readers) - attribution required.\n- `sources/stackexchange`: CC BY-SA - attribution to the post authors and share-alike required.\n"
    "- `sources/emotion-dataset`: third-party dataset, licence NOT yet verified - treat as unverified until a notice is added.\n- `sources/pd12m`, `sources/loc-pd-books`, `sources/arxiv-abstracts`: see their pack/licence files; PD12M is CDLA-Permissive/CC0-type, LoC books public domain, arXiv abstract metadata CC0.\n\n"
    "These notices were generated from the source manifests; they are not legal advice. Report errors to the repository owner.\n")
print(len(A), "packs ->", O)
