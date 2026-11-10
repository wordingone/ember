# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic export of the lane tooling into the repository layout (issue #1581, #2451).

The live lane scripts carry machine roots and seat names. The repository forbids both (repo-guard: no absolute local paths, no operator/seat names), so the repo copy is
GENERATED from the live copy, never hand-edited:
  - a machine root (e.g. the drive-rooted parent of the lane) in a code string  -> an expression over lane_config.M_ROOT / LANE_ROOT (read from the environment at run time);
  - a seat id used as a mailbox recipient or as a state-directory name in a code string -> lane_config.SEAT_LEAD / SEAT_TRAIN / SEAT_DATA;
  - roots, seat names and mail references in comments, docstrings and message text -> neutral role words (--word OLD=NEW);
  - .sh / .ps1: environment variables instead of the roots;
  - every exported file gets the repo goal header.
Nothing here names a person, a seat or a machine: all of those values arrive on the command line.

  python export_lane.py --src DIR --dst DIR --m-root ROOT --lane-dir NAME --seat lead=SEAT_LEAD --seat training=SEAT_TRAIN --seat data=SEAT_DATA --word lead=lead ... [--exclude REL] [--receipt FILE]

Equivalence proof (verify()): for every .py file the rewritten AST is folded back with the real values (names -> constants, '+' of constants -> one constant, f-string parts merged)
and compared with the original AST after normalising ONLY the documentary text (roots, role words). Any other difference fails the export (exit 1). The receipt lists per-file sha256 of source and output.
"""
import argparse, ast, hashlib, io, json, os, re, sys, tokenize

HEADER = ("# goal_id: EMBER-02\n# workstream_id: EMBER-02A\n"
          "# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember\n")
SEP = r"(?:/|\\\\|\\)+"


MSGS = []      # code-string locations whose text changed by role words only
PATCH_CENSUS_SKIP = "SKIP_PREFIXES = tuple(x for x in __import__(\"os\").environ.get(\"EMBER_CENSUS_SKIP_PREFIXES\", \"\").lower().split(\";\") if x)"      # skip list comes from the environment


class Cfg:
    def __init__(self, a):
        parts = [p for p in re.split(r"[\\/]+", a.m_root) if p]
        self.m_root = a.m_root.replace("\\", "/").rstrip("/")
        self.lane_dir = a.lane_dir
        m_pat = re.escape(parts[0]) + "".join(SEP + re.escape(p) for p in parts[1:])
        self.M_RE = re.compile(m_pat + r"(?=[/\\]|$|[^A-Za-z0-9_.\-])")
        self.LANE_RE = re.compile(m_pat + SEP + re.escape(a.lane_dir) + r"(?![A-Za-z0-9_\-])")
        self.seats = [tuple(s.split("=", 1)) for s in a.seat]          # (source id, config name)
        self.words = [tuple(w.split("=", 1)) for w in a.word]
        self.word_res = [(re.compile(r"(?<![A-Za-z])" + re.escape(o) + r"(?![A-Za-z])"), n) for o, n in self.words]
        self.role = {cn: dict(self.words).get(sid.capitalize()) or dict(self.words).get(sid, sid) for sid, cn in self.seats}
        self.repos = [tuple(s.split("=", 1)) for s in getattr(a, "repo", [])]         # (private repo name, config name): names of private HF repos never sit in the public tree
        self.repo_res = [(re.compile(r"(?<![A-Za-z0-9_])" + re.escape(nm) + r"(?![A-Za-z0-9_])"), cn, "<" + cn.lower().replace("hf_", "").replace("_", "-") + ">") for nm, cn in self.repos]
        self.vals = {"LANE_ROOT": self.m_root + "/" + self.lane_dir, "M_ROOT": self.m_root}
        for sid, cn in self.seats: self.vals[cn] = sid
        for nm, cn in self.repos: self.vals[cn] = nm


def words(c, s):
    for rx, n in c.word_res: s = rx.sub(n, s)
    return s


def doc_text(c, s):
    """documentary text (comment, docstring): roots and seat dirs become placeholders, then role words"""
    s = c.LANE_RE.sub("<lane-root>", s); s = c.M_RE.sub("<m-root>", s)
    for sid, cn in c.seats: s = re.sub(r"(?<=[/\\])" + re.escape(sid) + r"(?=[/\\]|$)", "<" + c.role[cn] + ">", s)
    for rx, cn, ph in c.repo_res: s = rx.sub(ph, s)
    return words(c, s)


def depth_inside_braces(body, pos):
    d = 0; i = 0
    while i < pos:
        if body.startswith("{{", i) or body.startswith("}}", i): i += 2; continue
        if body[i] == "{": d += 1
        elif body[i] == "}": d = max(0, d - 1)
        i += 1
    return d


def code_string(c, tok, warn, where):
    """-> (new token text, set of lane_config names used)"""
    m = re.match(r'^([rRbBuUfF]*)("""|\'\'\'|"|\')', tok); prefix, q = m.group(1), m.group(2)
    body = tok[len(prefix) + len(q): len(tok) - len(q)]; low = prefix.lower()
    if "b" in low:
        if c.M_RE.search(body): warn.append(f"{where}: bytes literal carries a machine root")
        return prefix + q + words(c, body) + q, set()
    marked = body
    for rx, nm in ((c.LANE_RE, "LANE_ROOT"), (c.M_RE, "M_ROOT")):
        marked = rx.sub("\x00" + nm + "\x00", marked)
    for sid, cn in c.seats:
        marked = re.sub(r"(?<=[/\\])" + re.escape(sid) + r"(?=[/\\]|$)", "\x00" + cn + "\x00", marked)
        if marked == sid: marked = "\x00" + cn + "\x00"
    for rx, cn, _ in c.repo_res: marked = rx.sub("\x00" + cn + "\x00", marked)
    parts = marked.split("\x00")
    if len(parts) == 1:
        nb = words(c, body)
        if nb != body: MSGS.append(where)      # message text in a code string: listed in the receipt for review
        return (prefix + q + nb + q if nb != body else tok), set()
    names = {p for p in parts[1::2]}
    texts = [words(c, p) for p in parts[0::2]]
    if "f" in low:
        flat = ""
        for i, p in enumerate(parts):
            if i % 2 == 0: flat += words(c, p)
            else:
                if depth_inside_braces(flat, len(flat)) > 0: warn.append(f"{where}: root inside an f-string replacement field")
                flat += "{" + p + "}"
        return prefix + q + flat + q, names
    plain = prefix.replace("f", "").replace("F", "")
    pieces = []
    for i, p in enumerate(parts):
        if i % 2 == 1: pieces.append(p)
        elif p != "" or len(parts) == 1: pieces.append(plain + q + words(c, p) + q)
    return "(" + " + ".join(pieces) + ")" if len(pieces) > 1 else pieces[0], names


def docstring_starts(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            out.add((n.body[0].lineno, n.body[0].col_offset))
    return out


def root_const(c, v):
    """-> 'LANE_ROOT' / 'M_ROOT' when v is a string constant that IS exactly the lane root / machine root (no suffix), else None"""
    if not (isinstance(v, ast.Constant) and isinstance(v.value, str)): return None
    m = c.LANE_RE.match(v.value)
    if m and m.end() == len(v.value): return "LANE_ROOT"
    m = c.M_RE.match(v.value)
    if m and m.end() == len(v.value): return "M_ROOT"
    return None


def lane_suffix(c, node, aliases):
    """suffix after the lane root for a constant 'LANE/x', for 'ALIAS + "/x"' and for a bare alias; None when node does not start at the lane root"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        m = c.LANE_RE.match(node.value); return node.value[m.end():] if m else None
    if isinstance(node, ast.Name): return "" if aliases.get(node.id) == "LANE_ROOT" else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
        left = lane_suffix(c, node.left, aliases); return left + node.right.value if left == "" else None
    return None


def is_scripts_insert(c, n, aliases):
    """module-level sys.path.insert(0, <lane root>/scripts): redundant in the exported tree (the prologue puts the file's own tree directory on sys.path) and unevaluable for the
    repository's self-location census, so the exporter drops it; the proof drops the same statement from the original"""
    if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == "sys.path.insert" and len(n.value.args) == 2 and not n.value.keywords): return False
    a0, a1 = n.value.args
    return isinstance(a0, ast.Constant) and a0.value == 0 and lane_suffix(c, a1, aliases) in ("/scripts", "/scripts/")


def stmt_plan(c, tree):
    """-> [(statement, replacement text, lane_config name)] for the module-level statements the exporter rewrites as statements:
    NAME = <exact lane/machine root>  ->  from lane_config import LANE_ROOT as NAME   (a config import, not a path assignment)
    sys.path.insert(0, <lane root>/scripts)  ->  pass"""
    plan = []; aliases = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            k = root_const(c, n.value)
            if k: aliases[n.targets[0].id] = k; plan.append((n, f"from lane_config import {k} as {n.targets[0].id}", k))
        elif is_scripts_insert(c, n, aliases): plan.append((n, "pass", "LANE_ROOT"))
    return plan


def export_py(c, text, depth, warn, rel):
    tree = ast.parse(text); docs = docstring_starts(tree)
    lines = text.splitlines(keepends=True); starts = [0]
    for l in lines: starts.append(starts[-1] + len(l))
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline)); edits = []; used = set()
    sig = [t for t in toks if t.type not in (tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)]      # NEWLINE stays: two string STATEMENTS on adjacent lines are not an implicit concatenation
    for i, t in enumerate(sig):
        if t.type == tokenize.STRING and ((i + 1 < len(sig) and sig[i + 1].type == tokenize.STRING) or (i > 0 and sig[i - 1].type == tokenize.STRING)):
            if c.M_RE.search(t.string) or any(re.search(re.escape(s), t.string) for s, _ in c.seats) or any(rx.search(t.string) for rx, _, _ in c.repo_res):
                warn.append(f"{rel}:{t.start[0]}: implicit string concatenation carries a root or seat id")
    for t in toks:
        where = f"{rel}:{t.start[0]}"
        if t.type == tokenize.COMMENT: new = doc_text(c, t.string); nm = set()
        elif t.type == tokenize.STRING:
            if t.start in docs: new = doc_text(c, t.string); nm = set()
            else: new, nm = code_string(c, t.string, warn, where)
        elif t.type == tokenize.NAME and any(r.lower() == sid.lower() for r in re.findall(r"[A-Za-z]+", t.string) for sid, _ in c.seats):
            warn.append(f"{where}: identifier carries a seat id: {t.string}"); continue
        else: continue
        if new != t.string:
            a = starts[t.start[0] - 1] + t.start[1]; b = starts[t.end[0] - 1] + t.end[1]; edits.append((a, b, new)); used |= nm
    def off(lineno, col): return starts[lineno - 1] + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8"))
    for n, repl, nm in stmt_plan(c, tree):
        a, b = off(n.lineno, n.col_offset), off(n.end_lineno, n.end_col_offset)
        edits = [e for e in edits if not (e[0] >= a and e[1] <= b)]; edits.append((a, b, repl)); used.add(nm)
    for a, b, new in sorted(edits, reverse=True): text = text[:a] + new + text[b:]
    if used:
        ref = "_os.path.dirname(_os.path.abspath(__file__))"
        for _ in range(depth): ref = "_os.path.dirname(" + ref + ")"
        pro = "import os as _os, sys as _sys\n_sys.path.insert(0, " + ref + ")\nfrom lane_config import " + ", ".join(sorted(used)) + "\n"
        t2 = ast.parse(text); at = 0
        for n in t2.body:
            if (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str) and n is t2.body[0]) or \
                    (isinstance(n, ast.ImportFrom) and n.module == "__future__"): at = n.end_lineno
        l2 = text.splitlines(keepends=True)
        if at == 0:      # no docstring / __future__: keep shebang and leading comment lines first
            while at < len(l2) and l2[at].startswith("#"): at += 1
        text = "".join(l2[:at]) + pro + "".join(l2[at:])
    if "goal_id:" not in text[:400]:
        if text.startswith("#!"): first, _, rest = text.partition("\n"); text = first + "\n" + HEADER + rest
        else: text = HEADER + text
    return text, used


def export_sh(c, text):
    text = c.LANE_RE.sub("$EMBER_LANE_ROOT", text); text = c.M_RE.sub("$EMBER_M_ROOT", text)
    return doc_text_sh(c, text)


def doc_text_sh(c, text):
    for sid, cn in c.seats: text = re.sub(r"(?<=[/\\])" + re.escape(sid) + r"(?=[/\\]|$)", "$EMBER_" + cn, text)
    for rx, cn, _ in c.repo_res: text = rx.sub("$EMBER_" + cn, text)
    return words(c, text)


def export_ps1(c, text):
    def lane_sub(m): return "(Join-Path $env:EMBER_LANE_ROOT '" + m.group(1).lstrip("\\/") + "')"
    text = re.sub(r"'" + c.LANE_RE.pattern + r"((?:[/\\][^'\r\n]*)?)'", lane_sub, text)
    text = re.sub(r"'" + c.M_RE.pattern + r"((?:[/\\][^'\r\n]*)?)'", lambda m: "(Join-Path $env:EMBER_M_ROOT '" + m.group(1).lstrip("\\/") + "')", text)
    for sid, cn in c.seats: text = text.replace("'" + sid + "'", "$env:EMBER_" + cn)
    text = c.LANE_RE.sub("$env:EMBER_LANE_ROOT", text); text = c.M_RE.sub("$env:EMBER_M_ROOT", text)
    for rx, cn, _ in c.repo_res: text = rx.sub("$env:EMBER_" + cn, text)
    return words(c, text)


def norm_str(c, s, strict=False):
    """strict (code strings): a seat id that is the whole string or a path segment is FUNCTIONAL and is kept; only message words are normalised away. Docstrings: loose."""
    if strict:
        for k, (sid, _) in enumerate(c.seats):
            tag = "%d" % k
            if s == sid: return tag
            s = re.sub(r"(?<=[/\\])" + re.escape(sid) + r"(?=[/\\]|$)", tag, s)
    lt, mt = ("\x01L\x01", "\x01M\x01") if strict else ("", "")      # code strings keep WHICH root they name (lane root vs machine root): swapping one for the other must fail the proof; docstrings drop roots (reworded as role words)
    s = c.LANE_RE.sub(lt, s); s = c.M_RE.sub(mt, s)
    if not strict:
        for rx, _, _ in c.repo_res: s = rx.sub("", s)      # docstrings/comments: the name is reworded to a placeholder; code strings keep WHICH repo (a swap must fail the proof)
    s = re.sub(r"<[a-z\-]+>", "", s)
    for rx, n in c.word_res: s = rx.sub("", s)
    for _, n in c.words: s = re.sub(r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])", "", s)
    for sid, _ in c.seats: s = re.sub(r"(?<![A-Za-z])" + re.escape(sid) + r"(?![A-Za-z])", "", s, flags=re.I)
    s = re.sub(r"(?<![A-Za-z])the(?![A-Za-z])", "", s, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[/\\]+", "/", s)).strip().lower()


class Fold(ast.NodeTransformer):
    def __init__(self, vals): self.vals = vals
    def visit_Name(self, n): return ast.copy_location(ast.Constant(self.vals[n.id]), n) if n.id in self.vals else n
    def visit_BinOp(self, n):
        self.generic_visit(n)
        if isinstance(n.op, ast.Add) and isinstance(n.left, ast.Constant) and isinstance(n.right, ast.Constant) and isinstance(n.left.value, str) and isinstance(n.right.value, str):
            return ast.copy_location(ast.Constant(n.left.value + n.right.value), n)
        return n
    def visit_FormattedValue(self, n):
        self.generic_visit(n)
        if isinstance(n.value, ast.Constant) and n.conversion == -1 and n.format_spec is None: return n.value
        return n
    def visit_JoinedStr(self, n):
        self.generic_visit(n); vals = []
        for v in n.values:
            if isinstance(v, ast.Constant) and vals and isinstance(vals[-1], ast.Constant): vals[-1] = ast.Constant(vals[-1].value + v.value)
            else: vals.append(v)
        if all(isinstance(v, ast.Constant) for v in vals): return ast.copy_location(ast.Constant("".join(v.value for v in vals)), n)
        n.values = vals; return n


def canon(c, tree, strip_prologue):
    body = []; aliases = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and root_const(c, n.value): aliases[n.targets[0].id] = root_const(c, n.value)
        if not strip_prologue and is_scripts_insert(c, n, aliases): continue      # dropped by the exporter (the prologue covers it)
        if strip_prologue:
            if isinstance(n, ast.ImportFrom) and n.module == "lane_config":
                if all(a.asname is None for a in n.names): continue                # the prologue import
                for a in n.names:                                                  # `from lane_config import X as NAME` stands for `NAME = <value of X>`
                    body.append(ast.Assign(targets=[ast.Name(a.asname, ast.Store())], value=ast.Name(a.name, ast.Load()), lineno=n.lineno))
                continue
            if isinstance(n, ast.Import) and [a.asname for a in n.names] == ["_os", "_sys"]: continue
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == "_sys.path.insert": continue
        if isinstance(n, ast.Pass): continue                                       # the exporter's stand-in for a dropped statement
        body.append(n)
    tree.body = body
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}
    tree = Fold(c.vals).visit(tree); ast.fix_missing_locations(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str): n.value = norm_str(c, n.value, strict=id(n) not in docs)
    return ast.dump(tree, annotate_fields=False, include_attributes=False)


def verify(c, orig, new):
    return canon(c, ast.parse(orig), False) == canon(c, ast.parse(new), True)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--src", required=True); ap.add_argument("--dst", required=True); ap.add_argument("--m-root", required=True)
    ap.add_argument("--lane-dir", required=True); ap.add_argument("--seat", action="append", default=[]); ap.add_argument("--word", action="append", default=[]); ap.add_argument("--repo", action="append", default=[], help="PRIVATE_REPO_NAME=CONFIG_NAME: a private HF repo name replaced by a lane_config value")
    ap.add_argument("--exclude", action="append", default=[]); ap.add_argument("--receipt"); ap.add_argument("--keep", action="append", default=[], help="relative path copied verbatim (already neutral)")
    a = ap.parse_args(argv); c = Cfg(a); warn = []; rows = []; bad = []
    for dp, dn, fn in os.walk(a.src):
        dn[:] = sorted(d for d in dn if d != "__pycache__")
        for f in sorted(fn):
            s = os.path.join(dp, f); rel = os.path.relpath(s, a.src).replace("\\", "/")
            if rel in a.exclude or not f.endswith((".py", ".sh", ".ps1")): continue
            text = open(s, encoding="utf-8", newline="").read().replace("\r\n", "\n"); depth = rel.count("/"); used = set()
            if rel == "census_hash.py":
                text, nsub = re.subn(r"(?m)^SKIP_PREFIXES = \(.*\)$", lambda m: PATCH_CENSUS_SKIP, text); assert nsub == 1, "census_hash SKIP_PREFIXES line not found"
            if rel in a.keep: new = text
            elif f.endswith(".py"):
                new, used = export_py(c, text, depth, warn, rel)
                try:
                    if not verify(c, text, new): bad.append(rel + ": AST equivalence FAILED")
                except Exception as e: bad.append(rel + ": verify error " + type(e).__name__ + " " + str(e)[:80])
            elif f.endswith(".sh"): new = export_sh(c, text)
            else: new = export_ps1(c, text)
            if "goal_id:" not in new[:400] and not f.endswith(".py"):
                new = (new.partition("\n")[0] + "\n" + HEADER + new.partition("\n")[2]) if new.startswith("#!") else HEADER + new
            d = os.path.join(a.dst, rel); os.makedirs(os.path.dirname(d), exist_ok=True)
            open(d, "w", encoding="utf-8", newline="").write(new)
            rows.append(dict(path=rel, src_sha256=hashlib.sha256(text.encode()).hexdigest(), out_sha256=hashlib.sha256(new.encode()).hexdigest(), lane_config_names=sorted(used)))
    out = dict(files=len(rows), warnings=warn, failures=bad, message_strings_reworded=MSGS, rows=rows)
    if a.receipt: json.dump(out, open(a.receipt, "w"), indent=1)
    print(f"exported {len(rows)} files; warnings {len(warn)}; failures {len(bad)}; reworded message strings {len(MSGS)}")
    for w in warn[:40]: print("WARN", w)
    for b in bad[:40]: print("FAIL", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
