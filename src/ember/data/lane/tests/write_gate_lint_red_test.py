# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Lint red test (lead 82324 class fix, lead 82669): every lane script that does a BULK write must call reserve_plan.write_gate on the path before that write, and must REFUSE when it returns False.
Bulk writer = binary-write open ('wb'/'ab'/'xb'), a text-write open whose with-body writes inside a loop, zstandard stream_writer / copy_stream, array.tofile, shutil.copy*.
A gate counts only when ALL of these hold (a gate that is only 'a call named write_gate' refuses nothing):
  1. its result is used as `if not <gate>: <raise | sys.exit(...)>` (an `and` chain in the test is accepted). `assert` is NOT accepted (python -O strips it), nor is a bare call, nor a discarded result;
  2. it sits at an earlier line than the write, in the write's OWN function (module level for a module-level write). A module-level gate also covers writes inside functions only when the file has exactly ONE bulk write site;
  3. harm_wait never counts (it gives up after 30 min).
A file with an ungated bulk write fails unless it is in TINY_OK (output is a small receipt/ledger/json, or a one-shot tool) or GATE_DEBT (known bulk writer, owner and next step stated).
Residual the scan cannot see is printed as 'unscannable: N files' and bounded by a frozen ceiling (UNSCANNABLE_CEILING): hf_hub_download / snapshot_download, Path.write_text / write_bytes, np.save / torch.save,
a variable or '+' open mode, subprocess stdout/stderr redirects, and .sh / .ps1 lane files. The ceiling can only be lowered.
EXECUTED cases (run_executed_gate_cases) copy dedup.py, filter_ids.py, carve_heldout.py, gh_assemble.py, redact_r1.py and repack_r1.py beside a stub reserve_plan / lane_config and RUN them: a gate that
returns False must exit non-zero with the named refusal and leave no file; for the three early-gate scripts a gate that returns True must produce the output; for the three that load a tokenizer or touch the
network first, a gate that raises a sentinel must fire before any file appears.
Run from the repo root or anywhere: python src/ember/data/lane/tests/write_gate_lint_red_test.py   (no lane environment variables needed; nothing is written outside a temp dir; CI: ci-pr.yml)."""
import ast, json, os, shutil, subprocess, sys, tempfile

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
    "restore_supervise.py": "restore supervisor: writes only its own log lines (KB); the restore bytes are written by ckpt_restore.py, listed in GATE_DEBT",
    "lane_drift.py": "writes one README copy (KB) into the export dir for the drift compare; the exported scripts come from export_lane.py",
    "audit_deleters.py": "one-shot audit: writes audit-rows.jsonl and audit-table.md (one row per delete site, KB-MB)",
    "audit_hf_index.py": "one-shot audit: writes hf-index.jsonl (one row per Hub file, MB) via .part and os.replace",
}
# known bulk writers that are NOT yet gated; each needs a follow-up row. A file leaves this list when it is gated (the test then FAILs the stale entry).
GATE_DEBT = {
    "pack.py": "owner: data lane: gated per shard only (flush_shards); the object stream in open_part (full jsonl.zst copy of the source) and the docs-index copy_stream are not gated; add write_gate before open_part and before the docs-index copy",
    "text_lane.py": "owner: data lane: master has a step-start write_gate in run() (new pack/dedup/scrub steps wait at the floor, in-flight steps finish); the object download appends (loc, 'ab') and the prep write stay ungated (harm_wait gives up after 30 min); add write_gate before the download loop and before prepf",
    "ckpt_restore.py": "owner: data lane: NO floor/write_gate check; downloads checkpoint files with hf_hub_download and copies them with shutil.copyfile (multi-GB per object); the owner rules whether restore writes are deliberately floor-exempt, if not add write_gate before the download and the copy",
    "fetch_open_model.py": "owner: data lane: hf_hub_download of multi-GB weights; its own floor --min-free-gib 300 is below the 315 standing floor (reserve_plan.floor_gib()); the owner rules exemption, else gate each file on write_gate",
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
UNSCANNABLE_CEILING = 43      # frozen: files with write forms the scan cannot see (see docstring). Lower it when one is gated or moved to the scan; never raise it without a ruling.


def _mode_str(v):
    if isinstance(v, ast.Constant) and isinstance(v.value, str): return v.value
    if isinstance(v, ast.IfExp): return _mode_str(v.body) + _mode_str(v.orelse)      # open(p, "ab" if have else "wb")
    return ""


def _mode_node(call):
    m = call.args[1] if len(call.args) >= 2 else None
    for k in call.keywords:
        if k.arg == "mode": m = k.value
    return m


def _mode(call):
    m = _mode_node(call)
    return _mode_str(m) if m is not None else ""


def _static_mode(v):
    return (isinstance(v, ast.Constant) and isinstance(v.value, str)) or (isinstance(v, ast.IfExp) and _static_mode(v.body) and _static_mode(v.orelse))


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


def _is_gate_call(n):
    if not isinstance(n, ast.Call): return False
    f = n.func
    return (isinstance(f, ast.Attribute) and f.attr == "write_gate") or (isinstance(f, ast.Name) and f.id == "write_gate")


def _stops(stmt):
    """True when the statement raises or exits: `raise ...`, `sys.exit(...)`, `exit(...)`, `os._exit(...)`."""
    if isinstance(stmt, ast.Raise): return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        f = stmt.value.func
        if isinstance(f, ast.Attribute) and f.attr in ("exit", "_exit") and isinstance(f.value, ast.Name) and f.value.id in ("sys", "os"): return True
        if isinstance(f, ast.Name) and f.id in ("exit", "quit"): return True
    return False


def _enforced(g, parent):
    """The gate's result is the test of an `if not <gate>:` (optionally inside an `and` chain) whose body raises/exits."""
    u = parent.get(g)
    if not (isinstance(u, ast.UnaryOp) and isinstance(u.op, ast.Not)): return False
    n = u
    while isinstance(parent.get(n), ast.BoolOp) and isinstance(parent[n].op, ast.And): n = parent[n]
    i = parent.get(n)
    return isinstance(i, ast.If) and i.test is n and any(_stops(st) for st in i.body)


def scan_source(text):
    """-> (ungated bulk sites [(lineno, kind)], all bulk sites count, ENFORCED gate linenos)."""
    tree = ast.parse(text)
    parent = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p): parent[c] = p

    def scope(n):
        """innermost enclosing def / lambda / class, or None at module level."""
        while n in parent:
            n = parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)): return n
        return None
    sites = []; gates = []
    text_open_with = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for it in n.items:
                if isinstance(it.context_expr, ast.Call) and _is_open(it.context_expr): text_open_with[it.context_expr] = n
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        f = n.func
        if _is_gate_call(n):
            if _enforced(n, parent): gates.append(n)
            continue
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
        so = scope(s); gated = False
        for g in gates:
            if g.lineno >= s.lineno: continue
            sg = scope(g)
            if sg is so or (sg is None and len(sites) == 1): gated = True; break      # own function; or a module-level gate when this is the file's only write path
        if not gated: bad.append((s.lineno, kind))
    return sorted(bad), len(sites), sorted(g.lineno for g in gates)


_PROC = {"run", "Popen", "call", "check_call", "check_output"}
_HUB = {"hf_hub_download", "snapshot_download"}
_ARR = {"save", "savez", "savez_compressed"}


def unscannable_forms(text):
    """Write forms scan_source cannot see; -> sorted list of kinds (empty when none)."""
    tree = ast.parse(text); kinds = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        f = n.func; name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        if name in _HUB: kinds.add("hub-download")
        if isinstance(f, ast.Attribute):
            if f.attr in ("write_text", "write_bytes"): kinds.add("Path.write_*")
            if f.attr in _ARR and isinstance(f.value, ast.Name) and f.value.id in ("np", "numpy", "torch"): kinds.add("array-save")
            if f.attr in _PROC and isinstance(f.value, ast.Name) and f.value.id == "subprocess":
                for k in n.keywords:
                    if k.arg in ("stdout", "stderr") and not (isinstance(k.value, ast.Attribute) and k.value.attr in ("PIPE", "DEVNULL", "STDOUT")) and not (isinstance(k.value, ast.Constant) and k.value.value is None):
                        kinds.add("subprocess-redirect")
        if _is_open(n):
            mn = _mode_node(n)
            if mn is not None and (not _static_mode(mn) or "+" in _mode_str(mn)): kinds.add("variable-or-r+-mode")
    return sorted(kinds)


def scan_tree(root, tiny, debt):
    """-> dict(ungated=[...], stale=[...], missing=[...], unscannable=[(file, kinds)]); a file fails when it has ungated bulk writes and is in neither list."""
    res = dict(ungated=[], stale=[], missing=[], allowed=0, files=0, unscannable=[])
    names = sorted(f for f in os.listdir(root) if f.endswith(".py"))
    shells = sorted(f for f in os.listdir(root) if f.endswith((".sh", ".ps1")))
    lp = os.path.join(root, "loops")
    if os.path.isdir(lp):
        names += ["loops/" + f for f in sorted(os.listdir(lp)) if f.endswith(".py")]
        shells += ["loops/" + f for f in sorted(os.listdir(lp)) if f.endswith((".sh", ".ps1"))]
    seen = set(); unscan = set()
    for n in names:
        res["files"] += 1
        text = open(os.path.join(root, n), encoding="utf-8").read()
        bad, nsites, _g = scan_source(text)
        kinds = unscannable_forms(text)
        if kinds: res["unscannable"].append((n, kinds)); unscan.add(n)
        seen.add(n)
        if bad and n not in tiny and n not in debt: res["ungated"].append((n, bad))
        elif bad: res["allowed"] += 1
        elif n in debt and n not in unscan: res["stale"].append(n)       # gated now (and no hidden write form): drop it from GATE_DEBT
    for n in shells:
        res["files"] += 1; seen.add(n); res["unscannable"].append((n, ["shell-script"])); unscan.add(n)
    res["missing"] = sorted((set(tiny) | set(debt)) - seen)
    return res


# ---------------------------------------------------------------- executed gate cases
STUB_RESERVE = """import os
def write_gate(who="", need_bytes=0, log=print, **kw):
    open(os.environ["STUB_GATE_CALLS"], "a").write(who + "\\n")
    mode = os.environ.get("STUB_GATE_MODE", "false")
    if mode == "raise": raise RuntimeError("SENTINEL_GATE_REACHED")
    return mode == "true"
def harm_wait(*a, **k): return True
"""
STUB_ZSTD = """class _W:
    def __init__(s, fo): s.fo = fo
    def write(s, b): return s.fo.write(b)
    def __enter__(s): return s
    def __exit__(s, *a): s.fo.flush(); s.fo.close(); return False
    def close(s): s.fo.flush()
class ZstdCompressor:
    def __init__(s, level=3, **k): pass
    def stream_writer(s, fo): return _W(fo)
class ZstdDecompressor:
    def stream_reader(s, f): return f
"""
STUB_XXHASH = "import zlib\ndef xxh64_intdigest(s): return zlib.crc32(s.encode())\n"
STUB_TOKENIZER_MODULE = """class _E:
    ids = [1, 2, 3]
class Tokenizer:
    @staticmethod
    def from_file(p): return Tokenizer()
    def encode(s, t): return _E()
    def encode_batch(s, ts, **k): return [_E() for _ in ts]
"""
STUB_REQUESTS = "def get(*a, **k): raise RuntimeError('NETWORK_TOUCHED_BEFORE_GATE')\n"
STUB_HUB = """class _L:
    sha256 = "ab"
class _I:
    size = 100; lfs = _L()
class HfApi:
    def get_paths_info(s, *a, **k): return [_I()]
    def file_exists(s, *a, **k): return False
def get_token(): return "tok"
"""
STUB_SCANNER_MODULE = "PLACEHOLDER = 'x'\ndef redact(t, c): return t\ndef scan_path(p): return {'hits': 0}\n"
STUB_HFPUSH = "def upload_file(*a, **k): raise RuntimeError('UPLOAD_TOUCHED_BEFORE_GATE')\n"
DOCS = [dict(id="a", text="the quick brown fox jumps over the lazy dog again and again", tokens=12), dict(id="b", text="pack my box with five dozen liquor jugs please now today", tokens=11),
        dict(id="c", text="the quick brown fox jumps over the lazy dog again and again", tokens=12)]


def _files(*roots):
    out = set()
    for r in roots:
        for dp, dn, fn in os.walk(r):
            for f in fn: out.add(os.path.join(dp, f))
    return out


def run_script(name, args, mode, fixtures_fn=None):
    """Copy lane/<name> beside stubs in a temp dir, run it with the gate stub in `mode` (false | true | raise).
    -> dict(rc, out, err, new [paths created by the run], calls [gate 'who' strings])."""
    with tempfile.TemporaryDirectory() as d:
        bindir = os.path.join(d, "bin"); work = os.path.join(d, "work"); lane = os.path.join(d, "lane"); m = os.path.join(d, "m")
        for x in (bindir, work, lane, m, os.path.join(lane, "scripts")): os.makedirs(x)
        w = lambda p, t: open(p, "w", encoding="utf-8", newline="").write(t)
        shutil.copyfile(os.path.join(HERE, name), os.path.join(bindir, name))      # byte copy of the script under test (CodeQL py/clear-text-storage-sensitive-data flagged the read+write form)
        for mod, src in (("reserve_plan", STUB_RESERVE), ("zstandard", STUB_ZSTD), ("xxhash", STUB_XXHASH), ("tokenizers", STUB_TOKENIZER_MODULE), ("requests", STUB_REQUESTS),
                         ("huggingface_hub", STUB_HUB), ("secret_scan", STUB_SCANNER_MODULE)): w(os.path.join(bindir, mod + ".py"), src)
        w(os.path.join(bindir, "lane_config.py"), "HF_TRAIN_REPO = 't-private'\nLANE_ROOT = %r\nM_ROOT = %r\nSEAT_LEAD = 'x'\nSEAT_DATA = 'y'\n" % (lane.replace(os.sep, "/"), m.replace(os.sep, "/")))
        w(os.path.join(lane, "scripts", "hf_push.py"), STUB_HFPUSH)
        for p, t in (fixtures_fn(work.replace(os.sep, "/"), lane.replace(os.sep, "/")) if fixtures_fn else {}).items():
            os.makedirs(os.path.dirname(p), exist_ok=True); w(p, t)
        calls = os.path.join(d, "calls.txt"); open(calls, "w").close()
        before = _files(work, lane, m)
        env = dict(os.environ, STUB_GATE_CALLS=calls, STUB_GATE_MODE=mode, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-B", os.path.join(bindir, name)] + [a.replace("{W}", work.replace(os.sep, "/")) for a in args], capture_output=True, text=True, env=env, timeout=180, cwd=d)
        new = sorted(os.path.relpath(p, d).replace(os.sep, "/") for p in _files(work, lane, m) - before)
        return dict(rc=r.returncode, out=r.stdout, err=r.stderr, new=new, calls=[l for l in open(calls).read().splitlines() if l])


def _jsonl(rows): return "".join(json.dumps(r) + "\n" for r in rows)


def _tail(r): return r["err"][-400:].replace("\n", " | ")


def run_executed_gate_cases():
    try: import numpy  # noqa: F401  (dedup.py needs the real numpy; ci-pr installs it)
    except ImportError: check("executed: numpy is importable (dedup.py needs it)", False); return
    fx_in = lambda wd, ln: {wd + "/in.jsonl": _jsonl(DOCS)}
    # ---- early-gate scripts: refuse (False) and produce (True)
    cases = [("dedup.py", ["{W}/in.jsonl", "{W}/out.jsonl"], fx_in, ["out.jsonl"]),
             ("filter_ids.py", ["{W}/in.jsonl", "{W}/keep.jsonl", "{W}/excl.jsonl", "{W}/ids.json", "id"], lambda wd, ln: {wd + "/in.jsonl": _jsonl(DOCS), wd + "/ids.json": '["a"]'}, ["keep.jsonl", "excl.jsonl"]),
             ("carve_heldout.py", ["{W}/in.jsonl", "{W}/train.jsonl", "{W}/held.jsonl", "5"], fx_in, ["train.jsonl", "held.jsonl"])]
    for name, args, fx, outs in cases:
        r = run_script(name, args, "false", fx)
        check(f"executed {name}: gate False -> exit != 0, named refusal, gate reached, no output file (not even .part)",
              r["rc"] != 0 and "write_gate refused" in r["err"] and bool(r["calls"]) and not r["new"] and "NameError" not in r["err"])
        if not (r["rc"] != 0 and "write_gate refused" in r["err"]): print("    stderr tail:", _tail(r))
        r = run_script(name, args, "true", fx)
        have = all("work/" + o in r["new"] for o in outs)
        check(f"executed {name}: gate True -> exit 0, outputs present, no .part left, JSON stats on stdout",
              r["rc"] == 0 and have and not any(p.endswith(".part") for p in r["new"]) and bool(r["calls"]) and bool(r["out"].strip()) and r["out"].strip().splitlines()[-1].startswith("{"))
        if r["rc"] != 0: print("    stderr tail:", _tail(r))
    # ---- late-gate scripts (tokenizer / network first): the gate must fire before any file is created
    fx_gh = lambda wd, ln: {wd + "/cands.jsonl": ""}
    fx_redact = lambda wd, ln: {ln + "/audit/secret-audit-t-private.jsonl": _jsonl([dict(path="text/p/objects/a.jsonl.zst", status="scanned", hits=1)])}
    fx_repack = lambda wd, ln: {ln + "/packed/p1/receipt.json": json.dumps(dict(objects=[dict(name="o1.jsonl.zst", sha256="ab")], tokenizer_sha256="t", stream_format="s")), ln + "/redact-r1/MANIFEST.jsonl": ""}
    for name, args, fx in (("gh_assemble.py", ["{W}/cands.jsonl", "{W}/out.jsonl.zst"], fx_gh), ("redact_r1.py", [], fx_redact), ("repack_r1.py", ["p1"], fx_repack)):
        r = run_script(name, args, "raise", fx)
        check(f"executed {name}: a gate that raises a sentinel fires before any file appears (gate reached, no network or upload touched)",
              r["rc"] != 0 and "SENTINEL_GATE_REACHED" in r["err"] and bool(r["calls"]) and not r["new"] and "BEFORE_GATE" not in r["err"] and "NameError" not in r["err"])
        if "SENTINEL_GATE_REACHED" not in r["err"]: print("    stderr tail:", _tail(r))
        r = run_script(name, args, "false", fx)
        check(f"executed {name}: gate False -> exit != 0, named refusal, no file", r["rc"] != 0 and "write_gate refused" in r["err"] and bool(r["calls"]) and not r["new"])
        if "write_gate refused" not in r["err"]: print("    stderr tail:", _tail(r))


# ---------------------------------------------------------------- sandbox cases (the scan itself)
def run_sandbox_cases():
    """Executed cases against a temporary file set: ungated flagged, gated passes, allowlisted passes, wrong-scope/late/unenforced gate flagged."""
    GOOD = "    if not reserve_plan.write_gate('x', 1 << 20):\n        sys.exit('write_gate refused: floor')\n"
    with tempfile.TemporaryDirectory() as d:
        w = lambda n, s: open(os.path.join(d, n), "w", encoding="utf-8").write(s)
        w("ungated.py", "import zstandard\ndef main():\n    with open('o', 'wb') as fo, zstandard.ZstdCompressor().stream_writer(fo) as w:\n        w.write(b'x')\nmain()\n")
        w("gated.py", "import zstandard, reserve_plan, sys\ndef main():\n" + GOOD + "    with open('o', 'wb') as fo, zstandard.ZstdCompressor().stream_writer(fo) as w:\n        w.write(b'x')\nmain()\n")
        w("gated_raise.py", "def main():\n    if not reserve_plan.write_gate('x', 1, log=print):\n        raise RuntimeError('refused')\n    open('o', 'wb').write(b'x')\n")
        w("gated_and.py", "def main(gate):\n    if gate and not reserve_plan.write_gate('x', 1):\n        raise RuntimeError('refused')\n    open('o', 'wb').write(b'x')\n")
        w("allowed.py", "def main():\n    open('o', 'wb').write(b'tiny')\nmain()\n")
        w("late_gate.py", "def main():\n    open('o', 'wb').write(b'x')\n" + GOOD)
        w("other_func_gate.py", "def g():\n" + GOOD + "def main():\n    open('o', 'wb').write(b'x')\n")
        w("harm_wait_only.py", "def main():\n    reserve_plan.harm_wait('x')\n    open('o', 'wb').write(b'x')\n")
        w("assert_gate.py", "def main():\n    assert reserve_plan.write_gate('x', 1), 'floor'\n    open('o', 'wb').write(b'x')\n")
        w("bare_gate.py", "def main():\n    reserve_plan.write_gate('x', 1)\n    open('o', 'wb').write(b'x')\n")
        w("discarded_gate.py", "def main():\n    ok = reserve_plan.write_gate('x', 1)\n    open('o', 'wb').write(b'x')\n")
        w("if_not_noexit.py", "def main():\n    if not reserve_plan.write_gate('x', 1):\n        print('would refuse')\n    open('o', 'wb').write(b'x')\n")
        w("if_positive.py", "def main():\n    if reserve_plan.write_gate('x', 1):\n        sys.exit('wrong way round')\n    open('o', 'wb').write(b'x')\n")
        w("module_gate_one.py", "import shutil, sys\nif not reserve_plan.write_gate('x', 1):\n    sys.exit('refused')\ndef main():\n    shutil.copyfile('a', 'b')\n")
        w("module_gate_two.py", "import shutil, sys\nif not reserve_plan.write_gate('x', 1):\n    sys.exit('refused')\ndef main():\n    shutil.copyfile('a', 'b')\ndef more():\n    open('o', 'wb').write(b'x')\n")
        w("module_gate_module_write.py", "import shutil, sys\nif not reserve_plan.write_gate('x', 1):\n    sys.exit('refused')\nshutil.copyfile('a', 'b')\nopen('o', 'wb').write(b'x')\n")
        w("nested_write.py", "def main():\n" + GOOD + "    def helper():\n        open('o', 'wb').write(b'x')\n    helper()\n")
        w("text_loop.py", "import json\nrows = []\nwith open('o', 'w') as f:\n    for r in rows: f.write(json.dumps(r))\n")
        w("text_once.py", "import json\nwith open('o', 'w') as f: json.dump({}, f)\n")
        w("tofile.py", "import array\ndef flush(buf):\n    with open('t', 'wb') as f: buf.tofile(f)\n")
        # unscannable forms
        w("u_hub.py", "from huggingface_hub import hf_hub_download\nhf_hub_download('r', 'f')\n")
        w("u_snap.py", "import huggingface_hub\nhuggingface_hub.snapshot_download('r')\n")
        w("u_path.py", "from pathlib import Path\nPath('p').write_text('x')\n")
        w("u_npsave.py", "import numpy as np\nnp.save('p', 1)\n")
        w("u_torch.py", "import torch\ntorch.save({}, 'p')\n")
        w("u_varmode.py", "def f(p, m):\n    return open(p, m)\n")
        w("u_rplus.py", "open('p', 'r+b').write(b'x')\n")
        w("u_redirect.py", "import subprocess\nsubprocess.run(['x'], stdout=open('log', 'a'))\n")
        w("u_pipe_ok.py", "import subprocess\nsubprocess.run(['x'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)\n")
        w("u_shell.sh", "echo hi > out.txt\n")
        r = scan_tree(d, {"allowed.py": "tiny"}, {})
        flagged = {n for n, _ in r["ungated"]}
        check("sandbox: an ungated bulk writer is flagged", "ungated.py" in flagged)
        check("sandbox: a gated bulk writer passes (if not gate: sys.exit / raise / inside an and chain)", not ({"gated.py", "gated_raise.py", "gated_and.py"} & flagged))
        check("sandbox: an allowlisted writer passes", "allowed.py" not in flagged)
        check("sandbox: a gate AFTER the write does not count", "late_gate.py" in flagged)
        check("sandbox: a gate in another function does not count", "other_func_gate.py" in flagged)
        check("sandbox: harm_wait alone does not count as a gate", "harm_wait_only.py" in flagged)
        check("sandbox: an assert gate does not count (python -O strips it)", "assert_gate.py" in flagged)
        check("sandbox: a bare / discarded-result gate does not count", "bare_gate.py" in flagged and "discarded_gate.py" in flagged)
        check("sandbox: `if not gate:` that does not raise/exit, and a positive `if gate:`, do not count", "if_not_noexit.py" in flagged and "if_positive.py" in flagged)
        check("sandbox: a module-level gate counts for a function's write only when it is the file's ONLY write path", "module_gate_one.py" not in flagged and "module_gate_two.py" in flagged)
        check("sandbox: a module-level gate covers module-level writes", "module_gate_module_write.py" not in flagged)
        check("sandbox: a gate in the outer function does not cover a write in a nested function", "nested_write.py" in flagged)
        check("sandbox: a text write inside a loop is bulk, a single json.dump is not", "text_loop.py" in flagged and "text_once.py" not in flagged)
        check("sandbox: array.tofile is bulk", "tofile.py" in flagged)
        un = {n for n, _ in r["unscannable"]}
        check("sandbox: unscannable forms are counted (hf download, Path.write_*, np/torch.save, variable / r+ mode, subprocess redirect, .sh)",
              {"u_hub.py", "u_snap.py", "u_path.py", "u_npsave.py", "u_torch.py", "u_varmode.py", "u_rplus.py", "u_redirect.py", "u_shell.sh"} <= un)
        check("sandbox: PIPE / STDOUT subprocess use and plain files are not counted as unscannable", "u_pipe_ok.py" not in un and "gated.py" not in un and "allowed.py" not in un)
        r2 = scan_tree(d, {"ghost.py": "x"}, {"gated.py": "debt", "u_hub.py": "debt"})
        check("sandbox: an allowlist entry for a missing file and a stale GATE_DEBT entry are reported; a debt entry for an unscannable-only file is not stale",
              r2["missing"] == ["ghost.py"] and r2["stale"] == ["gated.py"])


run_sandbox_cases()
run_executed_gate_cases()
res = scan_tree(HERE, TINY_OK, GATE_DEBT)
for n, bad in res["ungated"]: print("  ungated bulk write:", n, bad[:4])
check(f"real tree: {res['files']} lane files scanned, no ungated bulk writer outside TINY_OK / GATE_DEBT", not res["ungated"])
check("real tree: no stale GATE_DEBT entry (a gated file must leave the list)", not res["stale"])
check("real tree: every allowlist entry names an existing file", not res["missing"])
check("allowlists: every entry has a reason", all(isinstance(v, str) and len(v) > 12 for v in list(TINY_OK.values()) + list(GATE_DEBT.values())))
# the named gaps from lead 82669 stay gated, with an enforced gate (if not ...: exit/raise), in the write's own scope
for n in ("dedup.py", "carve_heldout.py", "filter_ids.py", "redact_r1.py", "repack_r1.py", "gh_assemble.py"):
    bad, nsites, g = scan_source(open(os.path.join(HERE, n), encoding="utf-8").read())
    check(f"{n}: bulk write sites ({nsites}) all behind an enforced write_gate", nsites > 0 and not bad and g and n not in TINY_OK and n not in GATE_DEBT)
nun = len(res["unscannable"])
print(f"unscannable: {nun} files (ceiling {UNSCANNABLE_CEILING})")
for n, kinds in res["unscannable"]: print("   ", n, ",".join(kinds))
check(f"real tree: unscannable files {nun} <= frozen ceiling {UNSCANNABLE_CEILING} (lower the ceiling when one is gated)", nun <= UNSCANNABLE_CEILING)
print(f"GATE_DEBT (known ungated bulk writers, follow-up owed): {len(GATE_DEBT)}; TINY_OK: {len(TINY_OK)}")
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
