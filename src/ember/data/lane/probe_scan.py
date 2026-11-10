# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contamination scan of the frozen probe test split against pack text objects. Read-only, CPU-only (one process).
Usage: python probe_scan.py PACK_OBJECTS_DIR [--test PATH] [--max-files N] [--out JSON]
Method (one regex pass per doc, no per-segment python loop): the doc is lower-cased once; an anchor regex finds the fixed template phrase of every probe prompt
("compute:", "reverse the letters of the word", "what is N mod M", ...). At each anchor hit the rest of that line (capped at the longest prompt length) is cut at every space and with trailing
punctuation stripped, normalised (case and whitespace), and looked up in a dict of the normalised test prompts. A hit = a test prompt occurs verbatim (case/whitespace-insensitive), whole line or embedded.
For each hit it also records whether the gold answer occurs in the next 300 chars (answer-bearing). common.gram_hashes (>= 8-word segments) cannot see these short prompts, hence this scan.
The anchor list is asserted to cover every test prompt, so template drift fails loudly."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, io, re, json, glob, time, argparse, collections
import zstandard
from lane_config import LANE_ROOT as BASE
WS = re.compile(r"\s+")
norm = lambda s: WS.sub(" ", s.lower()).strip()
ANCHORS = ["apply rot13 to the word", "capitalize the first letter of the word", "compute:", "convert to uppercase", r"divide \d+ by \d+\.", "how many different numbers are in this list",
           "how many letters are in the word", "how many times does the letter", "remove duplicates from this list and sort it ascending", "reverse the letters of the word",
           "sort the letters of the word alphabetically", "sort this list in ascending order", "what does this python program print", r"what is \d+ mod \d+", "what is the first letter of the word",
           "what is the largest number in this list", "what is the last letter of the word", "what is the smallest number in this list", "what is the sum of the numbers in this list",
           r"what is word number \d+ in this sentence"]
ANCHOR_RX = re.compile("|".join("(?:%s)" % a.replace(" ", r"\s+") for a in ANCHORS))   # whitespace-tolerant: the lookup normalises runs of spaces anyway
TRAIL = ".,;:!?)]}\"' "


def candidates(line, maxlen):
    line = norm(line[:maxlen * 4 + 16])[:maxlen + 4]    # normalise first: runs of spaces would otherwise eat the length cap
    ends = [i for i, ch in enumerate(line) if ch == " "] + [len(line)]
    seen = set()
    for i in ends:
        for s in (line[:i], line[:i].rstrip(TRAIL)):
            k = s.strip()
            if k and k not in seen: seen.add(k); yield k


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("objs"); ap.add_argument("--test", default=BASE + "/probes/v1/test.jsonl"); ap.add_argument("--max-files", type=int, default=0); ap.add_argument("--out", default="")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.test, encoding="utf-8")]
    byprompt = {norm(r["prompt"]): r for r in rows}
    miss = [r["id"] for r in rows if not ANCHOR_RX.match(norm(r["prompt"]))]
    assert not miss, "anchor list does not cover %d test prompts, e.g. %s" % (len(miss), miss[:3])
    maxlen = max(len(k) for k in byprompt)
    files = sorted(glob.glob(a.objs + "/*.jsonl.zst"))
    if a.max_files: files = files[:a.max_files]
    t0 = time.time(); docs = nbytes = anchor_docs = anchor_hits = hits = ans_hits = 0; by_type = collections.Counter(); ex = []
    for fp in files:
        with open(fp, "rb") as f:
            for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
                try: t = json.loads(line)["text"]
                except Exception: continue
                docs += 1; nbytes += len(t); low = t.lower(); got = False
                for m in ANCHOR_RX.finditer(low):
                    got = True; anchor_hits += 1
                    nl = low.find("\n", m.start()); rest = low[m.start(): (nl if nl >= 0 else len(low))]
                    for k in candidates(rest, maxlen):
                        r = byprompt.get(k)
                        if r:
                            hits += 1; by_type[r["type"]] += 1
                            tail = low[m.start(): m.start() + len(rest) + 300]
                            if r["answer"].lower() in tail[len(k):]: ans_hits += 1
                            if len(ex) < 5: ex.append(r["id"])
                            break
                anchor_docs += got
        print(os.path.basename(fp), "docs", docs, "sec", int(time.time() - t0), flush=True)
    secs = time.time() - t0
    res = {"objects_dir": a.objs.replace(BASE, "<lane>"), "files": len(files), "docs": docs, "text_bytes": nbytes, "seconds": round(secs, 1), "mb_per_s": round(nbytes / 1e6 / max(secs, 1e-9), 2),
           "anchor_docs": anchor_docs, "anchor_hits": anchor_hits, "prompt_hits": hits, "prompt_hits_with_answer_within_300_chars": ans_hits, "hits_by_type": dict(by_type), "example_ids": ex, "n_test_prompts": len(byprompt)}
    print(json.dumps(res, indent=1))
    if a.out: json.dump(res, open(a.out, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__": main()
