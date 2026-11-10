# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for probe_gen.py: deterministic, train/test disjoint, one-line prompts and gold (evaluator layout), 8 distinct candidates incl. gold, every answer independently recomputed from its prompt
(python_trace re-run in a clean subprocess), a wrong answer is caught, and a frozen test split cannot be overwritten.
Run: python scripts/tests/probe_gen_red_test.py"""
import os, sys, json, re, subprocess, tempfile, shutil, stat, random, codecs
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import probe_gen as P
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


def verify_row(r):
    """independent recomputation from the prompt text (a second implementation, not the generator's)"""
    p, a, s = r["prompt"], r["answer"], r["subtype"]
    if r["type"] == "word_transform":
        w = p.split(": ", 1)[1]
        exp = {"capitalize": w[:1].upper() + w[1:], "reverse": "".join(w[len(w) - 1 - i] for i in range(len(w))), "first_letter": w[0], "last_letter": w[-1], "length": str(sum(1 for _ in w))}[s]
    elif r["type"] == "arithmetic":
        nums = [int(x) for x in re.findall(r"-?\d+", p)]
        x, y = nums[0], nums[1]
        exp = {"add": str(x + y), "sub": str(x - y), "mul": str(x * y), "divmod": f"{x // y} {x % y}", "mod": str(x % y)}[s]
    elif r["type"] == "string_ops":
        if s == "count_letter":
            c = re.search(r'letter "(.)"', p).group(1); w = p.split("word: ")[1]; exp = str(len([1 for ch in w if ch == c]))
        elif s == "sort_letters": exp = "".join(sorted(p.split("alphabetically: ")[1]))
        elif s == "nth_word":
            n = int(re.search(r"word number (\d+)", p).group(1)); exp = p.split("sentence: ")[1].split(" ")[n - 1]
        elif s == "rot13": exp = codecs.encode(p.split("word: ")[1], "rot13")
        else: exp = p.split("uppercase: ")[1].upper()
    elif r["type"] == "list_ops":
        xs = json.loads(re.search(r"\[.*\]", p).group(0))
        exp = {"sort_asc": json.dumps(sorted(xs)), "max": str(max(xs)), "min": str(min(xs)), "sum": str(sum(xs)), "dedupe_sorted": json.dumps(sorted(set(xs))), "count_distinct": str(len(set(xs)))}[s]
    else:
        prog = p.split("print? ", 1)[1]
        exp = subprocess.run([sys.executable, "-I", "-c", prog], capture_output=True, text=True, timeout=30).stdout.strip()
    return exp == a


vocab = P.build_vocab()
chk("GREEN the vocabulary is built from local text (>= 5000 words)", len(vocab) >= 5000)
r1 = P.generate(vocab, 60, 40); r2 = P.generate(vocab, 60, 40)
chk("GREEN generation is deterministic (same rows twice)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
tr, te = r1["train"], r1["test"]
chk("GREEN counts: 60 per type train-side, 40 per type test", len(tr) == 300 and len(te) == 200 and all(sum(1 for r in te if r["type"] == t) == 40 for t, _ in P.TYPES))
chk("GREEN word_transform is the first type in the files", tr[0]["type"] == "word_transform" and te[0]["type"] == "word_transform")
chk("GREEN no prompt appears in both splits or twice", not ({r["prompt"] for r in tr} & {r["prompt"] for r in te}) and len({r["prompt"] for r in tr + te}) == len(tr) + len(te))
allr = tr + te
chk("GREEN layout: prompt has no newline; gold is one non-empty line with no leading/trailing space", all("\n" not in r["prompt"] and r["answer"] and r["answer"] == r["answer"].strip() and "\n" not in r["answer"] for r in allr))
chk("GREEN 8 distinct candidates per row, gold exactly once, each one line without edge spaces", all(len(r["candidates"]) == 8 and len(set(r["candidates"])) == 8 and r["candidates"].count(r["answer"]) == 1 and all(c == c.strip() and c and "\n" not in c for c in r["candidates"]) for r in allr))
pos = {r["candidates"].index(r["answer"]) for r in allr}
chk("GREEN gold sits at every position 0..7 across rows (order is shuffled, not fixed)", pos == set(range(8)))
chk("GREEN every row has its own candidate_seed", len({r["candidate_seed"] for r in allr}) == len(allr))
vs = set(vocab)
def target(r): return r["prompt"].split("word: ", 1)[1]
wt = lambda rows: [r for r in rows if r["type"] == "word_transform"]
chk("GREEN a dictionary word used in a test prompt is never a train-split word, and the reverse", all(P.split_of_word(target(r)) == "test" for r in wt(te) if target(r) in vs) and all(P.split_of_word(target(r)) == "train" for r in wt(tr) if target(r) in vs))
bad = [r["id"] for r in allr if not verify_row(r)]
chk("GREEN every answer matches an independent recomputation (%d rows)" % len(allr), not bad)
w = dict(tr[3]); w["answer"] = w["answer"] + "x"
chk("RED a wrong answer is caught by the independent check", not verify_row(w))
d = tempfile.mkdtemp()
sys.argv = ["probe_gen.py", "--out", d, "--train", "30", "--test", "20"]
rc = P.main()
sp = d + "/test.jsonl"; fz = json.load(open(d + "/FREEZE.json"))
chk("GREEN FREEZE.json sha256 matches the written files", fz["test_sha256"] == P.sha_file(sp) and fz["train_sha256"] == P.sha_file(d + "/train.jsonl") and fz["model_outputs_seen_before_freeze"] is False)
chk("GREEN the frozen test split is read-only", not os.access(sp, os.W_OK))
before = P.sha_file(sp); rc2 = P.main()
chk("RED a second run refuses to overwrite the frozen test split and leaves it unchanged", rc2 == 2 and P.sha_file(sp) == before)
os.chmod(sp, stat.S_IWRITE); shutil.rmtree(d, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
