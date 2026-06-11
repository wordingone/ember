"""fp10_idiom.py — idiom-separability probe (#73, fp-10).

fp-6 (audit §8.15c) pre-registered this probe FROZEN: are the 956 W-code
ledger episodes (3B-emitted) stylistically separable from the MBPP
sanitized reference solutions (human-written)? If a from-scratch core
pretrains on ledger episodes, a separable style signature is what it
would inherit as ground truth.

Frozen design (do not reinterpret):
  - Texts: verified mbpp ledger episodes' src  vs  the raw dataset's
    "code" field (reference solutions) for the SAME tasks — pairing by
    task controls the task-content confound; w1_mbpp.load_split does not
    return "code", so this script reads the raw dataset itself.
  - Features: cheap stylometry per program (type-hint rate, docstring/
    comment rate, f-string usage, quote style, identifier casing, mean
    line length, comprehension/lambda rate) + hashed char-3gram bag
    (crc32 % 256 buckets, count-normalized).
  - Classifier: logistic regression, 5-fold CV split BY TASK
    (sha1(task)%5 — both classes' rows for a task share a fold; no task
    leakage). sklearn if present, else a self-contained numpy
    gradient-descent twin (convex, deterministic).
  - Pre-registered verdict: pooled out-of-fold CV-AUC >= 0.75 =
    signature real and quantified (report top features); below =
    contamination concern demoted at this granularity.

Receipt: receipts/fp10-idiom-<ts>.json — AUC (pooled + per-fold), top
stylometry coefficients with per-class means, top 3-gram buckets with
example grams, and the §8.15d consequence block (marked-bits fraction,
mechanical-filter pointer). `python fp10_idiom.py --selftest` is
pure-logic and runs anywhere.
"""
import ast
import hashlib
import json
import sys
import zlib
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
LEDGER = f"{NC}/ledger/episodes.jsonl"

N_BUCKETS = 256
N_FOLDS = 5
AUC_BAR = 0.75
STYLO_NAMES = ["type_hint_rate", "doc_comment_rate", "fstring_rate",
               "single_quote_frac", "camel_ident_frac", "mean_line_len",
               "comprehension_lambda_per_line"]


# ---------- features ----------

def stylometry(src):
    """7 frozen stylometry features. ast-derived fields fall to 0 on a
    parse failure (flagged by caller via parses(src))."""
    lines = [ln for ln in src.splitlines() if ln.strip()]
    n_lines = max(len(lines), 1)
    mean_len = sum(len(ln) for ln in lines) / n_lines
    n_sq, n_dq = src.count("'"), src.count('"')
    sq_frac = n_sq / max(n_sq + n_dq, 1)
    comment_lines = sum(1 for ln in lines if ln.lstrip().startswith("#"))

    ann = args = defs = fstr = nstr = comp = lam = doc_lines = 0
    idents, camel = set(), 0
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs += 1
                a = node.args
                all_args = a.args + a.posonlyargs + a.kwonlyargs
                args += len(all_args)
                ann += sum(1 for x in all_args if x.annotation is not None)
                ann += int(node.returns is not None)
                ds = ast.get_docstring(node)
                if ds:
                    doc_lines += ds.count("\n") + 1
                idents.add(node.name)
                for x in all_args:
                    idents.add(x.arg)
            elif isinstance(node, ast.Name):
                idents.add(node.id)
            elif isinstance(node, ast.JoinedStr):
                fstr += 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                nstr += 1
            elif isinstance(node, (ast.ListComp, ast.SetComp,
                                   ast.DictComp, ast.GeneratorExp)):
                comp += 1
            elif isinstance(node, ast.Lambda):
                lam += 1
        for name in idents:
            body = name.lstrip("_")
            if any(c.islower() for c in body) and any(c.isupper() for c in body) \
                    and "_" not in body:
                camel += 1
    except SyntaxError:
        pass

    return [
        ann / max(args + defs, 1),
        (doc_lines + comment_lines) / n_lines,
        fstr / max(fstr + nstr, 1),
        sq_frac,
        camel / max(len(idents), 1),
        mean_len,
        (comp + lam) / n_lines,
    ]


def parses(src):
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def trigram_bag(src, n_buckets=N_BUCKETS):
    """Hashed char-3gram counts, normalized by total grams. crc32 is
    deterministic across processes (builtin hash() is salted — never)."""
    vec = [0.0] * n_buckets
    grams = [src[i:i + 3] for i in range(len(src) - 2)]
    for g in grams:
        vec[zlib.crc32(g.encode("utf-8", "replace")) % n_buckets] += 1.0
    total = max(len(grams), 1)
    return [v / total for v in vec]


def featurize(src):
    return stylometry(src) + trigram_bag(src)


# ---------- CV machinery ----------

def task_fold(task_key, n_folds=N_FOLDS):
    h = hashlib.sha1(str(task_key).encode()).hexdigest()
    return int(h, 16) % n_folds


def standardize(train_rows, test_rows):
    """Per-feature z-score from TRAIN stats only (fold discipline)."""
    d = len(train_rows[0])
    mu = [sum(r[j] for r in train_rows) / len(train_rows) for j in range(d)]
    var = [sum((r[j] - mu[j]) ** 2 for r in train_rows) / len(train_rows)
           for j in range(d)]
    sd = [v ** 0.5 if v > 1e-12 else 1.0 for v in var]
    f = lambda rows: [[(r[j] - mu[j]) / sd[j] for j in range(d)] for r in rows]
    return f(train_rows), f(test_rows)


def fit_logreg(X, y):
    """Returns (predict_proba_fn, coef list). sklearn when present, else a
    numpy GD twin (convex objective — deterministic, no seed)."""
    try:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        clf.fit(X, y)
        coef = list(clf.coef_[0])
        return (lambda Z: [p[1] for p in clf.predict_proba(Z)]), coef
    except ImportError:
        import numpy as np
        Xn, yn = np.asarray(X), np.asarray(y, dtype=float)
        n, d = Xn.shape
        # balanced class weights, L2 like sklearn's default C=1
        w_pos = n / (2 * max(yn.sum(), 1))
        w_neg = n / (2 * max(n - yn.sum(), 1))
        sw = np.where(yn == 1, w_pos, w_neg)
        w = np.zeros(d)
        b = 0.0
        lr = 0.1
        for _ in range(3000):
            z = Xn @ w + b
            p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
            g = sw * (p - yn)
            w -= lr * (Xn.T @ g / n + 1.0 * w / n)
            b -= lr * g.mean()
        return (lambda Z: list(1 / (1 + np.exp(-(np.asarray(Z) @ w + b))))), \
            list(w)


def auc(scores, labels):
    """Rank-based (Mann-Whitney), tie-aware. Pure python."""
    pairs = sorted(zip(scores, labels))
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        mean_rank = (i + 1 + j) / 2  # 1-based average rank of the tie block
        rank_sum += mean_rank * sum(1 for k in range(i, j) if pairs[k][1] == 1)
        i = j
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def cross_validate(rows):
    """rows: (task, label, feature_vec). Returns pooled AUC, per-fold
    AUCs, mean |coef| per feature across folds."""
    oof_scores, oof_labels = [], []
    fold_aucs = []
    d = len(rows[0][2])
    coef_acc = [0.0] * d
    for f in range(N_FOLDS):
        tr = [r for r in rows if task_fold(r[0]) != f]
        te = [r for r in rows if task_fold(r[0]) == f]
        if not te or len({r[1] for r in te}) < 2 or len({r[1] for r in tr}) < 2:
            fold_aucs.append(None)
            continue
        Xtr, Xte = standardize([r[2] for r in tr], [r[2] for r in te])
        predict, coef = fit_logreg(Xtr, [r[1] for r in tr])
        s = predict(Xte)
        oof_scores += list(s)
        oof_labels += [r[1] for r in te]
        fold_aucs.append(round(auc(list(s), [r[1] for r in te]), 4))
        for j in range(d):
            coef_acc[j] += abs(coef[j]) / N_FOLDS
    return auc(oof_scores, oof_labels), fold_aucs, coef_acc


# ---------- main leg ----------

def load_texts():
    from datasets import load_dataset
    eps = []
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if str(r.get("task", "")).startswith("mbpp:") \
                    and r.get("verified") and r.get("src"):
                eps.append((r["task"], r["src"]))
    tasks = {t for t, _ in eps}
    ds = load_dataset("google-research-datasets/mbpp", "sanitized",
                      split="train")
    humans = [(f"mbpp:{int(r['task_id'])}", r["code"]) for r in ds
              if f"mbpp:{int(r['task_id'])}" in tasks]
    return eps, humans


def top_trigrams_for_bucket(bucket, texts_pos, texts_neg, k=3):
    """Most class-skewed observed grams hashing into this bucket."""
    def count(texts):
        c = {}
        for t in texts:
            for i in range(len(t) - 2):
                g = t[i:i + 3]
                if zlib.crc32(g.encode("utf-8", "replace")) % N_BUCKETS == bucket:
                    c[g] = c.get(g, 0) + 1
        return c
    cp, cn = count(texts_pos), count(texts_neg)
    grams = sorted(set(cp) | set(cn),
                   key=lambda g: -abs(cp.get(g, 0) / max(len(texts_pos), 1)
                                      - cn.get(g, 0) / max(len(texts_neg), 1)))
    return [{"gram": g, "per_ep": round(cp.get(g, 0) / max(len(texts_pos), 1), 2),
             "per_human": round(cn.get(g, 0) / max(len(texts_neg), 1), 2)}
            for g in grams[:k]]


def main():
    eps, humans = load_texts()
    parse_fail = sum(1 for _, s in eps + humans if not parses(s))
    rows = [(t, 1, featurize(s)) for t, s in eps] + \
           [(t, 0, featurize(s)) for t, s in humans]
    pooled, per_fold, coef = cross_validate(rows)
    verdict = "signature-real" if pooled >= AUC_BAR else "demoted"

    # interpretability: stylometry coefs + class means; top 3gram buckets
    ep_srcs, hu_srcs = [s for _, s in eps], [s for _, s in humans]
    ep_sty = [stylometry(s) for s in ep_srcs]
    hu_sty = [stylometry(s) for s in hu_srcs]
    stylo_report = []
    for j, name in enumerate(STYLO_NAMES):
        stylo_report.append({
            "feature": name, "mean_abs_coef": round(coef[j], 3),
            "episode_mean": round(sum(r[j] for r in ep_sty) / len(ep_sty), 4),
            "human_mean": round(sum(r[j] for r in hu_sty) / len(hu_sty), 4)})
    stylo_report.sort(key=lambda r: -r["mean_abs_coef"])
    n_sty = len(STYLO_NAMES)
    gram_idx = sorted(range(n_sty, n_sty + N_BUCKETS),
                      key=lambda j: -coef[j])[:5]
    gram_report = [{"bucket": j - n_sty,
                    "mean_abs_coef": round(coef[j], 3),
                    "top_grams": top_trigrams_for_bucket(
                        j - n_sty, ep_srcs, hu_srcs)} for j in gram_idx]

    dup_srcs = len(ep_srcs) - len(set(ep_srcs))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP10-IDIOM", "ts": ts,
        "prereg": "audit §8.15c (frozen): CV-AUC >= 0.75 = signature real",
        "n_episodes": len(eps), "n_human_refs": len(humans),
        "n_tasks": len({t for t, _ in eps}),
        "parse_failures": parse_fail,
        "duplicate_episode_srcs": dup_srcs,
        "features": f"{len(STYLO_NAMES)} stylometry + {N_BUCKETS} hashed "
                    "char-3gram buckets (crc32), z-scored per train fold",
        "cv": "5-fold by sha1(task)%5 — both classes of a task share a fold",
        "auc_pooled_oof": round(pooled, 4),
        "auc_per_fold": per_fold,
        "verdict": verdict,
        "top_stylometry": stylo_report,
        "top_trigram_buckets": gram_report,
        "consequence_8_15d": {
            "marked_episode_bits": 573.2,
            "marked_bits_source": "fp6-provenance receipt (qwen-research class)",
            "mechanical_filter": "eng #70 ledger_license.py --license-allow "
                                 "(UNKNOWN fail-closed) already excludes the "
                                 "marked class from owned-core builds",
            "dilution_order": "human refs > apache-core (1.5B/7B) sampling > "
                              "other-world episodes > arc-dsl-MIT mass"},
        "flags": ["class imbalance episodes:humans handled by balanced "
                  "class weights; AUC is rank-based (imbalance-insensitive)",
                  "duplicate srcs stay within their task's fold — no "
                  "cross-fold leakage",
                  "feature FORMULAS are implementation choices; the frozen "
                  "spec fixes the feature FAMILIES and the 0.75 bar"],
    }
    out = f"{RECEIPTS}/fp10-idiom-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP10_IDIOM_DONE {out}")


# ---------- selftest (pure logic, runs anywhere) ----------

def _selftest():
    # stylometry on a known snippet
    src_hint = ("def f(x: int) -> int:\n"
                "    \"\"\"doc line\"\"\"\n"
                "    # comment\n"
                "    y = [i for i in range(x)]\n"
                "    return len(y)\n")
    s = stylometry(src_hint)
    assert s[0] == 2 / 2, s  # 1 arg ann + 1 return ann over 1 arg + 1 def
    assert s[1] == 2 / 5, s  # 1 docstring line + 1 comment over 5 lines
    assert s[6] == 1 / 5, s  # one comprehension over 5 lines
    src_camel = "def myFunc(someArg):\n    return someArg\n"
    sc = stylometry(src_camel)
    assert sc[4] == 1.0, sc  # both identifiers camelCase
    assert stylometry("def broken(:\n")[0] == 0.0  # parse-fail -> ast zeros
    assert not parses("def broken(:") and parses("x = 1")
    # trigram bag: deterministic, normalized
    b1, b2 = trigram_bag("hello world"), trigram_bag("hello world")
    assert b1 == b2 and abs(sum(b1) - 1.0) < 1e-9
    # fold split: 5-way partition, deterministic, groups by task
    folds = {t: task_fold(t) for t in (f"mbpp:{i}" for i in range(200))}
    assert set(folds.values()) <= set(range(5)) and len(set(folds.values())) == 5
    assert task_fold("mbpp:7") == task_fold("mbpp:7")
    # AUC: perfect / reversed / ties
    assert auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]) == 0.5
    assert auc([1, 1], [1, 1]) is None  # single class
    # standardize: train stats only, zero-mean train
    tr, te = standardize([[0.0, 2.0], [2.0, 4.0]], [[1.0, 3.0]])
    assert abs(tr[0][0] + tr[1][0]) < 1e-9 and abs(te[0][0]) < 1e-9
    # end-to-end CV on a constructed separable world (40 tasks x 2 classes;
    # feature = label + small task-dependent jitter) -> AUC ~ 1
    rows = []
    for i in range(40):
        t = f"t:{i}"
        jit = (i % 7) * 0.01
        rows.append((t, 1, [1.0 + jit, 0.0]))
        rows.append((t, 0, [0.0 + jit, 0.0]))
    pooled, per_fold, coef = cross_validate(rows)
    assert pooled > 0.95, pooled
    assert coef[0] > coef[1], coef  # informative feature carries the weight
    # and an unseparable world -> AUC ~ 0.5
    rows0 = [(f"t:{i}", i % 2, [0.0, 0.0]) for i in range(80)]
    p0, _, _ = cross_validate(rows0)
    assert 0.3 < p0 < 0.7, p0
    print("FP10_IDIOM_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
