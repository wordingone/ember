# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pack images or audio into raw deterministic train-ready shards (default spec v1, lead 81222; training may amend).
Usage: pack_media.py image|audio OUTDIR NAME MANIFEST.jsonl [DATASET_META.json]
MANIFEST rows: {path, caption|transcript_ref, licence, origin, fetch_date, ...extra kept verbatim}
IMAGE spec v1: decode with PIL, convert RGB, resize so SHORT side = 256 (BICUBIC, reducing_gap=None), center-crop LONG side to a multiple of 16
  (and at most 1024), cut into 16x16 patches row-major, each patch HWC uint8 (768 bytes), stored raw. No codec, no learned model.
AUDIO spec v1: decode with PyAV, libswresample to mono s16 16000 Hz (deterministic, no model), trim to a multiple of 320 samples (20 ms frames).
Shards: img-v1-{idx:05d}-{sha12}.bin / aud-v1-...bin, <=256 MiB each, objects never split. index.jsonl: one row per kept object. receipt.json: counts + failures.
Failures (decode errors, too small, too short) are dropped and listed in receipt.json, never silently."""
import sys, os, io, json, hashlib, struct
import numpy as np
MODE, OUT, NAME, MAN = sys.argv[1:5]
META = json.load(open(sys.argv[5])) if len(sys.argv) > 5 else {}
SHARD_BYTES = 256 << 20
os.makedirs(os.path.join(OUT, NAME), exist_ok=True)
D = os.path.join(OUT, NAME)

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()

def enc_image(p):
    from PIL import Image
    im = Image.open(p); im.load(); src = im.size
    im = im.convert("RGB"); w, h = im.size
    if min(w, h) < 16: raise ValueError("too small")
    s = 256 / min(w, h); nw, nh = max(16, round(w * s)), max(16, round(h * s))
    im = im.resize((nw, nh), Image.BICUBIC, reducing_gap=None)
    cw, ch = min(nw - nw % 16, 1024), min(nh - nh % 16, 1024)
    l, t = (nw - cw) // 2, (nh - ch) // 2
    a = np.asarray(im.crop((l, t, l + cw, t + ch)), dtype=np.uint8)
    hp, wp = ch // 16, cw // 16
    patches = a.reshape(hp, 16, wp, 16, 3).transpose(0, 2, 1, 3, 4).reshape(hp * wp, 768)
    return patches.tobytes(), dict(src_w=src[0], src_h=src[1], h_patches=hp, w_patches=wp, n_units=hp * wp, unit_bytes=768)

def enc_audio(p):
    import av
    c = av.open(p); st = c.streams.audio[0]; sr = st.rate
    rs = av.AudioResampler(format="s16", layout="mono", rate=16000); chunks = []
    for fr in c.decode(st):
        for o in rs.resample(fr): chunks.append(o.to_ndarray().reshape(-1))
    for o in rs.resample(None): chunks.append(o.to_ndarray().reshape(-1))
    c.close()
    if not chunks: raise ValueError("empty")
    pcm = np.concatenate(chunks).astype("<i2")
    n = (len(pcm) // 320) * 320
    if n < 320: raise ValueError("too short")
    return pcm[:n].tobytes(), dict(src_sr=sr, samples=n, n_units=n // 320, unit_bytes=640, seconds=round(n / 16000, 3))

enc = enc_image if MODE == "image" else enc_audio
pref = "img-v1" if MODE == "image" else "aud-v1"
rows = [json.loads(l) for l in open(MAN, encoding="utf-8")]
idx = []; fails = []; shard_i = 0; cur = bytearray(); cur_rows = []; seen = set(); shards = []
def flush():
    global cur, cur_rows, shard_i
    if not cur: return
    sh = hashlib.sha256(bytes(cur)).hexdigest()
    name = f"{pref}-{shard_i:05d}-{sh[:12]}.bin"
    with open(os.path.join(D, name), "wb") as f: f.write(cur)
    for r in cur_rows: r["shard"] = name
    idx.extend(cur_rows); shards.append(dict(name=name, bytes=len(cur), sha256=sh)); shard_i += 1; cur = bytearray(); cur_rows = []
for r in rows:
    p = r["path"]
    try:
        osha = sha256_file(p)
        if osha in seen: fails.append(dict(path=p, why="duplicate_content")); continue
        raw, meta = enc(p)
    except Exception as e:
        fails.append(dict(path=p, why=type(e).__name__ + ": " + str(e)[:120])); continue
    seen.add(osha)
    if cur and len(cur) + len(raw) > SHARD_BYTES: flush()
    row = {k: v for k, v in r.items() if k != "path"}
    row.setdefault("content_date_max", META.get("content_date_max")); row["modality"] = MODE
    row.update(meta); row.update(object_sha256=osha, src_path=p, offset_bytes=len(cur), length_bytes=len(raw), dataset_id=META.get("dataset_id"))
    cur += raw; cur_rows.append(row)
flush()
with open(os.path.join(D, "index.jsonl"), "w", encoding="utf-8") as f:
    for r in idx: f.write(json.dumps(r, ensure_ascii=False) + "\n")
rec = dict(mode=MODE, spec="v1", name=NAME, objects_in=len(rows), objects_kept=len(idx), failures=fails, shards=shards,
           units_total=sum(r["n_units"] for r in idx), index_sha256=sha256_file(os.path.join(D, "index.jsonl")))
json.dump(rec, open(os.path.join(D, "receipt.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in rec.items() if k != "failures"}), "failures:", len(fails))
