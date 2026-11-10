# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build the pack_media AUDIO manifest from MLS-English TRAIN parquet files (dev/test are eval-only and never read here).
Usage: mls_manifest.py IN1.parquet [...] --out OUTDIR  -> OUTDIR/audio/<n>.<ext> + manifest.jsonl + stats.json
Rules: file name must start with 'train-' (dev/test refused, hard); duration 1..40 s; transcript >= 3 words; heldout-sentence hit on the transcript (>=8 words) dropped; 
duplicate (speaker_id, book_id, begin_time) dropped. PROVENANCE FLAG: MLS transcripts are produced by the MLS pipeline (ASR + alignment to the LibriVox book text) = model-derived text;
each row carries transcript_origin so the per-hour declaration can name it. Audio is human speech (LibriVox volunteers, public domain / CC-BY 4.0 MLS release). Selftest: mls_manifest.py selftest"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, re, json, time, collections
IDX = None
def heldout_hit(t):
    global IDX
    import numpy as np, xxhash
    if IDX is None: IDX = [np.load(p, mmap_mode="r") for p in ((LANE_ROOT + "/heldout-index-full/heldout-sent-xxh64-full.npy"), (LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy")) if os.path.exists(p)]
    for s in re.split(r"(?<=[.!?])\s+|\n+", t):
        n = re.sub(r"\s+", " ", s.lower()).strip()
        if n.count(" ") >= 7:
            h = xxhash.xxh64_intdigest(n)
            for a in IDX:
                i = int(np.searchsorted(a, h))
                if i < len(a) and int(a[i]) == h: return True
    return False
def row_ok(r, st):
    d = r.get("audio_duration") or 0
    if not (1.0 <= d <= 40.0): st["duration"] += 1; return False
    t = (r.get("transcript") or "").strip()
    if len(t.split()) < 3: st["short_text"] += 1; return False
    return True
def main(files, out, spk_state=None, cap_s=None):
    import pyarrow.parquet as pq
    spk = json.load(open(spk_state)) if spk_state and os.path.exists(spk_state) else {}
    for f in files:
        if not os.path.basename(f).startswith("train-"): raise SystemExit("REFUSED: %s is not a train split (dev/test are eval-only)" % f)
    os.makedirs(out + "/audio", exist_ok=True); st = collections.Counter(); seen = set(); today = time.strftime("%Y-%m-%d"); n = 0
    with open(out + "/manifest.jsonl", "w", encoding="utf-8") as mf:
        for f in files:
            pf = pq.ParquetFile(f)
            for b in pf.iter_batches(batch_size=64):
                for r in b.to_pylist():
                    st["rows"] += 1
                    if not row_ok(r, st): continue
                    k = (r["speaker_id"], r["book_id"], r["begin_time"])
                    if k in seen: st["dup"] += 1; continue
                    if cap_s and spk.get(r["speaker_id"], 0) >= cap_s: st["speaker_cap"] += 1; continue
                    seen.add(k); t = r["transcript"].strip()
                    if heldout_hit(t): st["heldout_hit"] += 1; continue
                    a = r["audio"]; ext = os.path.splitext(a.get("path") or "")[1] or ".flac"; p = f"{out}/audio/{os.path.basename(f)[:-8]}-{n:07d}{ext}"; open(p, "wb").write(a["bytes"]); n += 1
                    mf.write(json.dumps(dict(path=p, transcript=t, transcript_origin="Multilingual LibriSpeech (Pratap et al. 2020), CC BY 4.0; transcripts produced by the MLS ASR+alignment pipeline (model-derived, declared)", speaker_id=r["speaker_id"], book_id=r["book_id"], seconds=r["audio_duration"],
                        licence="CC-BY-4.0 (MLS) over LibriVox public-domain recordings", origin="huggingface.co/datasets/facebook/multilingual_librispeech (english) via ember-raw-private audio/mls-eng", fetch_date=today, content_date_max="2020-12-31", modality="audio-text"), ensure_ascii=False) + "\n"); st["kept"] += 1; st["seconds"] += int(r["audio_duration"]); spk[r["speaker_id"]] = spk.get(r["speaker_id"], 0) + r["audio_duration"]
    if spk_state: json.dump(spk, open(spk_state, "w"))
    json.dump(dict(st), open(out + "/stats.json", "w")); print(dict(st))
def selftest():
    ok = True
    def chk(n, c):
        nonlocal ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)
    s = collections.Counter(); chk("good row kept", row_ok(dict(audio_duration=12.0, transcript="the quick brown fox"), s))
    chk("too long refused", not row_ok(dict(audio_duration=55.0, transcript="the quick brown fox"), s))
    try: main(["x/test-00000-of-00001.parquet"], (LANE_ROOT + "/scratch/_mlsself")); chk("test split refused", False)
    except SystemExit as e: chk("RED: test split refused", "not a train split" in str(e))
    try: main(["x/dev-00000-of-00001.parquet"], (LANE_ROOT + "/scratch/_mlsself")); chk("dev split refused", False)
    except SystemExit as e: chk("RED: dev split refused", "not a train split" in str(e))
    print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]: selftest()
    a = sys.argv[1:]; main([x for x in a if x.endswith(".parquet")], a[a.index("--out") + 1], a[a.index("--spk-state") + 1] if "--spk-state" in a else None, float(a[a.index("--cap-s") + 1]) if "--cap-s" in a else None)
