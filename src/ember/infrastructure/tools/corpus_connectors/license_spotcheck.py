#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Spot-check a random sample of a connector manifest's admitted arXiv papers
against the license shown on each paper's own live https://arxiv.org/abs/<id>
page.

Why this exists: arxiv_fetch.py's --license-override path admits a paper on
an out-of-band license claim (e.g. an OAI-PMH bulk harvest's own <license>
element) rather than the live per-paper arxiv:license Atom element, because
the live API is known-unreliable/absent for many papers. That override basis
is provenance, not proof for THIS specific paper -- an independent check
against the paper's own live page is what turns "the harvest said so" into
"we looked." Any mismatch must halt bulk admission of the checked manifest,
not be averaged away by the other 19 passing.

Reuses arxiv_fetch._urlopen_with_backoff so a spot-check run degrades the
same way the fetch itself does under arXiv's own rate limiting -- retry with
backoff, not raise straight through.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import arxiv_fetch  # noqa: E402

ABS_LICENSE_RE = re.compile(r'class="abs-license"><a href="([^"]+)"')


def fetch_abs_license(arxiv_id: str, opener=None, timeout: int = 30) -> Optional[str]:
    """Return the license URL shown in the abs page's own license block, or
    None if the page carries none (e.g. arXiv's default non-exclusive
    license, which renders no abs-license block at all)."""
    urlopen = opener or arxiv_fetch.urllib.request.urlopen
    url = f"https://arxiv.org/abs/{arxiv_id}"
    req = arxiv_fetch.urllib.request.Request(url, headers={"User-Agent": "ember-corpus-connector/1"})
    with arxiv_fetch._urlopen_with_backoff(req, urlopen, timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    match = ABS_LICENSE_RE.search(html)
    return match.group(1) if match else None


def sample_ids(manifest: dict, sample_size: int, seed: int) -> list[str]:
    ids = [Path(entry["path"]).stem for entry in manifest["files"]]
    rng = random.Random(seed)
    return rng.sample(ids, min(sample_size, len(ids)))


def run_spot_check(
    manifest_path: Path,
    sample_size: int = 20,
    seed: Optional[int] = None,
    expected_license: str = "http://creativecommons.org/licenses/by/4.0/",
    opener=None,
    sleep_seconds: float = 3.0,
    sleeper=None,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Deterministic-but-not-hand-picked: derive the sample seed from the
    # manifest's own content hash unless the caller pins one explicitly, so
    # a rerun against the SAME manifest reproduces the SAME sample without
    # anyone choosing which 20 papers get checked.
    if seed is None:
        seed = int(manifest["sha256_manifest"][:8], 16)
    sleep_fn = sleeper or time.sleep

    ids = sample_ids(manifest, sample_size, seed)
    results = []
    for i, arxiv_id in enumerate(ids):
        try:
            live_license = fetch_abs_license(arxiv_id, opener=opener)
            error = None
        except Exception as exc:  # noqa: BLE001 -- any failure is a check failure, not a crash
            live_license = None
            error = f"{type(exc).__name__}: {exc}"
        match = error is None and live_license == expected_license
        results.append({
            "arxiv_id": arxiv_id,
            "live_license": live_license,
            "error": error,
            "match": match,
        })
        if i < len(ids) - 1:
            sleep_fn(sleep_seconds)

    return {
        "schema": "arxiv-license-spotcheck-v1",
        "manifest_checked": str(manifest_path),
        "manifest_sha256_manifest": manifest.get("sha256_manifest"),
        "sample_size": len(ids),
        "seed": seed,
        "expected_license": expected_license,
        "results": results,
        "all_match": all(r["match"] for r in results),
        "checked_at": arxiv_fetch.rcpt.utc_now_iso(),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", required=True, type=Path, help="connector receipt manifest json to sample from")
    p.add_argument("--sample-size", type=int, default=20)
    p.add_argument("--seed", type=int, default=None, help="defaults to a value derived from the manifest's own sha256_manifest")
    p.add_argument("--expected-license", default="http://creativecommons.org/licenses/by/4.0/")
    p.add_argument("--out", type=Path, default=None, help="write the spot-check receipt here; defaults next to --manifest")
    p.add_argument("--sleep-seconds", type=float, default=3.0)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report = run_spot_check(
        args.manifest,
        sample_size=args.sample_size,
        seed=args.seed,
        expected_license=args.expected_license,
        sleep_seconds=args.sleep_seconds,
    )
    out_path = args.out
    if out_path is None:
        stamp = arxiv_fetch.rcpt.utc_stamp_compact()
        out_path = args.manifest.parent / f"{stamp}-{args.manifest.stem}.spotcheck.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"SPOTCHECK_{'PASS' if report['all_match'] else 'FAIL'} wrote={out_path}")
    return 0 if report["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
