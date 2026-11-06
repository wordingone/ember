# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Compose the next hour's shard ledger for `ember-lab resume`.

Inputs: the trained ledger (the chain the parent consumed), the trained end (the parent's data cursor), and the
PASS intake dirs (each holds ledger.jsonl + shards/ and a C1/C2 PASS receipt). Output: the trained rows unchanged,
then up to `--add-tokens` of intake rows, interleaved deterministically across intakes:
  - inside an intake, rows are ordered by sha256(row_sha256 || seed);
  - across intakes, the next row comes from the intake furthest behind its share of the remaining tokens
    (the share is proportional to each intake's remaining tokens; ties go to the smaller key);
  - every appended row is re-indexed, re-chained (prev_row_sha256 / row_sha256) and given its running token_start;
  - its shard is hard-linked into the shards root under its own name (a name already there must have equal bytes).
Writes the composed ledger and composition.json (tokens per intake, seed, input shas). Stdlib only, CPU only.

  python -I resume_compose.py --trained LEDGER --trained-end N --intake DIR [--intake DIR ...] --seed S
         --add-tokens N --shards-root DIR --out DIR [--check-only]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

GENESIS_PREV = "0" * 64
SCHEMA = "ember-catalog-train-shard-ledger-v1"


def row_sha(row: dict) -> str:
    body = {k: v for k, v in row.items() if k != "row_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_rows(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def key(row: dict, seed: str) -> str:
    return hashlib.sha256((row["row_sha256"] + seed).encode("ascii")).hexdigest()


def interleave(sources: dict[str, list[dict]], seed: str, add_tokens: int) -> list[tuple[str, dict]]:
    queues = {n: sorted(rows, key=lambda r: key(r, seed)) for n, rows in sources.items()}
    total = {n: sum(r["n_tokens"] for r in rows) for n, rows in queues.items()}
    taken = {n: 0 for n in queues}
    pos = {n: 0 for n in queues}
    out, budget = [], add_tokens
    while True:
        live = [n for n in queues if pos[n] < len(queues[n]) and queues[n][pos[n]]["n_tokens"] <= budget]
        if not live:
            return out
        n = min(live, key=lambda s: (taken[s] / total[s], key(queues[s][pos[s]], seed)))
        r = queues[n][pos[n]]
        pos[n] += 1
        taken[n] += r["n_tokens"]
        budget -= r["n_tokens"]
        out.append((n, r))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trained", required=True, type=Path)
    ap.add_argument("--trained-end", required=True, type=int)
    ap.add_argument("--intake", action="append", required=True, type=Path)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--add-tokens", required=True, type=int)
    ap.add_argument("--shards-root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args(argv)
    trained = read_rows(a.trained)
    prev, running = GENESIS_PREV, 0
    for i, r in enumerate(trained):
        if r.get("index") != i or r.get("prev_row_sha256") != prev or r.get("row_sha256") != row_sha(r):
            raise SystemExit(f"REFUSE trained ledger chain broken at row {i}")
        prev, running = r["row_sha256"], running + r["n_tokens"]
    if running < a.trained_end:
        raise SystemExit(f"REFUSE trained ledger ends at {running} < trained end {a.trained_end}")
    # The parent's cursor must lie inside the last trained row (the stream resumes mid-row); a ledger that runs
    # whole rows past the cursor carries rows the parent never read, which resume must not inherit unchecked.
    if not running - trained[-1]["n_tokens"] <= a.trained_end <= running:
        raise SystemExit(f"REFUSE parent cursor {a.trained_end} is not inside the last trained row [{running - trained[-1]['n_tokens']}, {running}]")
    sources, shard_dir = {}, {}
    for d in a.intake:
        name = d.name
        if name in sources:
            raise SystemExit(f"REFUSE duplicate intake {name}")
        sources[name] = read_rows(d / "ledger.jsonl")
        shard_dir[name] = d / "shards"
    seen = {r["name"] for r in trained}
    for n, rows in sources.items():
        for r in rows:
            if r["name"] in seen:
                raise SystemExit(f"REFUSE shard {r['name']} from {n} already in the ledger")
            seen.add(r["name"])
    picked = interleave(sources, a.seed, a.add_tokens)
    composed = list(trained)
    per = {n: {"rows": 0, "tokens": 0} for n in sources}
    for n, r in picked:
        src = shard_dir[n] / r["name"]
        if src.stat().st_size != r["n_tokens"] * 2:
            raise SystemExit(f"REFUSE {src} size does not match n_tokens")
        row = {k: v for k, v in r.items() if k not in ("row_sha256", "prev_row_sha256", "index", "token_start")}
        row.update(index=len(composed), prev_row_sha256=prev, token_start=running, schema_version=SCHEMA)
        row["row_sha256"] = row_sha(row)
        prev, running = row["row_sha256"], running + row["n_tokens"]
        composed.append(row)
        per[n]["rows"] += 1
        per[n]["tokens"] += row["n_tokens"]
        if not a.check_only:
            dst = a.shards_root / r["name"]
            if dst.exists():
                if dst.stat().st_size != src.stat().st_size or file_sha(dst) != file_sha(src):
                    raise SystemExit(f"REFUSE {dst} exists with different bytes")
            else:
                os.link(src, dst)
    added = sum(v["tokens"] for v in per.values())
    a.out.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for r in composed).encode("utf-8")
    ledger_sha = hashlib.sha256(body).hexdigest()
    comp = {"schema": "ember-resume-composition-v1", "seed": a.seed, "trained_ledger_sha256": file_sha(a.trained),
            "trained_end": a.trained_end, "added_tokens": added, "requested_tokens": a.add_tokens, "per_intake": per,
            "intake_ledger_sha256": {n: file_sha(d / "ledger.jsonl") for n, d in zip(sources, a.intake)},
            "composed_ledger_sha256": ledger_sha, "composed_rows": len(composed), "check_only": a.check_only}
    if not a.check_only:
        (a.out / "composed-ledger.jsonl").write_bytes(body)
    (a.out / "composition.json").write_text(json.dumps(comp, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: comp[k] for k in ("added_tokens", "composed_rows", "composed_ledger_sha256", "per_intake")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
