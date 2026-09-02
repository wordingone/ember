#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Evidence-bound candidate classification for open Ember work.

This produces review candidates, never title-only authority. A row with an
empty or insufficient body remains TRIAGE_REQUIRED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


KIND_SIGNALS: dict[str, tuple[str, ...]] = {
    "kind:experiment": (
        "pre-registration",
        "prereg",
        "treatment",
        "control arm",
        "matched control",
        "ablation",
        "run count",
        "kill criteria",
        "frozen protocol",
    ),
    "kind:defect": (
        " defect",
        "observed behavior",
        "expected behavior",
        "reproduc",
        "crash",
        "segfault",
        "access_violation",
        "broken",
        "fails",
        "failure",
        "missing",
        "invisible",
        "corrupt",
        "wrong",
        "no-op",
    ),
    "kind:research": (
        "research question",
        "hypothesis",
        "competing explanation",
        "prior art",
        "falsifi",
        "uncertainty",
        "mechanism question",
    ),
    "kind:governance": (
        "governance",
        "authority",
        "operator directive",
        "operator mandate",
        "constitutional",
        "retention law",
        "policy",
    ),
    "kind:maintenance": (
        "maintenance",
        "cleanup",
        "hygiene",
        "retire",
        "retention",
        "consolidat",
        "migration",
        "inventory",
    ),
    "kind:documentation": (
        "documentation",
        "docs/",
        "reader",
        "readme",
        "runbook",
    ),
    "kind:enhancement": (
        "existing behavior",
        "baseline",
        "success metric",
        "reduce latency",
        "performance regression",
        "improve",
        "optimization",
    ),
    "kind:feature": (
        "new capability",
        "user journey",
        "implement",
        "add ",
        "tool surface",
        "no such",
    ),
    "kind:engineering": (
        "engineering",
        "interface",
        "invariant",
        "runner",
        "wiring",
        "integration",
        "harden",
        "contract",
        "preflight",
    ),
}
AREA_SIGNALS: dict[str, tuple[str, ...]] = {
    "area:model": ("model", "parameter", "decoder", "architecture", "expert"),
    "area:tokenizer": ("tokenizer", "token", "decode", "vocab"),
    "area:data": ("corpus", "dataset", "shard", "contamination", "heldout", "data "),
    "area:training": ("training", "pretrain", "optimizer.step", "gradient", "grow rung"),
    "area:optimization": ("optimizer", "lr ", "learning rate", "throughput", "offload"),
    "area:evaluation": ("evaluation", " eval", "benchmark", "metric", "held-out"),
    "area:checkpoint": ("checkpoint", "model.pt", "save", "load policy"),
    "area:provenance": ("custody", "provenance", "lineage", "receipt", "identity"),
    "area:inference": ("inference", "serving", "openai-compatible", "generate"),
    "area:agent": ("agent", "goal organ", "autonom", "self-improvement", "loop"),
    "area:tools": ("tool call", "tool use", "tool surface"),
    "area:ember-lab": ("ember" + "d", "ember-lab"),
    "area:runtime": ("runtime", "process", "daemon", "watchdog", "memory", "resource"),
    "area:cli": ("ember-cli", "command", "slash", "conpty"),
    "area:cockpit": ("cockpit", "tui", "render", "flame", "window", "telemetry"),
    "area:installation": ("install", "uninstall", "setup"),
    "area:packaging": ("package", "binary distribution", "wheel"),
    "area:ci": ("github actions", "workflow", "ci ", "required check"),
    "area:release": ("release", "publish", "hugging face", " hf "),
    "area:docs": ("documentation", "docs/", "readme", "runbook"),
    "area:security": ("security", "secret", "credential", "attack", "untrusted"),
    "area:governance": ("governance", "authority", "policy", "constitution", "goal.md"),
}


def _signals(text: str, mapping: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    lowered = text.lower()
    return {
        label: [needle for needle in needles if needle in lowered]
        for label, needles in mapping.items()
        if any(needle in lowered for needle in needles)
    }


def classify(item: dict[str, Any]) -> dict[str, Any]:
    body = item.get("body") or ""
    comments = "\n".join(row.get("body") or "" for row in item.get("comments", []))
    if len(body.strip()) < 80:
        return {
            "number": item["number"],
            "review_status": "TRIAGE_REQUIRED",
            "reason": "body is insufficient; title-only inference is forbidden",
            "body_sha256": digest_text(body),
            "comments_sha256": digest_text(comments),
        }
    evidence_text = body + "\n" + comments
    kind_hits = _signals(evidence_text, KIND_SIGNALS)
    if "roadmap:parent" in item.get("labels", []):
        kind = "kind:initiative"
        kind_basis = ["existing roadmap:parent plus full roadmap body"]
    else:
        scores = {label: len(hits) for label, hits in kind_hits.items()}
        # Pre-registration is an execution contract even when it discusses
        # falsifiers; explicit experiment signals outrank generic defect words.
        if kind_hits.get("kind:experiment"):
            scores["kind:experiment"] = scores.get("kind:experiment", 0) + 5
        kind = max(scores, key=scores.get) if scores else "kind:engineering"
        kind_basis = kind_hits.get(kind, ["full body defaults to engineering obligation"])

    area_hits = _signals(evidence_text, AREA_SIGNALS)
    ranked = sorted(
        area_hits,
        key=lambda label: (-len(area_hits[label]), label),
    )
    areas = ranked[:3] or ["area:governance"]

    latest = (comments[-2000:] if comments else body[-2000:]).lower()
    if re.search(r"\b(blocked|held|waiting on|cannot progress)\b", latest):
        state = "state:blocked"
    elif re.search(r"\b(awaits review|under review|review required)\b", latest):
        state = "state:review"
    elif kind == "kind:initiative":
        state = "state:in-progress"
    else:
        state = "state:ready"

    milestone = item.get("milestone") or ""
    all_text = (item.get("title", "") + "\n" + evidence_text).lower()
    if re.search(r"\bp0\b|data loss|custody corruption|unsafe resource", all_text):
        priority = "priority:p0"
    elif (
        "EMBER-02" in milestone
        or re.search(r"\bp1\b|blocks? the current|operator workflow", all_text)
    ):
        priority = "priority:p1"
    elif kind in {"kind:documentation", "kind:maintenance"}:
        priority = "priority:p3"
    else:
        priority = "priority:p2"

    labels = [kind, *areas, state, priority]
    if kind == "kind:defect":
        if re.search(r"data loss|security|custody|corrupt|unsafe", all_text):
            labels.append("severity:s0")
        elif re.search(r"crash|false operator|invisible|blocks? core|segfault", all_text):
            labels.append("severity:s1")
        elif re.search(r"jitter|art|polish|layout", all_text):
            labels.append("severity:s3")
        else:
            labels.append("severity:s2")
    return {
        "number": item["number"],
        "review_status": "MACHINE_CANDIDATE",
        "labels": labels,
        "primary_milestone": item.get("milestone"),
        "basis": {
            "body_sha256": digest_text(body),
            "comments_sha256": digest_text(comments),
            "existing_labels": item.get("labels", []),
            "kind_signals": kind_basis,
            "area_signals": {key: area_hits[key] for key in areas},
            "title_used_only_with_body": True,
        },
    }


def build(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = [classify(item) for item in snapshot["open_items"]]
    result = {
        "schema_version": "ember-open-work-classification/v1",
        "repository": snapshot["repository"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "rows": rows,
        "claim_boundary": (
            "candidate metadata only; no issue closure, scientific, training, "
            "model-capability, or acceptance-completion claim"
        ),
    }
    result["classification_sha256"] = hashlib.sha256(canonical_bytes(result)).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8", errors="strict"))
    result = build(snapshot)
    args.output.write_bytes(canonical_bytes(result) + b"\n")
    counts: dict[str, int] = {}
    for row in result["rows"]:
        status = row["review_status"]
        counts[status] = counts.get(status, 0) + 1
    print(json.dumps({"status": "PASS", "counts": counts, "sha256": result["classification_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
