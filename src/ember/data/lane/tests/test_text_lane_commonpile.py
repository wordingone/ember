# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Offline check of the common-pile wall-safe prep functions on datasets-server sample rows (no bulk download). Run: python tests/test_text_lane_commonpile.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import sys, json, urllib.request, importlib
sys.argv = ["text_lane.py", "caselaw"]; pass
T = importlib.import_module("text_lane")
def rows(n, k=20):
    d = json.load(urllib.request.urlopen(f"https://datasets-server.huggingface.co/first-rows?dataset=common-pile/{n}&config=default&split=train", timeout=60)); return [r["row"] for r in d["rows"]][:k]
ok = True
def chk(name, cond):
    global ok; print(("PASS " if cond else "FAIL ") + name); ok = ok and cond
st = lambda: dict(docs_in=0, bad_licence=0, quality=0, gate_dup=0, kept=0)
s = st(); out = [T.prep_caselaw(r, s) for r in rows("caselaw_access_project_filtered")]; chk("caselaw keeps PD opinions (%d kept, %s)" % (sum(1 for o in out if o), s), any(out))
s = st(); out = [T.prep_usgpo(r, s) for r in rows("usgpo_filtered")]; chk("usgpo sample rows: no date exclusion, every kept row records content_date_max == issued (%d kept)" % sum(1 for o in out if o), any(out) and all(o is None or o["content_date_max"] == o["issued"] for o in out))
s = st(); old = {"id": "lordswrans2016-06-15", "metadata": "{'license': 'Open Parliament Licence - x', 'year': '2016'}", "text": "word " * 200}
new = dict(old, id="lordswrans2023-01-10"); chk("hansard 2016 kept", T.prep_hansard(old, s) is not None); o23 = T.prep_hansard(new, s); chk("hansard 2023 KEPT (no wall), content_date_max 2023-01-10", o23 is not None and o23["content_date_max"] == "2023-01-10")
s = st(); chk("pre1929 kept by construction", T.prep_pre1929({"id": "x", "text": "word " * 200}, s) is not None)
s = st(); chk("NC licence refused", T.prep_usgpo({"id": "y", "date": "2020-01-01T00:00:00", "metadata": "{'license': 'CC-BY-NC-4.0'}", "text": "word " * 200}, s) is None and s["bad_licence"] == 1)
# ---- Tier-1 (offline synthetic rows shaped like the real ones read by range request 2026-11-09)
s = st(); se = {"id": "b1", "created": "2021-11-09T14:53:37", "metadata": {"detected_licenses": ["MIT"], "filename": "a.md"}, "text": "x" * 300}
chk("stackv2_edu MIT pre-wall kept", T.prep_stackv2_edu(se, s) is not None)
o = T.prep_stackv2_edu(dict(se, created="2023-01-02T00:00:00"), s); chk("RED stackv2_edu created 2023 KEPT (no wall), content_date_max 2023-01-02", o is not None and o["content_date_max"] == "2023-01-02")
chk("RED stackv2_edu GPL/unknown licence refused", T.prep_stackv2_edu(dict(se, metadata={"detected_licenses": ["MIT", "GPL-3.0"]}), s) is None and s["bad_licence"] == 1)
s = st(); gh = {"id": "9", "created": "2022-12-21T01:58:45+00:00", "metadata": {"license": "MIT", "license_type": "permissive", "url": "u"}, "text": "word " * 80}
o = T.prep_github_archive(gh, s); chk("RED github_archive created 2022-12-21 KEPT (no wall), content_date_max 2022-12-21", o is not None and o["content_date_max"] == "2022-12-21")
chk("github_archive 2022-10-31 kept", T.prep_github_archive(dict(gh, created="2022-10-31T23:59:59+00:00"), s) is not None)
chk("RED github_archive non-permissive refused", T.prep_github_archive(dict(gh, created="2020-01-01T00:00:00", metadata={"license": "GPL-3.0", "license_type": "copyleft"}), s) is None)
s = st(); ax = {"id": "0705.1329v2", "created": "2007-05-08T01:01:59", "metadata": {"license": "Creative Commons - Attribution Share-Alike - https://creativecommons.org/licenses/by-sa/4.0/", "url": "u"}, "text": "word " * 300}
o = T.prep_arxiv_papers(ax, s); chk("arxiv kept, id normalised (no version) = arxiv-0705.1329", o is not None and o["id"] == "arxiv-0705.1329")
chk("RED arxiv NC licence refused", T.prep_arxiv_papers(dict(ax, metadata={"license": "Creative Commons - Attribution - Non Commercial - https://creativecommons.org/licenses/by-nc/4.0/"}), s) is None)
o = T.prep_arxiv_papers(dict(ax, created="2023-03-01T00:00:00"), s); chk("RED arxiv created 2023 KEPT (no wall), content_date_max 2023-03-01", o is not None and o["content_date_max"] == "2023-03-01")
s = st(); us = {"id": "US-1-A", "created": "1924-05-27", "metadata": {"license": "Creative Commons - Attribution - https://creativecommons.org/licenses/by/4.0/", "publication_date": "1925-11-24"}, "text": "claim " * 200}
chk("uspto 1924 kept", T.prep_uspto(us, s) is not None)
o = T.prep_uspto(dict(us, metadata=dict(us["metadata"], publication_date="2023-02-02")), s); chk("RED uspto published 2023 KEPT (no wall), content_date_max = the later of created/publication 2023-02-02", o is not None and o["content_date_max"] == "2023-02-02")
# ---- no-wall metadata checks on the remaining prep fns (offline, synthetic rows)
s = st(); o = T.prep_usgpo({"id": "u1", "date": "2024-05-01T00:00:00", "metadata": "{'license': 'CC0'}", "text": "word " * 200}, s); chk("usgpo 2024 KEPT, content_date_max 2024-05-01", o is not None and o["content_date_max"] == "2024-05-01")
o = T.prep_usgpo({"id": "u2", "metadata": "{'license': 'CC0'}", "text": "word " * 200}, s); chk("usgpo undated KEPT, content_date_max None", o is not None and o["content_date_max"] is None)
o = T.prep_hansard({"id": "lordsnoid", "metadata": "{'license': 'OPL', 'year': '2024'}", "text": "word " * 200}, s); chk("hansard year-only 2024 KEPT, content_date_max 2024-12-31", o is not None and o["content_date_max"] == "2024-12-31")
o = T.prep_pes2o({"id": "p1", "created": "2023-04-05T00:00:00", "metadata": "{'oa_license': 'cc-by'}", "text": "word " * 200}, s); chk("pes2o 2023 KEPT, content_date_max 2023-04-05", o is not None and o["content_date_max"] == "2023-04-05")
o = T.prep_pubmed({"id": "q1", "created": "2023-04-05", "metadata": "{'license': 'cc-by'}", "text": "word " * 200}, s); chk("pubmed 2023 KEPT, content_date_max 2023-04-05", o is not None and o["content_date_max"] == "2023-04-05")
o = T.prep_caselaw({"id": "c1", "metadata": "{'license': 'public domain'}", "text": "word " * 200}, s); chk("caselaw content_date_max = snapshot end 2020-12-31", o is not None and o["content_date_max"] == "2020-12-31")
o = T.prep_pre1929({"id": "b1", "text": "word " * 200}, s); chk("pre1929 content_date_max 1928-12-31", o is not None and o["content_date_max"] == "1928-12-31")
o = T.prep_stackv2_edu(dict(se, created=""), s); chk("stackv2_edu undated KEPT, content_date_max None", o is not None and o["content_date_max"] is None)
chk("no post_wall stat is produced any more", "post_wall" not in s)
chk("module has no WALL filter constant left", not hasattr(T, "WALL") and T.SPLIT_DATE == "2022-10-31")
# the <lane>_post remainder split still splits on SPLIT_DATE (a split, not a wall)
post = T._post_prep(T.prep_stackv2_edu, lambda r: T.norm_date(r.get("created"))); s = st()
chk("post split: 2023 doc written with content_date_max 2023-01-02", (lambda o: o is not None and o["content_date_max"] == "2023-01-02")(post(dict(se, created="2023-01-02T00:00:00"), s)))
chk("post split: 2021 doc skipped (already in the existing pack)", post(se, s) is None and s["pre_wall_skip"] == 1)
import overlap_gate as G
chk("overlap id key: lane id arxiv-0705.1329 == arxiv pack namespace", G.ns_key("arxiv_papers-00000-00000", "arxiv-0705.1329") == "arxiv:0705.1329" == G.ns_key("arxiv-pdf-prewall", "arxiv-0705.1329v1"))
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
