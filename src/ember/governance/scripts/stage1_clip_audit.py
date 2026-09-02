# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CLIP-assisted Stage-1 first-words curriculum audit.

This is a curation/control instrument, not an Ember capability claim. It uses a
local cached CLIP model to score whether an on-disk image is visually closer to
its intended Stage-1 noun than to the other Stage-1 nouns, then emits filtered
manifests and an audit receipt.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_NOUNS = [
    "car", "tree", "dog", "cake", "building", "cat", "house", "river",
    "road", "window", "ball", "boat", "flower", "hat", "book", "horse",
    "table", "door", "plant", "plate",
]


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def _rank_rows(rows: list[dict], nouns: list[str], score_rows: list[list[float]]) -> list[dict]:
    out: list[dict] = []
    for row, scores in zip(rows, score_rows):
        noun = str(row.get("noun") or row.get("caption", "")).strip()
        ranked = sorted(range(len(nouns)), key=lambda i: scores[i], reverse=True)
        target_idx = nouns.index(noun) if noun in nouns else -1
        target_rank = ranked.index(target_idx) + 1 if target_idx >= 0 else None
        best_idx = ranked[0]
        audited = dict(row)
        audited["clip_audit"] = {
            "model": "RN50",
            "prompt": "a photo of a {noun}",
            "target_noun": noun,
            "target_rank": target_rank,
            "target_score": round(float(scores[target_idx]), 6) if target_idx >= 0 else None,
            "top_noun": nouns[best_idx],
            "top_score": round(float(scores[best_idx]), 6),
            "top3": [
                {"noun": nouns[i], "score": round(float(scores[i]), 6)}
                for i in ranked[:3]
            ],
        }
        out.append(audited)
    return out


def _filter_rows(rows: list[dict], max_rank: int) -> list[dict]:
    return [
        row for row in rows
        if row.get("clip_audit", {}).get("target_rank") is not None
        and int(row["clip_audit"]["target_rank"]) <= max_rank
    ]


def _summarize(rows: list[dict], nouns: list[str]) -> dict:
    by_noun: dict[str, dict] = {
        noun: {"total": 0, "top1": 0, "top3": 0, "kept": 0}
        for noun in nouns
    }
    for row in rows:
        noun = str(row.get("noun") or row.get("caption", ""))
        rank = row.get("clip_audit", {}).get("target_rank")
        if noun not in by_noun:
            continue
        by_noun[noun]["total"] += 1
        if rank == 1:
            by_noun[noun]["top1"] += 1
        if rank is not None and rank <= 3:
            by_noun[noun]["top3"] += 1
        if row.get("clip_keep"):
            by_noun[noun]["kept"] += 1
    return by_noun


def _row_source_idx(row: dict) -> int:
    try:
        return int(row.get("source_idx", -1))
    except (TypeError, ValueError):
        return -1


def _qualified_by_rank(row: dict, max_rank: int) -> bool:
    rank = row.get("clip_audit", {}).get("target_rank")
    return rank is not None and int(rank) <= max_rank


def _resplit_rows(
    audited_rows: list[dict],
    nouns: list[str],
    max_rank: int,
    min_train_per_noun: int,
) -> tuple[list[dict], list[dict], dict]:
    """Create a deterministic train/heldout split from already-audited rows.

    The heldout choice is the highest source_idx among qualifying rows, not the
    easiest CLIP score. CLIP is used only as a cleanliness filter.
    """
    train_rows: list[dict] = []
    holdout_rows: list[dict] = []
    by_noun: dict[str, dict] = {}
    skipped: dict[str, dict] = {}

    for noun in nouns:
        noun_rows = [
            row for row in audited_rows
            if str(row.get("noun") or row.get("caption", "")).strip() == noun
        ]
        qualified = [row for row in noun_rows if _qualified_by_rank(row, max_rank)]
        qualified = sorted(qualified, key=lambda row: (_row_source_idx(row), str(row.get("image_path", ""))))
        needed = min_train_per_noun + 1
        by_noun[noun] = {
            "available": len(noun_rows),
            "qualified": len(qualified),
            "selected_train": 0,
            "selected_holdout": 0,
        }
        if len(qualified) < needed:
            skipped[noun] = {
                "reason": "insufficient_qualified_rows",
                "available": len(noun_rows),
                "qualified": len(qualified),
                "needed": needed,
            }
            continue

        holdout = qualified[-1]
        train = qualified[:-1]
        by_noun[noun]["selected_train"] = len(train)
        by_noun[noun]["selected_holdout"] = 1

        for split, rows in (("train", train), ("holdout", [holdout])):
            for row in rows:
                emitted = dict(row)
                prior_rule = str(emitted.get("selection_rule", "")).strip()
                emitted["resplit_source_split"] = emitted.get("split")
                emitted["split"] = split
                emitted["caption"] = noun
                emitted["noun"] = noun
                emitted["clip_keep"] = True
                emitted["selection_rule"] = (
                    (prior_rule + "; ") if prior_rule else ""
                ) + (
                    f"clip-rank-resplit max_rank={max_rank}; "
                    "heldout=highest-source-idx-among-qualified"
                )
                if split == "train":
                    train_rows.append(emitted)
                else:
                    holdout_rows.append(emitted)

    selected_nouns = sorted({row["noun"] for row in train_rows} & {row["noun"] for row in holdout_rows})
    summary = {
        "selected_nouns": selected_nouns,
        "noun_count": len(selected_nouns),
        "by_noun": by_noun,
        "skipped": skipped,
        "heldout_selection_rule": "highest-source-idx-among-qualified",
    }
    return train_rows, holdout_rows, summary


def _score_with_clip(rows: list[dict], nouns: list[str], model_name: str, device: str, batch_size: int) -> list[list[float]]:
    import torch
    from PIL import Image
    import clip

    model, preprocess = clip.load(
        model_name,
        device=device,
        download_root=str(Path.home() / ".cache" / "clip"),
    )
    model.eval()
    prompts = [f"a photo of a {noun}" for noun in nouns]
    text = clip.tokenize(prompts).to(device)
    with torch.no_grad():
        text_features = model.encode_text(text)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    scores: list[list[float]] = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            images = []
            for row in batch:
                image_path = row.get("image_path") or row.get("source_image_path")
                image = Image.open(image_path).convert("RGB")
                images.append(preprocess(image))
            image_tensor = torch.stack(images).to(device)
            image_features = model.encode_image(image_tensor)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            logits = image_features @ text_features.T
            scores.extend(logits.detach().cpu().float().tolist())
    return scores


def audit(args: argparse.Namespace) -> dict:
    nouns = list(args.nouns or DEFAULT_NOUNS)
    train_rows = _read_jsonl(Path(args.train_manifest))
    holdout_rows = _read_jsonl(Path(args.holdout_manifest))
    rows = train_rows + holdout_rows

    device = args.device
    if device == "auto":
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"

    scores = _score_with_clip(rows, nouns, args.model, device, args.batch_size)
    audited = _rank_rows(rows, nouns, scores)
    kept = _filter_rows(audited, args.max_rank)
    kept_ids = {id(row) for row in kept}
    for row in audited:
        row["clip_keep"] = id(row) in kept_ids

    n_train = len(train_rows)
    audited_train = audited[:n_train]
    audited_holdout = audited[n_train:]
    kept_train = [row for row in audited_train if row["clip_keep"]]
    kept_holdout = [row for row in audited_holdout if row["clip_keep"]]

    out_root = Path(args.out_root)
    receipt_dir = Path(args.receipt_dir)
    train_out = out_root / "train" / "manifest.jsonl"
    holdout_out = out_root / "holdout" / "holdout-manifest-stage1-first-words.jsonl"
    audit_out = out_root / "clip-audit.jsonl"
    _write_jsonl(train_out, kept_train)
    _write_jsonl(holdout_out, kept_holdout)
    _write_jsonl(audit_out, audited)

    selected_nouns_train = {row["noun"] for row in kept_train}
    selected_nouns_holdout = {row["noun"] for row in kept_holdout}
    selected_nouns = sorted(selected_nouns_train & selected_nouns_holdout)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "EMBER-STAGE1-CLIP-AUDIT",
        "ts": ts,
        "model": args.model,
        "device": device,
        "train_manifest": str(args.train_manifest),
        "holdout_manifest": str(args.holdout_manifest),
        "out_root": str(out_root),
        "filtered_train_manifest": str(train_out),
        "filtered_holdout_manifest": str(holdout_out),
        "audit_jsonl": str(audit_out),
        "nouns": nouns,
        "max_rank": args.max_rank,
        "train_total": len(audited_train),
        "holdout_total": len(audited_holdout),
        "train_kept": len(kept_train),
        "holdout_kept": len(kept_holdout),
        "noun_count_train_and_holdout": len(selected_nouns),
        "nouns_train_and_holdout": selected_nouns,
        "by_noun_train": _summarize(audited_train, nouns),
        "by_noun_holdout": _summarize(audited_holdout, nouns),
        "pass": len(selected_nouns) >= args.min_nouns,
        "claim_boundary": (
            "CLIP audit is a curriculum cleanliness control only; it is not "
            "counted as Ember model capability evidence."
        ),
    }
    receipt_path = receipt_dir / f"stage1-clip-audit-{ts}.json"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def resplit(args: argparse.Namespace) -> dict:
    nouns = list(args.nouns or DEFAULT_NOUNS)
    audited_rows = _read_jsonl(Path(args.resplit_from_audit))
    train_rows, holdout_rows, summary = _resplit_rows(
        audited_rows,
        nouns=nouns,
        max_rank=args.max_rank,
        min_train_per_noun=args.min_train_per_noun,
    )

    out_root = Path(args.out_root)
    receipt_dir = Path(args.receipt_dir)
    train_out = out_root / "train" / "manifest.jsonl"
    holdout_out = out_root / "holdout" / "holdout-manifest-stage1-first-words.jsonl"
    all_out = out_root / "manifest.jsonl"
    _write_jsonl(train_out, train_rows)
    _write_jsonl(holdout_out, holdout_rows)
    _write_jsonl(all_out, train_rows + holdout_rows)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "EMBER-STAGE1-CLIP-RESPLIT",
        "ts": ts,
        "source_audit_jsonl": str(args.resplit_from_audit),
        "out_root": str(out_root),
        "train_manifest": str(train_out),
        "holdout_manifest": str(holdout_out),
        "all_manifest": str(all_out),
        "nouns": nouns,
        "max_rank": args.max_rank,
        "min_train_per_noun": args.min_train_per_noun,
        "train_pair_count": len(train_rows),
        "holdout_pair_count": len(holdout_rows),
        "noun_count": summary["noun_count"],
        "nouns_selected": summary["selected_nouns"],
        "by_noun": summary["by_noun"],
        "skipped": summary["skipped"],
        "heldout_selection_rule": summary["heldout_selection_rule"],
        "pass": summary["noun_count"] >= args.min_nouns,
        "claim_boundary": (
            "CLIP resplit is a curriculum cleanliness control only; it is not "
            "counted as Ember model capability evidence."
        ),
    }
    receipt_path = receipt_dir / f"stage1-clip-resplit-{ts}.json"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def _selftest() -> None:
    rows = [
        {"noun": "car", "caption": "car", "image_path": "car.jpg"},
        {"noun": "dog", "caption": "dog", "image_path": "dog.jpg"},
    ]
    nouns = ["car", "dog", "tree"]
    ranked = _rank_rows(rows, nouns, [[0.9, 0.1, 0.0], [0.2, 0.7, 0.1]])
    assert ranked[0]["clip_audit"]["target_rank"] == 1
    assert ranked[1]["clip_audit"]["target_rank"] == 1
    kept = _filter_rows(ranked, max_rank=1)
    assert len(kept) == 2
    for row in ranked:
        row["clip_keep"] = row in kept
    summary = _summarize(ranked, nouns)
    assert summary["car"]["top1"] == 1
    assert summary["dog"]["kept"] == 1
    audited_for_resplit = [
        {
            "noun": "car",
            "caption": "car",
            "image_path": "car0.jpg",
            "source_idx": 0,
            "clip_audit": {"target_rank": 1, "target_score": 0.91},
        },
        {
            "noun": "car",
            "caption": "car",
            "image_path": "car2.jpg",
            "source_idx": 2,
            "clip_audit": {"target_rank": 1, "target_score": 0.87},
        },
        {
            "noun": "dog",
            "caption": "dog",
            "image_path": "dog0.jpg",
            "source_idx": 10,
            "clip_audit": {"target_rank": 1, "target_score": 0.88},
        },
        {
            "noun": "road",
            "caption": "road",
            "image_path": "road0.jpg",
            "source_idx": 20,
            "clip_audit": {"target_rank": 2, "target_score": 0.55},
        },
        {
            "noun": "road",
            "caption": "road",
            "image_path": "road1.jpg",
            "source_idx": 21,
            "clip_audit": {"target_rank": 1, "target_score": 0.61},
        },
    ]
    train_rows, holdout_rows, resplit_summary = _resplit_rows(
        audited_for_resplit,
        nouns=["car", "dog", "road"],
        max_rank=1,
        min_train_per_noun=1,
    )
    assert [row["source_idx"] for row in holdout_rows] == [2], holdout_rows
    assert [row["source_idx"] for row in train_rows] == [0], train_rows
    assert resplit_summary["selected_nouns"] == ["car"], resplit_summary
    assert resplit_summary["skipped"]["dog"]["reason"] == "insufficient_qualified_rows"
    assert resplit_summary["skipped"]["road"]["qualified"] == 1
    print("STAGE1_CLIP_AUDIT_SELFTEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description="CLIP-audit Stage-1 first-word manifests.")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--resplit-from-audit")
    parser.add_argument("--train-manifest")
    parser.add_argument("--holdout-manifest")
    parser.add_argument("--out-root")
    parser.add_argument("--receipt-dir", default="receipts")
    parser.add_argument("--model", default="RN50")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-rank", type=int, default=1)
    parser.add_argument("--min-train-per-noun", type=int, default=1)
    parser.add_argument("--min-nouns", type=int, default=10)
    parser.add_argument("--nouns", nargs="*")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return
    if args.resplit_from_audit:
        if not args.out_root:
            raise SystemExit("--out-root is required with --resplit-from-audit")
        receipt = resplit(args)
        print(
            "STAGE1_CLIP_RESPLIT_DONE "
            f"nouns={receipt['noun_count']} "
            f"train={receipt['train_pair_count']} "
            f"holdout={receipt['holdout_pair_count']} "
            f"pass={receipt['pass']} "
            f"receipt={receipt['receipt_path']}"
        )
        return
    for name in ("train_manifest", "holdout_manifest", "out_root"):
        if not getattr(args, name):
            raise SystemExit(f"--{name.replace('_', '-')} is required")
    receipt = audit(args)
    print(
        "STAGE1_CLIP_AUDIT_DONE "
        f"train_kept={receipt['train_kept']}/{receipt['train_total']} "
        f"holdout_kept={receipt['holdout_kept']}/{receipt['holdout_total']} "
        f"nouns={receipt['noun_count_train_and_holdout']} "
        f"receipt={receipt['receipt_path']}"
    )


if __name__ == "__main__":
    main()
