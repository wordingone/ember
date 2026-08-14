#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""lean_fetch.py -- deterministic disjoint-partition connector CLI for
Lean/GitHub formal-math repos (master corpus table fetch_filter for domain A
train-1 and domain G train-2, both of which point at the same underlying
source, hoskinson-center/proofnet, MIT -- with the constraint, relayed by the
research lead, that these two slots must select DISJOINT content sets
deterministically; neither may silently pull identical bytes to the other).

    lean_fetch.py REPO_ID [--ref REF] --partition-count K --partition-index I
                 [--budget-bytes N] [--dest DIR]
                 [--license STR --license-evidence STR] [--allow-unverified-license]
                 [--github-token TOKEN]

Stdlib-only (urllib.request). Resolves --ref (default: the repo's default
branch) to a pinned commit SHA via the GitHub API, enumerates the full
recursive file tree at that commit, sorts it into one canonical manifest
order (blob `path`, ascending -- directory entries are excluded), then
partitions that manifest by index: file i belongs to partition
`i % partition_count`. Two calls against the same repo/ref with the same
--partition-count and different --partition-index are therefore guaranteed
disjoint (every file belongs to exactly one partition) and, together, cover
every file in the tree -- the "manifest-order split" named in the master
table's fetch_filter legend. This was chosen over a content hash-bucket
because it needs no extra hashing pass over file contents and is trivially
auditable from the two receipts' recorded partition parameters alone
(reviewer just checks partition_index differs and partition_count matches).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

import receipt as rcpt

CONNECTOR_NAME = "lean_fetch"
API_ROOT = "https://api.github.com"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Deterministic disjoint-partition fetch of a Lean/GitHub repo's file tree."
    )
    p.add_argument("repo_id", help="GitHub repo id, e.g. hoskinson-center/proofnet")
    p.add_argument("--ref", default=None, help="branch/tag/sha to resolve and pin (default: repo's default branch)")
    p.add_argument(
        "--partition-count", type=int, default=1, metavar="K",
        help="number of disjoint partitions the tree's manifest is split into (default 1: no partition)",
    )
    p.add_argument(
        "--partition-index", type=int, default=0, metavar="I",
        help="0-based partition to fetch this invocation (must be < --partition-count)",
    )
    p.add_argument(
        "--budget-bytes", type=int, default=None, metavar="N",
        help="optional byte budget; stops once the next file's declared tree size would exceed it",
    )
    p.add_argument(
        "--dest", default=None,
        help="local destination dir (default: ./corpus-downloads/lean/<safe repo_id>-p<I>-of-<K>)",
    )
    p.add_argument("--license", dest="license_str", default=None, metavar="STR")
    p.add_argument("--license-evidence", dest="license_evidence", default=None, metavar="STR")
    p.add_argument("--github-token", default=None, help="optional token for authenticated (higher rate-limit) API calls")
    p.add_argument("--allow-unverified-license", action="store_true")
    return p


def _auth_headers(token: Optional[str]) -> dict:
    headers = {"User-Agent": "ember-corpus-connector/1", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_get(url: str, token: Optional[str], opener) -> dict:
    request = urllib.request.Request(url, headers=_auth_headers(token))
    urlopen = opener or urllib.request.urlopen
    with urlopen(request, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_ref(repo_id: str, ref: Optional[str], token: Optional[str], opener) -> str:
    if ref is None:
        info = _api_get(f"{API_ROOT}/repos/{repo_id}", token, opener)
        ref = info.get("default_branch") or "main"
    commit = _api_get(f"{API_ROOT}/repos/{repo_id}/commits/{urllib.parse.quote(ref)}", token, opener)
    sha = commit.get("sha")
    if not sha:
        raise rcpt.BlockedError(f"could not resolve ref {ref!r} for {repo_id} to a commit sha")
    return sha


def _fetch_tree(repo_id: str, sha: str, token: Optional[str], opener) -> List[dict]:
    data = _api_get(f"{API_ROOT}/repos/{repo_id}/git/trees/{sha}?recursive=1", token, opener)
    if data.get("truncated"):
        raise rcpt.BlockedError(
            f"tree for {repo_id}@{sha} was truncated by the GitHub API; partitioning over "
            f"an incomplete manifest would not be deterministic"
        )
    blobs = [item for item in data.get("tree", []) if item.get("type") == "blob"]
    return sorted(blobs, key=lambda item: item["path"])


def _validate_partition_args(partition_count: int, partition_index: int) -> None:
    if partition_count < 1:
        raise rcpt.BlockedError(f"--partition-count must be >= 1, got {partition_count}")
    if not (0 <= partition_index < partition_count):
        raise rcpt.BlockedError(
            f"--partition-index {partition_index} out of range for --partition-count {partition_count}"
        )


def _select_partition(manifest: List[dict], partition_count: int, partition_index: int) -> List[dict]:
    _validate_partition_args(partition_count, partition_index)
    return [item for i, item in enumerate(manifest) if i % partition_count == partition_index]


def _raw_url(repo_id: str, sha: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_id}/{sha}/{urllib.parse.quote(path)}"


def fetch(args: argparse.Namespace, opener=None) -> Path:
    _validate_partition_args(args.partition_count, args.partition_index)

    if (args.license_str is None) != (args.license_evidence is None):
        raise rcpt.BlockedError("--license and --license-evidence must be supplied together")
    license_str = args.license_str if args.license_str else rcpt.UNVERIFIED
    license_evidence = (
        args.license_evidence if args.license_evidence else "no --license/--license-evidence supplied by caller"
    )
    rcpt.gate_license(license_str, args.allow_unverified_license)

    sha = _resolve_ref(args.repo_id, args.ref, args.github_token, opener)
    manifest = _fetch_tree(args.repo_id, sha, args.github_token, opener)
    partition = _select_partition(manifest, args.partition_count, args.partition_index)
    if not partition:
        raise rcpt.BlockedError(
            f"partition {args.partition_index}/{args.partition_count} of {args.repo_id}@{sha} is empty "
            f"({len(manifest)} files in the full tree)"
        )

    key = f"{rcpt.safe_key(args.repo_id)}-p{args.partition_index}-of-{args.partition_count}"
    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "lean" / key
    dest_root.mkdir(parents=True, exist_ok=True)

    downloaded_paths: List[Path] = []
    fetched_notes = []
    running_total = 0
    try:
        for item in partition:
            path = item["path"]
            size_hint = int(item.get("size") or 0)
            if args.budget_bytes is not None and running_total + size_hint > args.budget_bytes:
                break
            url = _raw_url(args.repo_id, sha, path)
            dest_file = dest_root / path
            _, digest = rcpt.download_url(url, dest_file, opener=opener)
            downloaded_paths.append(dest_file)
            running_total += size_hint
            fetched_notes.append({"path": path, "sha256": digest, "declared_size_bytes": size_hint})
    except Exception:
        for p in downloaded_paths:
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
        raise

    if not downloaded_paths:
        raise rcpt.BlockedError(
            f"--budget-bytes {args.budget_bytes} left no room for any file in partition "
            f"{args.partition_index}/{args.partition_count}"
        )

    rel_paths = [p.relative_to(dest_root) for p in downloaded_paths]
    files = rcpt.build_file_entries(dest_root, rel_paths)

    receipt = rcpt.Receipt(
        source="lean-github",
        source_id=f"{args.repo_id}@{sha}#partition-{args.partition_index}-of-{args.partition_count}",
        canonical_url=f"https://github.com/{args.repo_id}/tree/{sha}",
        license=license_str,
        license_evidence=license_evidence,
        revision=sha,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=json.dumps(
            {
                "full_tree_file_count": len(manifest),
                "partition_count": args.partition_count,
                "partition_index": args.partition_index,
                "partition_selected_count": len(partition),
                "files_fetched": len(downloaded_paths),
                "budget_bytes": args.budget_bytes,
                "files": fetched_notes,
            },
            sort_keys=True,
        ),
    )
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return rcpt.run_cli(lambda: fetch(args))


if __name__ == "__main__":
    sys.exit(main())
