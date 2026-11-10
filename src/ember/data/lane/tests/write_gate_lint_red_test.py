# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Lint red test (lead 82324 class fix, lead 82669): every lane script that does a BULK write must call reserve_plan.write_gate on the path before that write.
Bulk writer = binary-write open ('wb'/'ab'/'xb'), a text-write open whose with-body writes inside a loop, zstandard stream_writer / copy_stream, array.tofile, shutil.copy*.
'On the path before it' = a write_gate call at an earlier line in the same function or in an enclosing scope of the write. harm_wait does NOT count (it gives up after 30 min).
A file with an ungated bulk write fails unless it is in TINY_OK (reason: output is a small receipt/ledger/json, or a one-shot tool) or GATE_DEBT (known bulk writer, owner and next step stated).
Run from the repo root or anywhere: python src/ember/data/lane/tests/write_gate_lint_red_test.py   (no lane environment variables needed; nothing is written outside a temp dir)."""
import ast, os, sys, tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # .../lane
ok = True


def check(label, cond):
    global ok
    ok = ok and bool(cond); print(("PASS " if cond else "FAIL ") + label)


# ---- allowlist: file -> one-line reason (output is tiny, or the tool is report-only / one-shot with its own gate) ----
TINY_OK = {
    "_cap_redtest.py": "red-test helper: writes a 4 KiB fixture file under its own temp queue dir",
    "ccby_manifest.py": "manifest builder: writes one small jpg per sampled image row (KB each, sample-capped), not a corpus copy",
    "coco_fetch.py": "fetches individual COCO images (KB each, a few hundred max) for the held-out image probe",
    "commons_pilot.py": "pilot: a few dozen Commons images (KB each), one-shot",
    "commons_pilot2.py": "pilot: a few dozen Commons images (KB each), one-shot",
    "mls_manifest.py": "manifest builder: sampled audio rows only (KB each, sample-capped)",
    "secret_scan.py": "self-test fixtures: tiny bytes written under a tempfile dir",
    "th_gate.py": "scratch expansion is gated by its own write_gate call in scan_files (see write_gate_red_test.py); the writes in this file's self-test are tiny fixtures",
    "ledger_add_model.py": "copies one model LICENSE + README (KB) into the evidence dir",
    "rescrub_r2.py": "copies a single .prov.jsonl (KB-MB provenance table), not a shard",
    "hf_inventory.py": "copies a small json checkpoint of the inventory scan (KB-MB)",
    "bulk_lane.py": "copy2 of one local file kept beside its .dat: the bulk bytes come from the already-gated download path",
    "_touched_paths.py": "one-shot audit: writes a path list text file (<= tens of MB)",
    "a1_prov.py": "provenance row writer: one jsonl row per source, KB-MB",
    "arxiv_manifest.py": "manifest rows (one per arXiv id, tens of MB at most)",
    "ccby_pack.py": "manifest.jsonl rows for the ccby pack (the image bytes themselves go through ccby_manifest's sampled writer)",
    "census_hash.py": "census hash rows (one line per file), tens of MB at most",
    "coco_prep.py": "coco-keep.jsonl: one row per kept image (KB-MB)",
    "commons_finish.py": "one-shot pilot manifest (KB-MB)",
    "delete_approved_dirs.py": "writes a per-directory deletion manifest (KB) before a delete; the delete path has its own manifest-first gate",
    "drop_manifest.py": "drop-candidate manifest rows (KB-MB)",
    "drop_scan.py": "drop-candidate scan rows (KB-MB)",
    "dup_ckpt_delete.py": "receipt appends and a RELOCATED json (KB); deletes data, writes none",
    "gh_catalog.py": "candidate catalogue/residual jsonl rows (MB; one row per candidate PR) and a resume append",
    "gh_discover.py": "discovery rows (one per candidate repo, MB)",
    "heldout_custody.py": "a one-page markdown custody note",
    "imgtext_manifest.py": "image-text manifest rows (one per pair, MB)",
    "licence_audit.py": "licence audit markdown report (KB)",
    "nara_manifest.py": "manifest rows for one archive (MB)",
    "pack_prov_fix.py": "rewrites one pack's .prov.jsonl (KB-MB)",
    "probe_gen.py": "writes the small probe-set text files (KB each, count-capped)",
    "prov_const.py": "writes one provenance constants file (KB)",
    "raw_roll.py": "appends rows to a rolling receipt (KB)",
    "reserve_manifest.py": "reserve manifest tsv (one row per file, MB)",
    "source_manifest.py": "source-manifest.jsonl for one pack (KB-MB)",
    "sources_ledger.py": "sources ledger tmp+replace write (KB-MB)",
    "loops/run_loops.py": "opens its own lock file (a few bytes) and appends log lines",
    "ckpt_restore.py": "report-only per lead (restore tool has its own floor/lease gates); not edited here",
    "restore_supervise.py": "report-only per lead (restore supervisor; writes only its own logs); not edited here",
}
# known bulk writers that are NOT yet gated; each needs a follow-up row. A file leaves this list when it is gated (the test then FAILs the stale entry).
GATE_DEBT = {
    "pack.py": "owner: data lane: gated per shard only (flush_shards); the object stream in open_part (full jsonl.zst copy of the source) and the docs-index copy_stream are not gated; add write_gate before open_part and before the docs-index copy",
    "text_lane.py": "owner: data lane: object download appends (loc, 'ab') and the prep stream are ungated (text_lane waits in harm_wait, which gives up after 30 min); add write_gate before the download loop and before prepf",
    "pack_media.py": "owner: data lane: writes the media shards (f.write(cur) per shard, MB-GB each); add write_gate in flush()",
    "a_relocate.py": "owner: data lane: relocation copy; has its own source-rehash + floor logic (a_relocate_red_test.py), add write_gate on the dest write",
    "gh_post.py": "owner: data lane: GitHub post-pass stream output (<=GBs), add write_gate before the stream",
    "heldout_pdf_overlap.py": "owner: data lane: filtered copy of a pdf pack, add write_gate before OUT",
    "net_cap.py": "owner: data lane: downloader .part appends; net_cap has its own cap, add write_gate before the open",
    "pdf_extract.py": "owner: data lane: stream_writer over the pdf extract output, add write_gate before OUT",
    "pg_prep.py": "owner: data lane: Project Gutenberg prep stream, add write_gate before OUT",
    "redact_r2_hit.py": "owner: data lane: single-object redaction copy (same shape as redact_pack_hits.py, which is gated), add write_gate",
    "remedy_hheldout2.py": "owner: data lane: ranged re-download append, add write_gate before the open",
    "remedy_move.py": "owner: data lane: ranged re-download append, add write_gate before the open",
    "scrub.py": "owner: data lane: scrub stream output, add write_gate before OUT",
    "se_prep.py": "owner: data lane: StackExchange prep stream, add write_gate before OUT",
    "wiki_pilot.py": "owner: data lane: wiki pilot stream, add write_gate before OUT",
    "wikisource_prep.py": "owner: data lane: wikisource prep stream, add write_gate before OUT",
}

_COPY = {"copy", "copy2", "copyfile", "copyfileobj", "copytree"}


def _mode_str(v):
    if isinstance(v, ast.Constant) and isinstance(v.value, str): return v.value
    if isinstance(v, ast.IfExp): return _mode_str(v.body) + _mode_str(v.orelse)      # open(p, "ab" if have else "wb")
    return ""


def _mode(call):
    m = ""
    if len(call.args) >= 2: m = _mode_str(call.args[1])
    for k in call.keywords:
        if k.arg == "mode": m = _mode_str(k.value)
    return m


def _is_open(call):
    f = call.func
    return (isinstance(f, ast.Name) and f.id == "open") or (isinstance(f, ast.Attribute) and f.attr == "open")


def _loop_writes(body):
    for n in body:
        for x in ast.walk(n):
            if isinstance(x, (ast.For, ast.While)):
                for y in ast.walk(x):
                    if isinstance(y, ast.Call) and isinstance(y.func, ast.Attribute) and y.func.attr in ("write", "writelines", "dump"): return True
    return False


def scan_source(text):
    """-> (ungated bulk sites [(lineno, kind)], all bulk sites count, gate linenos)."""
    tree = ast.parse(text)
    parent = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p): parent[c] = p

    def scopes(n):
        s = []
        while n in parent:
            n = parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)): s.append(n)
        return s
    sites = []; gates = []
    text_open_with = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for it in n.items:
                if isinstance(it.context_expr, ast.Call) and _is_open(it.context_expr): text_open_with[it.context_expr] = n
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        f = n.func
        if (isinstance(f, ast.Attribute) and f.attr == "write_gate") or (isinstance(f, ast.Name) and f.id == "write_gate"):
            gates.append(n); continue
        if _is_open(n):
            m = _mode(n)
            if any(c in m for c in "wax"):
                if "b" in m: sites.append((n, "open-binary-write"))
                elif n in text_open_with and _loop_writes(text_open_with[n].body): sites.append((n, "open-text-write-in-loop"))
        elif isinstance(f, ast.Attribute):
            if f.attr in ("stream_writer", "tofile", "copy_stream"): sites.append((n, f.attr))
            elif f.attr in _COPY and isinstance(f.value, ast.Name) and f.value.id == "shutil": sites.append((n, "shutil." + f.attr))
    bad = []
    for s, kind in sites:
        ss = scopes(s)
        gated = any(g.lineno < s.lineno and (set(map(id, scopes(g))) <= set(map(id, ss))) for g in gates)
        if not gated: bad.append((s.lineno, kind))
    return sorted(bad), len(sites), sorted(g.lineno for g in gates)


def scan_tree(root, tiny, debt):
    """-> dict(ungated=[...], stale=[...], missing=[...], flagged_allowed=n); a file fails when it has ungated bulk writes and is in neither list."""
    res = dict(ungated=[], stale=[], missing=[], allowed=0, files=0)
    names = sorted(f for f in os.listdir(root) if f.endswith(".py"))
    lp = os.path.join(root, "loops")
    if os.path.isdir(lp): names += ["loops/" + f for f in sorted(os.listdir(lp)) if f.endswith(".py")]
    seen = set()
    for n in names:
        res["files"] += 1
        bad, nsites, _g = scan_source(open(os.path.join(root, n), encoding="utf-8").read())
        seen.add(n)
        if bad and n not in tiny and n not in debt: res["ungated"].append((n, bad))
        elif bad: res["allowed"] += 1
        elif n in debt: res["stale"].append(n)       # gated now: drop it from GATE_DEBT
    res["missing"] = sorted((set(tiny) | set(debt)) - seen)
    return res


def run_sandbox_cases():
    """Executed cases against a temporary file set: ungated flagged, gated passes, allowlisted passes, wrong-scope/late gate flagged."""
    with tempfile.TemporaryDirectory() as d:
        w = lambda n, s: open(os.path.join(d, n), "w", encoding="utf-8").write(s)
        w("ungated.py", "import zstandard\ndef main():\n    with open('o', 'wb') as fo, zstandard.ZstdCompressor().stream_writer(fo) as w:\n        w.write(b'x')\nmain()\n")
        w("gated.py", "import zstandard, reserve_plan\ndef main():\n    assert reserve_plan.write_gate('x', 1 << 20), 'floor'\n    with open('o', 'wb') as fo, zstandard.ZstdCompressor().stream_writer(fo) as w:\n        w.write(b'x')\nmain()\n")
        w("allowed.py", "def main():\n    open('o', 'wb').write(b'tiny')\nmain()\n")
        w("late_gate.py", "def main():\n    open('o', 'wb').write(b'x')\n    reserve_plan.write_gate('x', 1)\nmain()\n")
        w("other_func_gate.py", "def g():\n    reserve_plan.write_gate('x', 1)\ndef main():\n    open('o', 'wb').write(b'x')\n")
        w("harm_wait_only.py", "def main():\n    reserve_plan.harm_wait('x')\n    open('o', 'wb').write(b'x')\n")
        w("module_gate.py", "import shutil\nreserve_plan.write_gate('x', 1)\ndef main():\n    shutil.copyfile('a', 'b')\n")
        w("text_loop.py", "import json\nrows = []\nwith open('o', 'w') as f:\n    for r in rows: f.write(json.dumps(r))\n")
        w("text_once.py", "import json\nwith open('o', 'w') as f: json.dump({}, f)\n")
        w("tofile.py", "import array\ndef flush(buf):\n    with open('t', 'wb') as f: buf.tofile(f)\n")
        r = scan_tree(d, {"allowed.py": "tiny"}, {})
        flagged = {n for n, _ in r["ungated"]}
        check("sandbox: an ungated bulk writer is flagged", "ungated.py" in flagged)
        check("sandbox: a gated bulk writer passes", "gated.py" not in flagged)
        check("sandbox: an allowlisted writer passes", "allowed.py" not in flagged)
        check("sandbox: a gate AFTER the write does not count", "late_gate.py" in flagged)
        check("sandbox: a gate in another function does not count", "other_func_gate.py" in flagged)
        check("sandbox: harm_wait alone does not count as a gate", "harm_wait_only.py" in flagged)
        check("sandbox: a module-level gate before a function's write counts", "module_gate.py" not in flagged)
        check("sandbox: a text write inside a loop is bulk, a single json.dump is not", "text_loop.py" in flagged and "text_once.py" not in flagged)
        check("sandbox: array.tofile is bulk", "tofile.py" in flagged)
        r2 = scan_tree(d, {"ghost.py": "x"}, {"gated.py": "debt"})
        check("sandbox: an allowlist entry for a missing file and a stale GATE_DEBT entry are reported", r2["missing"] == ["ghost.py"] and r2["stale"] == ["gated.py"])


run_sandbox_cases()
res = scan_tree(HERE, TINY_OK, GATE_DEBT)
for n, bad in res["ungated"]: print("  ungated bulk write:", n, bad[:4])
check(f"real tree: {res['files']} lane files scanned, no ungated bulk writer outside TINY_OK / GATE_DEBT", not res["ungated"])
check("real tree: no stale GATE_DEBT entry (a gated file must leave the list)", not res["stale"])
check("real tree: every allowlist entry names an existing file", not res["missing"])
check("allowlists: every entry has a reason", all(isinstance(v, str) and len(v) > 12 for v in list(TINY_OK.values()) + list(GATE_DEBT.values())))
# the named gaps from lead 82669 stay gated
for n in ("dedup.py", "carve_heldout.py", "filter_ids.py", "redact_r1.py", "repack_r1.py", "gh_assemble.py"):
    bad, nsites, g = scan_source(open(os.path.join(HERE, n), encoding="utf-8").read())
    check(f"{n}: bulk write sites ({nsites}) all behind write_gate", nsites > 0 and not bad and g and n not in TINY_OK and n not in GATE_DEBT)
print(f"GATE_DEBT (known ungated bulk writers, follow-up owed): {len(GATE_DEBT)}; TINY_OK: {len(TINY_OK)}")
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
