#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""github_fetch.py -- GitHub topic-search bulk connector CLI (master corpus
table fetch_filter: "Top-N repos by stars WITH verified in-set LICENSE file
per repo, deterministic order, license recorded in receipt").

    github_fetch.py TOPIC --budget-bytes N [--dest DIR]
                    [--max-candidates N] [--per-page N] [--github-token TOKEN]
                    [--allow-content-mismatch]

Stdlib-only (urllib.request). Queries the GitHub Search API
(`/search/repositories?q=topic:<TOPIC>`) for candidate repos, paginated,
then re-sorts client-side by (-stargazers_count, full_name) for full
determinism independent of the API's own tie-break behavior across pages.
Each candidate's `license` field -- GitHub's own per-repo LICENSE-file
detection, returned inline by the search API, no extra per-repo call
needed -- is checked against `spdx_gate.allowed_licenses()`, the package's
live training-admission allow-list (bound, not copied, per spdx_gate.py's
own "a fourth disagreeing copy of the allow-list is the bug this gate
exists to prevent" -- this connector holds no license identifiers of its
own); repos with no detected license, or a license outside that allow-list
(including GitHub's own "NOASSERTION" -- a LICENSE file exists but
couldn't be classified), are excluded outright, never recorded as
UNVERIFIED-and-gated -- this connector's contract is "verified in-set
only," not "record and gate on a flag" like the single-source connectors.
Eligible repos are fetched in that deterministic
order (default-branch tarball,
`https://github.com/<full_name>/archive/refs/heads/<default_branch>.tar.gz`)
until the next eligible repo's declared size would push the running total
past --budget-bytes, at which point enumeration stops -- no smaller,
lower-ranked repo is substituted in to fill the remaining budget, since that
would break rank fidelity ("top-N by stars", not "best-fit knapsack").
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

# Direct execution appends the repository root so the package import resolves
# without publishing connector-local bare names or shadowing earlier imports.
_REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from src.ember.infrastructure.tools.corpus_connectors import receipt as rcpt  # noqa: E402
import spdx_gate  # noqa: E402

CONNECTOR_NAME = "github_fetch"
API_ROOT = "https://api.github.com"
SEARCH_PER_PAGE_DEFAULT = 100
MAX_CANDIDATES_DEFAULT = 200


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="GitHub topic-search bulk fetch: top-N by stars, in-set LICENSE only, deterministic order."
    )
    p.add_argument("topic", help="GitHub topic to search, e.g. cuda, testing, debugging, bim, robotics")
    p.add_argument(
        "--budget-bytes", type=int, required=True, metavar="N",
        help="declared total byte budget; enumeration stops once the next eligible repo's "
             "declared size would push the running total past it",
    )
    p.add_argument(
        "--max-candidates", type=int, default=MAX_CANDIDATES_DEFAULT, metavar="N",
        help="how many search-API candidates to consider before giving up "
             "(GitHub search caps at 1000 results regardless)",
    )
    p.add_argument("--per-page", type=int, default=SEARCH_PER_PAGE_DEFAULT, metavar="N")
    p.add_argument("--github-token", default=None, help="optional token for authenticated (higher rate-limit) API calls")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/github/<safe topic>)")
    p.add_argument("--allow-content-mismatch", action="store_true")
    return p


def _auth_headers(token: Optional[str]) -> dict:
    headers = {
        "User-Agent": "ember-corpus-connector/1",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _search_page(topic: str, page: int, per_page: int, token: Optional[str], opener) -> dict:
    query = urllib.parse.urlencode(
        {"q": f"topic:{topic}", "sort": "stars", "order": "desc", "per_page": per_page, "page": page}
    )
    url = f"{API_ROOT}/search/repositories?{query}"
    request = urllib.request.Request(url, headers=_auth_headers(token))
    urlopen = opener or urllib.request.urlopen
    with urlopen(request, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _collect_candidates(
    topic: str, max_candidates: int, per_page: int, token: Optional[str], opener=None
) -> List[dict]:
    items: List[dict] = []
    page = 1
    while len(items) < max_candidates:
        data = _search_page(topic, page, per_page, token, opener)
        batch = data.get("items", [])
        if not batch:
            break
        items.extend(batch)
        if len(batch) < per_page:
            break  # exhausted GitHub's result set for this query
        page += 1
    return items[:max_candidates]


def _license_spdx(item: dict) -> Optional[str]:
    lic = item.get("license") or {}
    spdx = lic.get("spdx_id")
    if not spdx or spdx == "NOASSERTION":
        return None
    return spdx


def _deterministic_order(items: List[dict]) -> List[dict]:
    return sorted(items, key=lambda it: (-int(it.get("stargazers_count") or 0), str(it.get("full_name") or "")))


def _tarball_url(full_name: str, default_branch: str) -> str:
    return f"https://github.com/{full_name}/archive/refs/heads/{default_branch}.tar.gz"


def _select_eligible(
    items: List[dict], budget_bytes: int, allowed_licenses: frozenset
) -> Tuple[List[dict], List[dict]]:
    """Returns (selected, excluded_for_license) in deterministic rank order.
    Stops selecting the moment the next license-eligible repo's declared size
    (bytes, from the search API's `size` field in KiB) would push the running
    total past budget_bytes -- no later, lower-ranked repo is substituted in."""
    ordered = _deterministic_order(items)
    selected: List[dict] = []
    excluded: List[dict] = []
    running_total = 0
    for item in ordered:
        spdx = _license_spdx(item)
        if spdx not in allowed_licenses:
            excluded.append(item)
            continue
        declared_bytes = int(item.get("size") or 0) * 1024
        if running_total + declared_bytes > budget_bytes:
            break
        enriched = dict(item)
        enriched["_resolved_license"] = spdx
        enriched["_declared_bytes"] = declared_bytes
        selected.append(enriched)
        running_total += declared_bytes
    return selected, excluded


def fetch(args: argparse.Namespace, opener=None) -> Path:
    allowed_licenses = spdx_gate.allowed_licenses()
    items = _collect_candidates(args.topic, args.max_candidates, args.per_page, args.github_token, opener)
    selected, excluded = _select_eligible(items, args.budget_bytes, allowed_licenses)
    if not selected:
        raise rcpt.BlockedError(
            f"no repos for topic '{args.topic}' had an in-set LICENSE within "
            f"{len(items)} candidates / budget {args.budget_bytes} bytes"
        )

    key = rcpt.safe_key(args.topic)
    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "github" / key
    dest_root.mkdir(parents=True, exist_ok=True)

    downloaded_paths: List[Path] = []
    per_repo_notes = []
    licenses_seen = set()
    try:
        for item in selected:
            full_name = item["full_name"]
            default_branch = item.get("default_branch") or "main"
            url = _tarball_url(full_name, default_branch)
            dest_file = dest_root / (rcpt.safe_key(full_name) + ".tar.gz")
            rcpt.download_url(url, dest_file, opener=opener)
            with dest_file.open("rb") as fh:
                head = fh.read(1024)
            try:
                rcpt.gate_content_type(url, head, args.allow_content_mismatch)
            except rcpt.ContentTypeMismatchError:
                dest_file.unlink(missing_ok=True)
                raise
            downloaded_paths.append(dest_file)
            licenses_seen.add(item["_resolved_license"])
            per_repo_notes.append(
                {
                    "full_name": full_name,
                    "url": item.get("html_url", f"https://github.com/{full_name}"),
                    "license": item["_resolved_license"],
                    "stars": item.get("stargazers_count"),
                    "declared_size_bytes": item["_declared_bytes"],
                }
            )
    except Exception:
        for p in downloaded_paths:
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
        raise

    files = rcpt.build_file_entries(dest_root, [p.relative_to(dest_root) for p in downloaded_paths])
    summary_license = licenses_seen.pop() if len(licenses_seen) == 1 else "mixed (see notes)"

    receipt = rcpt.Receipt(
        source="github",
        source_id=f"topic:{args.topic}",
        canonical_url=f"https://github.com/search?q=topic%3A{urllib.parse.quote(args.topic)}&s=stars&o=desc",
        license=summary_license,
        license_evidence="GitHub Search API per-repo `license.spdx_id` (LICENSE-file detection), filtered to allow-set",
        revision=None,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=json.dumps(
            {
                "candidates_considered": len(items),
                "excluded_for_license": len(excluded),
                "selected": per_repo_notes,
                "budget_bytes": args.budget_bytes,
                "allowed_licenses": sorted(allowed_licenses),
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
