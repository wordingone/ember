# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Degenerate-object scan for a packed pack (lead 82716 item 3; finding: one 1,144,723-token period-2 object trained 8 ledger rows).

Usage: degenerate_scan.py PACK_DIR [--ledger L] [--shards-dir D] [--run-min N] [--max-period K] [--min-match PCT] [--allow-missing] [--json OUT]

Reads PACK_DIR/ledger.jsonl and PACK_DIR/shards/v1-*.bin (little-endian uint16 tokens, read-only) and checks object by object. In a ledger row, span token_start/token_end are SOURCE-STREAM coordinates
(end - start = the object's token count); the shard-relative offset of span i is the cumulative sum of the span lengths before it. An object is REFUSED when it holds a run of >= RUN_MIN consecutive
tokens that is period-k repetition for some k in 1..MAX_PERIOD with >= MIN_MATCH percent of positions satisfying tok[i] == tok[i+k] (checked as a sliding window of RUN_MIN tokens, vectorised per k,
one shard at a time). A run that straddles a shard boundary is found through a carried tail. Objects are never mixed: a window never crosses an object boundary.

Edges are trimmed to the first/last streak of 32 consecutive matches, so run_tokens (the trimmed matching span) can sit a few dozen tokens below RUN_MIN while the RUN_MIN window still met MIN_MATCH.
Output: one line per refused object (object sha256, shard, offsets, period, run length) and a summary line; never token text. Exit 0 clean, 1 refused objects named (also when errors exist), 2 cannot scan
(missing shard / inconsistent ledger / bad arguments).

--json OUT writes the records; OUT must not sit inside the pack and must sit under <repo>/scratch/ or a root listed in DEGEN_SCAN_OUT_ROOT (os.pathsep-separated).
Defaults: DEGEN_RUN_MIN=4096, DEGEN_MAX_PERIOD=16, DEGEN_MIN_MATCH=99. Numpy only; CPU only, at most 4 threads. No model anywhere."""
import os, sys, json, time, argparse
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "4")
import numpy as np

RUN_MIN = int(os.environ.get("DEGEN_RUN_MIN", "4096"))
MAX_PERIOD = int(os.environ.get("DEGEN_MAX_PERIOD", "16"))
MIN_MATCH = int(os.environ.get("DEGEN_MIN_MATCH", "99"))
STREAK = 32                                                      # edge trimming: a run starts/ends at a streak of this many consecutive matches


def find_runs(tok, run_min, max_period, min_match=99):
    """tok: 1-D uint16 array. Returns [(period, start, end)] token ranges [start, end) (merged across periods; period = smallest k that flags the run)."""
    n = len(tok)
    out = []
    if n < run_min or run_min <= max_period:
        return out
    for k in range(1, max_period + 1):
        m = tok[k:] == tok[:-k]                                  # length n-k
        cs = np.zeros(n - k + 1, dtype=np.int32)
        np.cumsum(~m, dtype=np.int32, out=cs[1:])
        w = run_min - k                                          # comparisons inside a window of run_min tokens
        mism = cs[w:n - k + 1] - cs[:n - run_min + 1]            # window i = tokens i..i+run_min-1, comparisons i..i+w-1
        flagged = mism <= (w * (100 - min_match)) // 100
        if not flagged.any():
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], flagged.view(np.int8), [0]))))
        for a, b in zip(edges[0::2], edges[1::2]):               # flagged window starts [a, b)
            lo, hi = int(a), int(b - 1 + run_min - k)            # comparison positions covered: lo..hi-1
            reg = m[lo:hi]                                                    # trim the <=1% window fuzz: first/last position of a STREAK consecutive matches
            sc = np.zeros(len(reg) + 1, dtype=np.int32)
            np.cumsum(reg, dtype=np.int32, out=sc[1:])
            hit = np.flatnonzero(sc[STREAK:] - sc[:-STREAK] == STREAK) if len(reg) >= STREAK else np.empty(0, dtype=np.int64)
            if len(hit) == 0:
                continue
            out.append((k, lo + int(hit[0]), lo + int(hit[-1]) + STREAK + k))
    return _merge(out)


def _merge(runs):
    runs = sorted(runs, key=lambda r: (r[1], r[2]))
    merged = []
    for k, s, e in runs:
        if merged and s <= merged[-1][2]:
            pk, ps, pe = merged[-1]
            merged[-1] = (min(pk, k), ps, max(pe, e))
        else:
            merged.append((k, s, e))
    return merged


def _ledger(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def scan(pack_dir, ledger_path=None, shards_dir=None, run_min=RUN_MIN, max_period=MAX_PERIOD, min_match=MIN_MATCH, allow_missing=False):
    """Returns (records, stats, errors). records: one dict per refused object run (sorted by position)."""
    ledger_path = ledger_path or os.path.join(pack_dir, "ledger.jsonl")
    shards_dir = shards_dir or os.path.join(pack_dir, "shards")
    rows = _ledger(ledger_path)
    tail_len = run_min + max_period
    raw = []                                                     # (sha, src_start, src_end, k, start_shard, start_off, end_shard, end_off)
    errors, missing = [], []
    stats = dict(shards=0, shards_missing=0, objects=set(), tokens=0)
    carry = None                                                 # (sha, token_end, tail array, shard name, shard n_tokens)
    for row in rows:
        name, n = row["name"], int(row["n_tokens"])
        spans = row["spans"]
        if sum(int(s["token_end"]) - int(s["token_start"]) for s in spans) != n:
            errors.append("ledger row %s: span lengths do not sum to n_tokens" % row.get("index"))
            carry = None
            continue
        path = os.path.join(shards_dir, name)
        if not os.path.isfile(path):
            missing.append(name); stats["shards_missing"] += 1; carry = None
            continue
        if os.path.getsize(path) != 2 * n:
            errors.append("shard %s: size %d != 2 x n_tokens %d" % (name, os.path.getsize(path), n))
            carry = None
            continue
        arr = np.memmap(path, dtype="<u2", mode="r")
        stats["shards"] += 1; stats["tokens"] += n
        rel = 0
        for si, sp in enumerate(spans):
            ln = int(sp["token_end"]) - int(sp["token_start"]); sha = sp["sha256"]
            stats["objects"].add(sha)
            seg = np.asarray(arr[rel:rel + ln])
            pre = None
            if si == 0 and carry and carry[0] == sha and carry[1] == int(sp["token_start"]):
                pre = carry[2]
            win = np.concatenate((pre, seg)) if pre is not None and len(pre) else seg
            plen = 0 if pre is None else len(pre)
            for k, s, e in find_runs(win, run_min, max_period, min_match):
                s_rel, e_rel = rel + s - plen, rel + e - plen                    # shard-relative; negative start = previous shard
                if s_rel < 0 and carry:
                    s_name, s_off = carry[3], carry[4] + s_rel
                else:
                    s_name, s_off = name, s_rel
                raw.append((sha, int(sp["token_start"]) + s - plen, int(sp["token_start"]) + e - plen, k, s_name, s_off, name, e_rel))
            rel += ln
        last = spans[-1]
        carry = (last["sha256"], int(last["token_end"]), np.array(arr[max(0, n - tail_len):n]), name, n)
        del arr
    if missing and not allow_missing:
        errors.append("missing shards (cannot claim clean): %s" % ", ".join(missing[:10]) + (" ... +%d" % (len(missing) - 10) if len(missing) > 10 else ""))
    # merge duplicates produced by the carried tail: same object, overlapping source coordinates
    recs = []
    for sha in sorted({r[0] for r in raw}):
        grp = sorted((r for r in raw if r[0] == sha), key=lambda r: (r[1], r[2]))
        cur = None
        for r in grp:
            if cur and r[1] <= cur["source_end"]:
                cur["period"] = min(cur["period"], r[3])
                if r[2] > cur["source_end"]:
                    cur["source_end"] = r[2]; cur["end_shard"] = r[6]; cur["shard_end"] = r[7]
            else:
                cur = dict(object_sha256=sha, shard=r[4], shard_start=r[5], end_shard=r[6], shard_end=r[7], source_start=r[1], source_end=r[2], period=r[3])
                recs.append(cur)
    for c in recs:
        c["run_tokens"] = c["source_end"] - c["source_start"]
    recs.sort(key=lambda c: (c["source_start"], c["object_sha256"]))
    stats["objects"] = len(stats["objects"])
    return recs, stats, errors


def _json_ok(out, pack_dir):
    out = os.path.realpath(out)
    if out.startswith(os.path.realpath(pack_dir) + os.sep):
        return False
    top = os.path.dirname(os.path.abspath(__file__))
    while top != os.path.dirname(top) and not os.path.exists(os.path.join(top, ".git")):
        top = os.path.dirname(top)                               # worktree root (.git file or dir)
    roots = [os.path.join(top, "scratch")]
    roots += [p for p in os.environ.get("DEGEN_SCAN_OUT_ROOT", "").split(os.pathsep) if p]
    return any(out.startswith(os.path.realpath(r) + os.sep) for r in roots)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pack_dir"); ap.add_argument("--ledger"); ap.add_argument("--shards-dir")
    ap.add_argument("--run-min", type=int, default=RUN_MIN); ap.add_argument("--max-period", type=int, default=MAX_PERIOD)
    ap.add_argument("--min-match", type=int, default=MIN_MATCH); ap.add_argument("--allow-missing", action="store_true"); ap.add_argument("--json")
    a = ap.parse_args(argv)
    if a.run_min <= a.max_period or not (50 <= a.min_match <= 100):
        print("degenerate_scan: need run-min > max-period and 50 <= min-match <= 100", file=sys.stderr); return 2
    if a.json and not _json_ok(a.json, a.pack_dir):
        print("degenerate_scan: --json must be under <repo>/scratch/ or DEGEN_SCAN_OUT_ROOT and outside the pack", file=sys.stderr); return 2
    t0 = time.time()
    try:
        recs, st, errs = scan(a.pack_dir, a.ledger, a.shards_dir, a.run_min, a.max_period, a.min_match, a.allow_missing)
    except (OSError, ValueError, KeyError) as e:
        print("degenerate_scan: cannot scan: %s: %s" % (type(e).__name__, e), file=sys.stderr); return 2
    for c in recs:
        end = "" if c["end_shard"] == c["shard"] else " ..%s" % c["end_shard"]
        print("REFUSED object=%s shard=%s offsets=%d..%d%s source=%d..%d period=%d run_tokens=%d" % (
            c["object_sha256"], c["shard"], c["shard_start"], c["shard_end"], end, c["source_start"], c["source_end"], c["period"], c["run_tokens"]))
    print("degenerate_scan: shards=%d missing=%d objects=%d tokens=%d refused_runs=%d refused_objects=%d run_min=%d max_period=%d min_match=%d secs=%.1f" % (
        st["shards"], st["shards_missing"], st["objects"], st["tokens"], len(recs), len({c["object_sha256"] for c in recs}), a.run_min, a.max_period, a.min_match, time.time() - t0))
    for e in errs:
        print("ERROR " + e, file=sys.stderr)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(dict(pack=os.path.basename(os.path.normpath(a.pack_dir)), stats=st, errors=errs, refused=recs), f, indent=1)
    return 1 if recs else (2 if errs else 0)


if __name__ == "__main__":
    sys.exit(main())
