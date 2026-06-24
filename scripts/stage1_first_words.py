"""stage1_first_words.py - curate infant-scale first-word image/text pairs.

Reads an existing B-MULTI-1 raw manifest and emits a small, local Stage-1
corpus with single-word captions, heldout exemplars, and receipts. This is a
curation bridge, not a claim that the source captions are already clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


STAGE1_NOUNS = [
    "car",
    "tree",
    "dog",
    "cake",
    "building",
    "cat",
    "house",
    "river",
    "road",
    "window",
    "ball",
    "boat",
    "flower",
    "hat",
    "book",
    "horse",
    "table",
    "door",
    "plant",
    "plate",
]


@dataclass(frozen=True)
class SourcePair:
    idx: int
    image_path: Path
    caption: str
    url: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tokens(text: str) -> set[str]:
    toks = set(re.findall(r"[a-z]+", text.lower()))
    toks |= {t[:-1] for t in toks if t.endswith("s") and len(t) > 3}
    return toks


def _repo_root_from_manifest(manifest: Path) -> Path:
    # .../<repo>/manifests/corpus/b-multi-1/raw/manifest.jsonl
    if len(manifest.parents) >= 4:
        return manifest.parents[3]
    return manifest.parent


def _resolve_image_path(manifest: Path, rec: dict) -> Path:
    raw_dir = manifest.parent
    repo_root = _repo_root_from_manifest(manifest)
    value = rec.get("image_path")
    if value:
        p = Path(value)
        if p.is_absolute():
            return p
        p_repo = repo_root / p
        if p_repo.exists():
            return p_repo
        p_raw = raw_dir / p
        if p_raw.exists():
            return p_raw
    idx = int(rec.get("idx", -1))
    if idx >= 0:
        return raw_dir / f"{idx:06d}.jpg"
    raise ValueError(f"record has no resolvable image path: {rec}")


def load_source_pairs(source_manifest: Path) -> list[SourcePair]:
    pairs: list[SourcePair] = []
    with source_manifest.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            caption = str(rec.get("caption", "")).strip()
            image_path = _resolve_image_path(source_manifest, rec)
            if not caption or not image_path.exists():
                continue
            pairs.append(
                SourcePair(
                    idx=int(rec.get("idx", line_no - 1)),
                    image_path=image_path,
                    caption=caption,
                    url=str(rec.get("url", "")),
                )
            )
    return pairs


def select_pairs(
    pairs: list[SourcePair],
    nouns: list[str],
    train_per_noun: int,
) -> tuple[list[dict], list[dict], dict]:
    train_rows: list[dict] = []
    holdout_rows: list[dict] = []
    summary: dict = {}

    for noun in nouns:
        matches = [p for p in pairs if noun in _tokens(p.caption)]
        matches = sorted(matches, key=lambda p: p.idx)
        if len(matches) < 2:
            summary[noun] = {"available": len(matches), "selected_train": 0, "selected_holdout": 0}
            continue

        holdout = matches[-1]
        train = matches[: min(train_per_noun, len(matches) - 1)]
        summary[noun] = {
            "available": len(matches),
            "selected_train": len(train),
            "selected_holdout": 1,
            "shortfall": len(train) < train_per_noun,
        }

        for kind, selected in (("train", train), ("holdout", [holdout])):
            for pair in selected:
                row = {
                    "noun": noun,
                    "split": kind,
                    "source_idx": pair.idx,
                    "source_image_path": str(pair.image_path),
                    "source_url": pair.url,
                    "source_caption": pair.caption,
                    "caption": noun,
                    "source_sha256": _sha256_file(pair.image_path),
                    "selection_rule": "caption-token-match; single-word target caption",
                    "manual_review_required": True,
                }
                if kind == "train":
                    train_rows.append(row)
                else:
                    holdout_rows.append(row)

    return train_rows, holdout_rows, summary


def _copy_rows(rows: list[dict], out_raw: Path) -> list[dict]:
    out_raw.mkdir(parents=True, exist_ok=True)
    emitted: list[dict] = []
    counters: dict[str, int] = {}
    for row in rows:
        noun = row["noun"]
        counters[noun] = counters.get(noun, 0) + 1
        stem = f"{noun}_{row['split']}_{counters[noun]:02d}"
        image_out = out_raw / f"{stem}.jpg"
        caption_out = out_raw / f"{stem}.txt"
        shutil.copyfile(row["source_image_path"], image_out)
        caption_out.write_text(row["caption"] + "\n", encoding="utf-8")
        out = dict(row)
        out["image_path"] = str(image_out)
        out["caption_path"] = str(caption_out)
        out["sha256"] = _sha256_file(image_out)
        emitted.append(out)
    return emitted


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def curate(args: argparse.Namespace) -> dict:
    source_manifest = Path(args.source_manifest)
    out_root = Path(args.out_root)
    receipt_dir = Path(args.receipt_dir)
    nouns = list(args.nouns or STAGE1_NOUNS)

    pairs = load_source_pairs(source_manifest)
    train_rows, holdout_rows, noun_summary = select_pairs(
        pairs, nouns=nouns, train_per_noun=args.train_per_noun
    )

    selected_nouns = sorted({r["noun"] for r in train_rows} & {r["noun"] for r in holdout_rows})
    if len(selected_nouns) < args.min_nouns:
        raise SystemExit(
            f"Stage-1 curation found {len(selected_nouns)} nouns, need {args.min_nouns}. "
            "Use a larger on-disk clean set or lower --min-nouns only for diagnostics."
        )

    if out_root.exists() and args.clean:
        shutil.rmtree(out_root)
    train_emitted = _copy_rows(train_rows, out_root / "train" / "raw")
    holdout_emitted = _copy_rows(holdout_rows, out_root / "holdout" / "raw")

    train_manifest = out_root / "train" / "manifest.jsonl"
    holdout_manifest = out_root / "holdout" / "holdout-manifest-stage1-first-words.jsonl"
    all_manifest = out_root / "manifest.jsonl"
    receipt_holdout = receipt_dir / "holdout-manifest-stage1-first-words.jsonl"

    _write_jsonl(train_manifest, train_emitted)
    _write_jsonl(holdout_manifest, holdout_emitted)
    _write_jsonl(all_manifest, train_emitted + holdout_emitted)
    _write_jsonl(receipt_holdout, holdout_emitted)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "EMBER-STAGE1-FIRST-WORDS-CURATION",
        "ts": ts,
        "source_manifest": str(source_manifest),
        "out_root": str(out_root),
        "nouns_requested": nouns,
        "nouns_selected": selected_nouns,
        "noun_count": len(selected_nouns),
        "train_pair_count": len(train_emitted),
        "holdout_pair_count": len(holdout_emitted),
        "train_manifest": str(train_manifest),
        "holdout_manifest": str(holdout_manifest),
        "receipt_holdout_manifest": str(receipt_holdout),
        "single_word_captions": True,
        "new_collection": False,
        "source": "existing on-disk B-MULTI-1 subset",
        "cc3m_bulk_deferred": True,
        "manual_review_required": True,
        "manual_review_reason": (
            "Selection is caption-token heuristic over noisy web captions; "
            "image cleanliness must be reviewed before capability claims."
        ),
        "noun_summary": noun_summary,
        "pass": len(selected_nouns) >= args.min_nouns and len(holdout_emitted) >= len(selected_nouns),
    }
    receipt_path = receipt_dir / f"stage1-first-words-curation-{ts}.json"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def _selftest() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        raw = root / "corpus-manifests" / "b-multi-1" / "raw"
        raw.mkdir(parents=True)
        manifest = raw / "manifest.jsonl"
        rows = []
        for i, caption in enumerate(
            [
                "red car",
                "blue car",
                "small dog",
                "sleepy dog",
            ]
        ):
            img = raw / f"{i:06d}.jpg"
            img.write_bytes(f"fake-jpg-{i}".encode("ascii"))
            rows.append({"idx": i, "image_path": str(img), "caption": caption, "url": f"u{i}"})
        _write_jsonl(manifest, rows)
        args = argparse.Namespace(
            source_manifest=str(manifest),
            out_root=str(root / "stage1"),
            receipt_dir=str(root / "receipts"),
            nouns=["car", "dog"],
            train_per_noun=1,
            min_nouns=2,
            clean=True,
        )
        receipt = curate(args)
        assert receipt["noun_count"] == 2, receipt
        assert receipt["train_pair_count"] == 2, receipt
        assert receipt["holdout_pair_count"] == 2, receipt
        assert Path(receipt["train_manifest"]).exists()
        assert Path(receipt["receipt_holdout_manifest"]).exists()
    print("STAGE1_FIRST_WORDS_SELFTEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate Stage-1 first-word pairs from existing local B-MULTI-1.")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--source-manifest", default="manifests/corpus/b-multi-1/raw/manifest.jsonl")
    parser.add_argument("--out-root", default="manifests/corpus/stage-1-first-words")
    parser.add_argument("--receipt-dir", default="receipts")
    parser.add_argument("--train-per-noun", type=int, default=2)
    parser.add_argument("--min-nouns", type=int, default=20)
    parser.add_argument("--clean", action="store_true", default=True)
    parser.add_argument("--nouns", nargs="*")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return

    receipt = curate(args)
    print(
        "STAGE1_FIRST_WORDS_CURATED "
        f"nouns={receipt['noun_count']} "
        f"train={receipt['train_pair_count']} "
        f"holdout={receipt['holdout_pair_count']} "
        f"receipt={receipt['receipt_path']}"
    )


if __name__ == "__main__":
    main()
