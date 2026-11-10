# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generate the first-skill probe set (coordinator 82425/82428, answer rule from the training lane 82431/82432): exact-answer tasks, answers by construction, no licence, deterministic.
Usage: python probe_gen.py [--out DIR] [--train N] [--test N] [--no-freeze]
Types in order: word_transform (capitalize, reverse, first_letter, last_letter, length) FIRST, arithmetic, string_ops, list_ops, python_trace.
Splits: train-side N per type (default 5000), frozen test N per type (default 2000). Words are split by a hash of the word so train and test words are DISJOINT; every prompt is unique across both splits.
Layout (fixed by the evaluator rule): the model sees  "Q: " + prompt + "\\nA: "  and answers ONE line; the prompt text has no newline; gold has no newline and no leading/trailing space.
Decode arm: greedy, stop at the first newline or 64 tokens, strip whitespace, correct = byte-exact equality with `answer`. Teacher-forced arm: `candidates` = 8 strings including gold (plausible wrong answers of the same type and length class), order shuffled by `candidate_seed`; correct = gold has the lowest answer-token NLL.
Row: {id,type,subtype,prompt,answer,candidates,candidate_seed,check,seed,generator_version,split,difficulty}. check = "exact" or "python-stdout" (answer is the stdout of the one-line program in the prompt).
Writes DIR/train.jsonl, DIR/test.jsonl, DIR/vocab.json, DIR/FREEZE.json (sha256 of every file, per-type/subtype counts, generator sha256); marks test.jsonl read-only; refuses to overwrite a frozen test split."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, io, re, json, hashlib, random, string, collections, contextlib, time, stat, argparse
from lane_config import LANE_ROOT as BASE; GEN_VERSION = "probe-gen-v1"
VOCAB_SRC = BASE + "/packed/hansard-00000-00001/objects/hansard-00000-00001-0000.jsonl.zst"; VOCAB_DOCS = 1500; VOCAB_MIN = 20
LAYOUT = "Q: <prompt>\\nA: <answer>\\n"


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()


def build_vocab(src=VOCAB_SRC, ndocs=VOCAB_DOCS):
    import zstandard
    cnt = collections.Counter(); n = 0
    with open(src, "rb") as f:
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
            cnt.update(re.findall(r"\b[a-z]{3,12}\b", json.loads(line)["text"].lower())); n += 1
            if n >= ndocs: break
    return sorted((w for w, c in cnt.items() if c >= VOCAB_MIN), key=lambda w: (-cnt[w], w))


def split_of_word(w): return "test" if int(hashlib.sha256(w.encode()).hexdigest(), 16) % 5 == 0 else "train"
def rand_string(rng): return "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(3, 12)))
def pick_word(rng, pool, rand_share=0.3): return rand_string(rng) if rng.random() < rand_share else rng.choice(pool)


# ---- plausible-wrong-answer pools (same type, same length class); the framework samples 7 of them
def mut_str(g):
    out = []; n = len(g)
    for i in range(n - 1):
        if g[i] != g[i + 1]: out.append(g[:i] + g[i + 1] + g[i] + g[i + 2:])
    if n > 1: out += [g[:i] + g[i + 1:] for i in range(n)]
    out += [g[:i] + g[i] + g[i:] for i in range(n)]
    for i, c in enumerate(g):
        if c.isalpha():
            base = ord("a") if c.islower() else ord("A")
            out += [g[:i] + chr((ord(c) - base + d) % 26 + base) + g[i + 1:] for d in (-1, 1)]
    return out


def mut_num(g):
    s = str(abs(g)); out = [g + d for d in (1, -1, 2, -2, 10, -10, 100, -100, 1000, -1000)] + [g - g % 10 + d for d in range(10)]
    out += [int(("-" if g < 0 else "") + s[:i] + s[i + 1] + s[i] + s[i + 2:]) for i in range(len(s) - 1)]
    if g != 0: out.append(-g)
    return [c for c in out if (c >= 0) == (g >= 0)]


def finish(gold, hints, generic, rng, same=lambda c: True):
    """-> 8 distinct candidates incl. gold: type-specific hints first (up to 7), then generic mutations"""
    ok = lambda c: isinstance(c, str) and c and c == c.strip() and "\n" not in c and c != gold and not (gold.isdigit() and c.startswith("-"))   # a count / length / sum is never negative
    hints = list(dict.fromkeys(str(h) for h in hints)); pool = []; seen = {gold}
    for c in list(hints) + list(generic):
        c = str(c)
        if ok(c) and c not in seen: seen.add(c); pool.append(c)
    pref = [c for c in pool if same(c)]; rest = [c for c in pool if not same(c)]
    first = [c for c in hints if c in pref]; pref = first + [c for c in pref if c not in first]
    pick = []
    for grp in (pref, rest):
        grp = [c for c in grp if c not in pick]; need = 7 - len(pick)
        if need <= 0: break
        hp = [c for c in grp if c in hints]; ot = [c for c in grp if c not in hp]
        rng.shuffle(ot); pick += (hp + ot)[:need]
    if len(pick) < 7: raise ValueError("not enough distractors for " + gold)
    return pick


# ---- generators: each returns (subtype, prompt, answer, difficulty, check, hints, generic, same)
def g_word_transform(rng, ctx):
    sub = ctx["i"] % 5; w = pick_word(rng, ctx["pool"]); L = len(w); samelen = lambda c: len(c) == L
    if sub == 0:
        g = w[0].upper() + w[1:]
        return "capitalize", f"Capitalize the first letter of the word: {w}", g, L, "exact", [w, w.upper(), w[0].upper() + w[1:-1] + w[-1].upper(), w[:-1] + w[-1].upper(), w[0].upper() + w[1:].upper(), w.swapcase(), w[:1] + w[1:2].upper() + w[2:]], mut_str(g), samelen
    if sub == 1:
        g = w[::-1]
        return "reverse", f"Reverse the letters of the word: {w}", g, L, "exact", [w, "".join(sorted(w)), g[1:] + g[:1], g[-1:] + g[:-1]], mut_str(g), samelen
    if sub == 2:
        g = w[0]; return "first_letter", f"What is the first letter of the word: {w}", g, L, "exact", [w[-1], w[1], w[-2]] + [c for c in w[1:]], [chr((ord(g) - 97 + d) % 26 + 97) for d in (1, -1, 2, -2, 3)] + list(string.ascii_lowercase), lambda c: len(c) == 1
    if sub == 3:
        g = w[-1]; return "last_letter", f"What is the last letter of the word: {w}", g, L, "exact", [w[0], w[-2], w[1]] + [c for c in w[:-1]], [chr((ord(g) - 97 + d) % 26 + 97) for d in (1, -1, 2, -2, 3)] + list(string.ascii_lowercase), lambda c: len(c) == 1
    return "length", f"How many letters are in the word: {w}", str(L), L, "exact", [L + d for d in (1, -1, 2, -2, 3, -3) if L + d > 0], [c for c in range(1, 16)], lambda c: True


def g_arithmetic(rng, ctx):
    sub = ctx["i"] % 5; d = rng.randint(2, 6)
    def num(k): return rng.randint(10 ** (k - 1), 10 ** k - 1)
    a, b = num(d), num(rng.randint(2, max(2, d)))
    if sub == 0: g = a + b; return "add", f"Compute: {a} + {b}", str(g), d, "exact", [], mut_num(g), lambda c: len(c.lstrip("-")) == len(str(abs(g)))
    if sub == 1: g = a - b; return "sub", f"Compute: {a} - {b}", str(g), d, "exact", [], mut_num(g), lambda c: len(c.lstrip("-")) == len(str(abs(g)))
    if sub == 2:
        a, b = num(rng.randint(2, 4)), num(rng.randint(1, 3)); g = a * b
        return "mul", f"Compute: {a} * {b}", str(g), len(str(a)) + len(str(b)), "exact", [], mut_num(g), lambda c: len(c) == len(str(g))
    if sub == 3:
        b = num(rng.randint(1, 3)); q, r = a // b, a % b
        pool = [(q + 1, r), (q - 1, r), (q, r + 1), (q, r - 1), (r, q), (q + 1, r + 1), (q - 1, r - 1), (q + 10, r), (q, r + 10)]
        return "divmod", f"Divide {a} by {b}. Give the quotient and the remainder as 'quotient remainder'.", f"{q} {r}", d, "exact", [f"{x} {y}" for x, y in pool if x >= 0 and y >= 0], [f"{x} {y}" for x in mut_num(q)[:6] for y in (r,)], lambda c: True
    b = num(rng.randint(1, 3)); g = a % b
    return "mod", f"What is {a} mod {b}?", str(g), d, "exact", [str(x) for x in (g + 1, g - 1, a // b % b, b - g, g + 2, g - 2) if x >= 0], mut_num(g) + list(range(0, 12)), lambda c: True


def g_string_ops(rng, ctx):
    sub = ctx["i"] % 5; pool = ctx["pool"]
    if sub == 0:
        w = pick_word(rng, pool); c = rng.choice(w) if rng.random() < 0.8 else rng.choice(string.ascii_lowercase); g = w.count(c)
        return "count_letter", f'How many times does the letter "{c}" appear in the word: {w}', str(g), len(w), "exact", [g + 1, g - 1, g + 2, g - 2, len(w)], list(range(0, 8)), lambda x: True
    if sub == 1:
        w = pick_word(rng, pool); g = "".join(sorted(w)); return "sort_letters", f"Sort the letters of the word alphabetically: {w}", g, len(w), "exact", [w, w[::-1], "".join(sorted(w, reverse=True))], mut_str(g), lambda x: len(x) == len(w)
    if sub == 2:
        k = rng.randint(4, 9); ws = [rng.choice(pool) for _ in range(k)]; n = rng.randint(1, k); g = ws[n - 1]
        return "nth_word", f"What is word number {n} in this sentence: {' '.join(ws)}", g, k, "exact", [x for x in ws if x != g], mut_str(g), lambda x: True
    if sub == 3:
        w = pick_word(rng, pool); sh = lambda s: "".join(chr((ord(ch) - 97 + s) % 26 + 97) for ch in w); g = sh(13)
        return "rot13", f"Apply ROT13 to the word: {w}", g, len(w), "exact", [w, sh(12), sh(14), sh(1), sh(25)], mut_str(g), lambda x: len(x) == len(w)
    k = rng.randint(2, 5); ws = [rng.choice(pool) for _ in range(k)]; s = " ".join(ws); g = s.upper()
    return "uppercase", f"Convert to uppercase: {s}", g, k, "exact", [s, s.title(), s.capitalize(), s.swapcase(), g.lower()], mut_str(g), lambda x: len(x) == len(g)


def g_list_ops(rng, ctx):
    sub = ctx["i"] % 6; k = rng.randint(4, 10); xs = [rng.randint(0, 99) for _ in range(k)]; s = "[" + ", ".join(map(str, xs)) + "]"
    fmt = lambda v: "[" + ", ".join(map(str, v)) + "]"
    def listmut(v):
        out = [v[:i] + v[i + 1:] for i in range(len(v))] + [v[:i + 1] + v[i:] for i in range(len(v))] + [v[::-1]]
        for i in range(len(v) - 1):
            if v[i] != v[i + 1]: out.append(v[:i] + [v[i + 1], v[i]] + v[i + 2:])
        for i in range(len(v)): out += [v[:i] + [v[i] + 1] + v[i + 1:], v[:i] + [max(0, v[i] - 1)] + v[i + 1:]]
        return [fmt(o) for o in out if o]
    if sub == 0: g = sorted(xs); return "sort_asc", f"Sort this list in ascending order: {s}", fmt(g), k, "exact", [s, fmt(g[::-1])], listmut(g), lambda c: True
    if sub == 1: g = max(xs); return "max", f"What is the largest number in this list: {s}", str(g), k, "exact", [str(x) for x in xs if x != g], mut_num(g), lambda c: True
    if sub == 2: g = min(xs); return "min", f"What is the smallest number in this list: {s}", str(g), k, "exact", [str(x) for x in xs if x != g], mut_num(g), lambda c: True
    if sub == 3: g = sum(xs); return "sum", f"What is the sum of the numbers in this list: {s}", str(g), k, "exact", [str(x) for x in (g + 1, g - 1, g + 10, g - 10, sum(xs[1:]), sum(xs[:-1]), max(xs) * k)], mut_num(g), lambda c: len(c) == len(str(g))
    if sub == 4: g = sorted(set(xs)); return "dedupe_sorted", f"Remove duplicates from this list and sort it ascending: {s}", fmt(g), k, "exact", [fmt(sorted(xs)), fmt(list(dict.fromkeys(xs)))], listmut(g), lambda c: True
    g = len(set(xs)); return "count_distinct", f"How many different numbers are in this list: {s}", str(g), k, "exact", [str(x) for x in (g + 1, g - 1, k, g + 2, g - 2) if x > 0], list(range(1, 13)), lambda c: True


def run_py(prog):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): exec(compile(prog, "<probe>", "exec"), {"__name__": "__probe__"})
    return buf.getvalue().strip()


def g_python_trace(rng, ctx):
    sub = ctx["i"] % 5; pool = ctx["pool"]
    if sub == 0:
        a = rng.randint(0, 9); b = a + rng.randint(4, 60); st = rng.randint(1, 6); m = rng.randint(1, 9); prog = f"print(sum(i * {m} for i in range({a}, {b}, {st})))"; kind = "loop_sum"
    elif sub == 1:
        w = pick_word(rng, pool, 0.4); i = rng.randint(0, 2); j = rng.randint(i + 1, len(w)); prog = f's = "{w}"; print(s[{i}:{j}][::-1].upper())'; kind = "slice"
    elif sub == 2:
        xs = [rng.randint(1, 30) for _ in range(rng.randint(5, 9))]; k = rng.randint(2, 4); prog = f"xs = {xs}; print(sum(x * x for x in xs if x % {k} == 0))"; kind = "comprehension"
    elif sub == 3:
        a, b, n = rng.randint(2, 9), rng.randint(1, 20), rng.randint(1, 60); prog = f"f = lambda n: n * {a} + {b}; print(f(f({n})))"; kind = "function"
    else:
        n = rng.randint(3, 9999); prog = f"c = lambda n: 0 if n == 1 else 1 + c(n // 2 if n % 2 == 0 else 3 * n + 1); print(c({n}))"; kind = "recursion"
    out = run_py(prog)
    gen = mut_num(int(out)) if re.fullmatch(r"-?\d+", out) else mut_str(out)
    return kind, f"What does this Python program print? {prog}", out, len(prog), "python-stdout", [], gen, (lambda c: len(c) == len(out))


TYPES = [("word_transform", g_word_transform), ("arithmetic", g_arithmetic), ("string_ops", g_string_ops), ("list_ops", g_list_ops), ("python_trace", g_python_trace)]


def generate(vocab, n_train, n_test):
    pools = {"train": [w for w in vocab if split_of_word(w) == "train"], "test": [w for w in vocab if split_of_word(w) == "test"]}
    seen = set(); rows = {"train": [], "test": []}
    for split, n in (("test", n_test), ("train", n_train)):       # test first: its prompts are never displaced by train
        for tname, fn in TYPES:
            seed = f"{GEN_VERSION}:{tname}:{split}"; rng = random.Random(seed); got = 0; i = 0; tries = 0
            while got < n:
                tries += 1
                if tries > n * 50: raise RuntimeError(f"cannot produce {n} unique {tname} {split} prompts")
                sub, prompt, ans, diff, chk, hints, generic, same = fn(rng, {"i": i, "pool": pools[split]})
                i += 1
                if prompt in seen or "\n" in prompt or not ans or ans != ans.strip() or "\n" in ans: continue
                try: dis = finish(ans, hints, generic, rng, same)
                except ValueError: continue
                seen.add(prompt); got += 1
                cs = f"{seed}:{got}"; cands = dis + [ans]; random.Random(cs).shuffle(cands)
                rows[split].append({"id": f"{tname}-{split}-{got:05d}", "type": tname, "subtype": sub, "prompt": prompt, "answer": ans, "candidates": cands, "candidate_seed": cs, "check": chk, "seed": seed, "generator_version": GEN_VERSION, "split": split, "difficulty": diff})
    return rows


def write_jsonl(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=BASE + "/probes/v1"); ap.add_argument("--train", type=int, default=5000); ap.add_argument("--test", type=int, default=2000); ap.add_argument("--no-freeze", action="store_true")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    tp, sp, vp = a.out + "/train.jsonl", a.out + "/test.jsonl", a.out + "/vocab.json"
    if os.path.exists(sp) and not os.access(sp, os.W_OK): print("test.jsonl is frozen; refusing to overwrite", sp); return 2
    if os.path.exists(vp): vocab = json.load(open(vp, encoding="utf-8"))["words"]
    else:
        vocab = build_vocab(); json.dump({"source": VOCAB_SRC.replace(BASE, "<lane>"), "docs": VOCAB_DOCS, "min_count": VOCAB_MIN, "n": len(vocab), "words": vocab}, open(vp, "w", encoding="utf-8"))
    rows = generate(vocab, a.train, a.test)
    write_jsonl(tp, rows["train"]); write_jsonl(sp, rows["test"])
    cnt = collections.Counter((r["split"], r["type"], r["subtype"]) for s in rows.values() for r in s)
    fz = {"generator_version": GEN_VERSION, "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "generator_sha256": sha_file(__file__), "vocab_sha256": sha_file(vp), "train_sha256": sha_file(tp), "test_sha256": sha_file(sp),
          "test_sha256_sorted_rows": hashlib.sha256("\n".join(sorted(open(sp, encoding="utf-8").read().splitlines())).encode("utf-8")).hexdigest(),
          "n_train": len(rows["train"]), "n_test": len(rows["test"]), "prompt_layout": LAYOUT, "counts": {f"{s}/{t}/{u}": n for (s, t, u), n in sorted(cnt.items())}, "model_outputs_seen_before_freeze": False}
    if not a.no_freeze:
        json.dump(fz, open(a.out + "/FREEZE.json", "w", encoding="utf-8"), indent=1); os.chmod(sp, stat.S_IREAD)
    print(json.dumps({k: fz[k] for k in ("generator_version", "train_sha256", "test_sha256", "n_train", "n_test", "vocab_sha256")}, indent=1))


if __name__ == "__main__": sys.exit(main() or 0)
