# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for pack_media spec v2 (A24, mail 83214): python scripts/tests/pack_media_v2_red_test.py   (CPU only, tiny synthetic inputs, temp dir on A:)
Proves, with Ember's REAL decoder (ember-restart-3b/batch.py decode_owned_packed_batch), that v2 shards feed the projector inputs and v1 shards do not:
 a) image v2: 48x48x3 patches (6,912 B per unit), grid <= 6 wide/4+ high from short side 192, a too-small image is a listed failure, text_token_ids + tokenizer sha in the index
 b) audio v2: whole 640-sample frames (1,280 B), 22.05 kHz input resampled to 16 kHz, a too-short clip is a listed failure, topology key = frame count
 c) records built from the index rows (marker tokens + exact-cover span + base64 bytes) pass decode_owned_packed_batch: image_patches [2,16,48,48,3], audio_frames [2,25,640]
 d) the decoded tensor equals the stored bytes (first patch / first frame round trip)
 e) a pack mixing two topologies (4x4 and 4x5 grids) is refused by the decoder -> the topology key must bucket packs
 f) MUTANT: spec v1 shards (16x16 patches, 320-sample frames) put through the same builder are refused by the decoder (wrong byte lengths)
NOT proven here: the loss/target convention on marker positions and the span attention mode (A24, training): this red uses a placeholder shifted target."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import M_ROOT
import os, sys, json, base64, hashlib, subprocess, tempfile, shutil, wave, struct, math, importlib.util
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); PM = os.path.join(os.path.dirname(HERE), "pack_media.py")
BATCH = (M_ROOT + "/ember/src/ember/infrastructure/tools/ember-restart-3b/batch.py")
TOKP = (M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json")
res = []
def chk(name, cond):
    res.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)

import torch
sp = importlib.util.spec_from_file_location("ember_batch_under_test", BATCH); B = importlib.util.module_from_spec(sp); sys.modules["ember_batch_under_test"] = B; sp.loader.exec_module(B)
from src.ember.model.ember_v0_model import RestartDecoderConfig
CFG = RestartDecoderConfig(hidden_size=64, layers=1, attention_heads=2, vocab_size=32000)

tmp = tempfile.mkdtemp(prefix="pmv2_", dir="A:/data-scan" if os.path.isdir("A:/data-scan") else None)
def img(name, w, h, seed):
    from PIL import Image
    rng = np.random.default_rng(seed); a = rng.integers(0, 256, (h, w, 3), dtype=np.uint8); p = os.path.join(tmp, name); Image.fromarray(a).save(p); return p
def wav(name, sec, sr):
    p = os.path.join(tmp, name)
    with wave.open(p, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr)
        f.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / sr))) for i in range(int(sec * sr))))
    return p
def run(mode, name, rows, spec):
    man = os.path.join(tmp, name + ".jsonl"); open(man, "w").write("".join(json.dumps(r) + "\n" for r in rows))
    env = dict(os.environ); env["PACK_MEDIA_SPEC"] = spec
    r = subprocess.run([sys.executable, PM, mode, os.path.join(tmp, "out-" + spec), name, man], capture_output=True, text=True, env=env)
    if r.returncode: print(r.stderr[-400:])
    d = os.path.join(tmp, "out-" + spec, name)
    return [json.loads(l) for l in open(d + "/index.jsonl", encoding="utf-8")], json.load(open(d + "/receipt.json")), d

def rec_for(idx_row, d, kind):
    raw = open(os.path.join(d, idx_row["shard"]), "rb").read()[idx_row["offset_bytes"]: idx_row["offset_bytes"] + idx_row["length_bytes"]]
    n, ub = idx_row["n_units"], idx_row["unit_bytes"]; units = [raw[i * ub:(i + 1) * ub] for i in range(n)]
    ids = idx_row["text_token_ids"]; marker = CFG.image_token_id if kind == "image" else CFG.audio_token_id
    tok = [marker] * n + ids; rec = dict(schema_version="ember-owned-bootstrap-batch-v1", token_ids=tok, target_ids=tok[1:] + [0],
        multimodal_spans=[dict(start=0, length=n, modality=kind, attention_mode="bidirectional")], active_expert="vision" if kind == "image" else "audio")
    if kind == "image":
        wp = idx_row["w_patches"]; rec["image_patches_u8_base64"] = [base64.b64encode(u).decode() for u in units]; rec["image_coordinates"] = [[i % wp, i // wp] for i in range(n)]
    else:
        rec["audio_frames_i16le_base64"] = [base64.b64encode(u).decode() for u in units]; rec["image_coordinates"] = []
    return rec, units

def decodes(recs):
    try: B.decode_owned_packed_batch(recs, CFG, device=torch.device("cpu"), expected_records=len(recs)); return True, ""
    except ValueError as e: return False, str(e)

try:
    lic = dict(licence="test", origin="synthetic", fetch_date="2026-11-11")
    # --- image
    imgs = [dict(path=img("a.png", 300, 300, 1), caption="a red barn", **lic), dict(path=img("b.png", 320, 320, 2), caption="two dogs", **lic),
            dict(path=img("c.png", 380, 300, 3), caption="wide shot", **lic), dict(path=img("d.png", 30, 30, 4), caption="tiny", **lic), dict(path=img("e.png", 1000, 300, 5), caption="panorama", **lic)]
    ix, rc, d = run("image", "imgv2", imgs, "v2"); by = {os.path.basename(r["src_path"]): r for r in ix}
    chk("a1) v2 image: unit_bytes 6912, length == n_units*6912 for every object", all(r["unit_bytes"] == 6912 and r["length_bytes"] == r["n_units"] * 6912 for r in ix) and len(ix) == 4)
    chk("a2) grids from short side 192: 300x300 -> 4x4, 380x300 -> 4x5, 1000x300 capped at 6 wide (4x6)", (by["a.png"]["h_patches"], by["a.png"]["w_patches"]) == (4, 4) and (by["c.png"]["h_patches"], by["c.png"]["w_patches"]) == (4, 5) and by["e.png"]["w_patches"] == 6 and by["e.png"]["topology"] == "g4x6")
    chk("a3) the too-small image is a listed failure, spec v2 in the receipt, topology_counts present", any("too small" in f["why"] for f in rc["failures"]) and rc["spec"] == "v2" and rc["topology_counts"].get("g4x4") == 2)
    tsha = hashlib.sha256(open(TOKP, "rb").read()).hexdigest()
    chk("a4) every row carries text_token_ids (ints < vocab) and the tokenizer sha", all(r["text_token_ids"] and all(isinstance(t, int) and 0 <= t < 32000 for t in r["text_token_ids"]) and r["tokenizer_sha256"] == tsha for r in ix))
    ra, ua = rec_for(by["a.png"], d, "image"); rb, _ = rec_for(by["b.png"], d, "image"); rc_, _ = rec_for(by["c.png"], d, "image")
    ok, why = decodes([ra, rb]); chk("c1) two 4x4 image records pass decode_owned_packed_batch " + why[:60], ok)
    out = B.decode_owned_packed_batch([ra, rb], CFG, device=torch.device("cpu"), expected_records=2)
    chk("c2) image_patches shape [2,16,48,48,3]", tuple(out["image_patches"].shape) == (2, 16, 48, 48, 3))
    chk("d1) first decoded patch equals the stored bytes", out["image_patches"][0, 0].flatten().to(torch.uint8).tolist() == list(ua[0]))
    ok, why = decodes([ra, rc_]); chk("e) a pack mixing 4x4 and 4x5 is refused (the topology key must bucket packs): " + why[:70], not ok)
    # --- audio
    auds = [dict(path=wav("s1.wav", 1.0, 16000), transcript="hello there", **lic), dict(path=wav("s2.wav", 1.0, 22050), transcript="good morning", **lic), dict(path=wav("s3.wav", 0.01, 16000), transcript="x", **lic)]
    ax, rca, da = run("audio", "audv2", auds, "v2"); ab = {os.path.basename(r["src_path"]): r for r in ax}
    chk("b1) v2 audio: unit_bytes 1280, 25 frames for 1.0 s at 16 kHz and after resampling 22.05 kHz, topology f25", all(r["unit_bytes"] == 1280 and r["n_units"] == 25 and r["topology"] == "f25" for r in ax) and len(ax) == 2)
    chk("b1b) every audio row records samples_trimmed (int, < 640 = < 40 ms), never silent", all(isinstance(r.get("samples_trimmed"), int) and 0 <= r["samples_trimmed"] < 640 for r in ax))
    chk("b2) the too-short clip is a listed failure", any("too short" in f["why"] for f in rca["failures"]))
    r1, u1 = rec_for(ab["s1.wav"], da, "audio"); r2, _ = rec_for(ab["s2.wav"], da, "audio")
    ok, why = decodes([r1, r2]); chk("c3) two 25-frame audio records pass decode_owned_packed_batch " + why[:60], ok)
    out = B.decode_owned_packed_batch([r1, r2], CFG, device=torch.device("cpu"), expected_records=2)
    chk("c4) audio_frames shape [2,25,640]", tuple(out["audio_frames"].shape) == (2, 25, 640))
    exp0 = np.frombuffer(u1[0], dtype="<i2").astype(np.float32) / 32768.0
    chk("d2) first decoded audio frame equals the stored int16 / 32768", np.allclose(out["audio_frames"][0, 0].numpy(), exp0))
    # --- mutant: spec v1 shards through the same builder are refused
    i1, _, d1 = run("image", "imgv1", imgs[:1], "v1"); r1row = dict(i1[0]); r1row["text_token_ids"] = [5, 6]
    rv1, _ = rec_for(r1row, d1, "image")
    ok, why = decodes([rv1, rv1]); chk("f1) MUTANT v1 image shards (16x16 patches) are refused by the decoder: " + why[:70], not ok)
    a1, _, da1 = run("audio", "audv1", auds[:1], "v1"); a1row = dict(a1[0]); a1row["text_token_ids"] = [5, 6]
    rav1, _ = rec_for(a1row, da1, "audio")
    ok, why = decodes([rav1, rav1]); chk("f2) MUTANT v1 audio shards (320-sample frames) are refused by the decoder: " + why[:70], not ok)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
bad = [n for n, c in res if not c]
print("FAILCOUNT", len(bad), "of", len(res)); print("ALL PASS" if not bad else "FAILED"); sys.exit(1 if bad else 0)
