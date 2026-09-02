# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""corpus_acquire_multimodal.py — download CC0/permissive image-text pairs.

Source: Conceptual Captions 3M (CC3M) TSV — public, permissive-licensed captions.
Images downloaded from original URLs; some may 404 (normal for CC3M).
"""

import os
import sys
import json
import requests
from pathlib import Path


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ember-corpus-builder/0.1)"}
TIMEOUT = 10


def _load_cc3m_lines(n: int) -> list[tuple[str, str]]:
    """Fetch up to n*3 (url, caption) pairs from CC3M via HuggingFace datasets.

    Google Cloud Storage TSV (gcc-data bucket) returns 403 as of 2026.
    HF datasets mirror: google-research-datasets/conceptual_captions.
    """
    from datasets import load_dataset
    ds = load_dataset(
        "google-research-datasets/conceptual_captions",
        "unlabeled",
        split="train",
        streaming=True,
    )
    pairs = []
    for row in ds:
        url = row.get("image_url", "").strip()
        caption = row.get("caption", "").strip()
        if url and caption:
            pairs.append((url, caption))
        if len(pairs) >= n * 3:  # over-fetch because many URLs 404
            break
    return pairs


def fetch_urls(n: int = 1000, output_dir: str = "manifests/corpus/b-multi-1/raw") -> list[dict]:
    """Download at least n CC0/permissive image-text pairs.

    Each pair: image saved to output_dir/<idx>.jpg, caption to output_dir/<idx>.txt.
    Returns list of {idx, image_path, caption_path, url, caption}.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Fetching CC3M TSV (need {n} pairs)...")
    candidates = _load_cc3m_lines(n)

    results = []
    tried = 0
    for url, caption in candidates:
        if len(results) >= n:
            break
        tried += 1
        idx = len(results)
        img_path = out / f"{idx:06d}.jpg"
        cap_path = out / f"{idx:06d}.txt"
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200 or "image" not in r.headers.get("content-type", ""):
                continue
            img_path.write_bytes(r.content)
            cap_path.write_text(caption, encoding="utf-8")
            results.append({
                "idx": idx,
                "image_path": str(img_path),
                "caption_path": str(cap_path),
                "url": url,
                "caption": caption,
            })
        except Exception:
            continue
        if len(results) % 100 == 0 and len(results) > 0:
            print(f"Downloaded {len(results)}/{n}")

    # Write manifest
    manifest_path = out / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"Downloaded {len(results)}/{n} (tried {tried} URLs)")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--output-dir", default="manifests/corpus/b-multi-1/raw")
    args = parser.parse_args()
    pairs = fetch_urls(args.n, args.output_dir)
    print(f"DONE pair_count={len(pairs)}")
