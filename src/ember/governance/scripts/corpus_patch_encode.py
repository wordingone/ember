# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""corpus_patch_encode.py — encode images as 48×48px patches for multimodal training.

Spec: domains/model/configs/v0-multimodal-config.json vision_embedder (patch_px=48, in_dim=6912).
Reserved vocab band: DELIM_START=32000, DELIM_END=32001 (from lock1_reserved_vocab_band).
Output format: .npy dict per pair (numpy npz-style via np.save with allow_pickle=True).
"""

import os
import sys
import numpy as np
from pathlib import Path

PATCH_PX = 48
IN_DIM = PATCH_PX * PATCH_PX * 3  # 6912
DELIM_START = 32000
DELIM_END = 32001
MAX_LONG_SIDE = 480


def encode_patches(image_path: str) -> np.ndarray:
    """Open image, tile into 48×48 patches, return (n_patches, 6912) float32.

    Resizes so longest side ≤ MAX_LONG_SIDE, then crops to patch-grid boundary.
    Normalizes pixels to [0, 1].
    """
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    scale = min(1.0, MAX_LONG_SIDE / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    w, h = img.size
    # Crop to nearest patch boundary
    w_crop = (w // PATCH_PX) * PATCH_PX
    h_crop = (h // PATCH_PX) * PATCH_PX
    if w_crop == 0 or h_crop == 0:
        # Image too small — pad to one patch
        padded = Image.new("RGB", (PATCH_PX, PATCH_PX), (0, 0, 0))
        padded.paste(img, (0, 0))
        img = padded
        w_crop, h_crop = PATCH_PX, PATCH_PX
    else:
        img = img.crop((0, 0, w_crop, h_crop))

    arr = np.asarray(img, dtype=np.float32) / 255.0  # (h_crop, w_crop, 3)
    n_y = h_crop // PATCH_PX
    n_x = w_crop // PATCH_PX
    # Reshape into patches: (n_y, n_x, PATCH_PX, PATCH_PX, 3) → (n_patches, IN_DIM)
    arr = arr.reshape(n_y, PATCH_PX, n_x, PATCH_PX, 3)
    arr = arr.transpose(0, 2, 1, 3, 4)  # (n_y, n_x, PATCH_PX, PATCH_PX, 3)
    arr = arr.reshape(-1, IN_DIM)        # (n_patches, 6912)
    return arr


def encode_pair(image_path: str, caption: str, out_path: str) -> dict:
    """Encode one image-caption pair; write .npy to out_path.

    Packs: patches (ndarray), delim_start, delim_end, caption, n_patches.
    Returns metadata dict.
    """
    patches = encode_patches(image_path)
    n_patches = patches.shape[0]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, {
        "patches": patches,
        "delim_start": DELIM_START,
        "delim_end": DELIM_END,
        "caption": caption,
        "n_patches": n_patches,
    }, allow_pickle=True)
    return {
        "image_path": image_path,
        "out_path": out_path,
        "n_patches": n_patches,
        "delim_start": DELIM_START,
        "delim_end": DELIM_END,
    }


def batch_encode(raw_dir: str = "manifests/corpus/b-multi-1/raw",
                 encoded_dir: str = "manifests/corpus/b-multi-1/encoded") -> dict:
    """Encode all <idx>.jpg + <idx>.txt pairs in raw_dir → encoded_dir/<idx>.npy."""
    raw = Path(raw_dir)
    enc = Path(encoded_dir)
    enc.mkdir(parents=True, exist_ok=True)

    pairs = sorted(raw.glob("*.jpg"))
    count = 0
    for jpg in pairs:
        txt = jpg.with_suffix(".txt")
        if not txt.exists():
            continue
        caption = txt.read_text(encoding="utf-8").strip()
        out_path = enc / (jpg.stem + ".npy")
        try:
            encode_pair(str(jpg), caption, str(out_path))
            count += 1
        except Exception as e:
            print(f"WARN encode_pair failed for {jpg}: {e}", file=sys.stderr)
        if count % 100 == 0 and count > 0:
            print(f"Encoded {count}/{len(pairs)}")

    print(f"Encoded {count} pairs -> {encoded_dir}")
    return {"pair_count": count, "shard_count": count, "encoded_dir": encoded_dir}


def _selftest():
    import tempfile
    from PIL import Image

    with tempfile.TemporaryDirectory() as d:
        # 48×48 image → 1 patch
        img = Image.new("RGB", (48, 48), color=(128, 64, 32))
        img_path = os.path.join(d, "test.jpg")
        img.save(img_path)

        patches = encode_patches(img_path)
        assert patches.shape == (1, IN_DIM), f"shape {patches.shape}, expected (1, {IN_DIM})"
        assert patches.dtype == np.float32, f"dtype {patches.dtype}"
        assert 0.0 <= patches.min() and patches.max() <= 1.0, f"range [{patches.min()}, {patches.max()}]"

        out_path = os.path.join(d, "out.npy")
        result = encode_pair(img_path, "test caption", out_path)
        assert result["delim_start"] == DELIM_START, f"delim_start {result['delim_start']}"
        assert result["delim_end"] == DELIM_END, f"delim_end {result['delim_end']}"
        assert result["n_patches"] == 1, f"n_patches {result['n_patches']}"

        # Load back and verify
        data = np.load(out_path, allow_pickle=True).item()
        assert data["n_patches"] == 1
        assert data["patches"].shape == (1, IN_DIM)
        assert data["caption"] == "test caption"

        # Verify delimiter ids don't overlap regular vocab (0..31999)
        assert DELIM_START >= 32000, "DELIM_START overlaps regular vocab"
        assert DELIM_END >= 32000, "DELIM_END overlaps regular vocab"

        # 96×48 image → 2 patches
        img2 = Image.new("RGB", (96, 48), color=(0, 128, 255))
        img2_path = os.path.join(d, "test2.jpg")
        img2.save(img2_path)
        patches2 = encode_patches(img2_path)
        assert patches2.shape == (2, IN_DIM), f"96x48 → expected 2 patches, got {patches2.shape}"

    print("SELFTEST_PASS delimiter_ok shape_ok range_ok")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--raw-dir", default="manifests/corpus/b-multi-1/raw")
    parser.add_argument("--encoded-dir", default="manifests/corpus/b-multi-1/encoded")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
    else:
        result = batch_encode(args.raw_dir, args.encoded_dir)
        print(f"DONE pair_count={result['pair_count']} encoded_dir={result['encoded_dir']}")
