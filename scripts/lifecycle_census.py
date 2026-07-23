#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed, paginated open-issue/PR census for the freshness monitor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PageFetcher = Callable[[int, int], list[dict[str, Any]]]


class CensusError(RuntimeError):
    """A collection or receipt error that must fail closed."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _item_number(item: Mapping[str, Any], *, page: int, index: int) -> int:
    number = item.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise CensusError(f"page {page} item {index} has invalid number")
    return number


def _item_sha256(item: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(item)).hexdigest()


def collect_population(
    fetch_page: PageFetcher,
    *,
    kind: str,
    page_size: int = 100,
    max_pages: int = 1000,
) -> list[dict[str, Any]]:
    """Collect every page, deduplicating immutable numeric identities.

    The caller supplies one endpoint-specific fetcher. An empty page is the only
    completion sentinel; a short page is not treated as proof that no later page
    exists. For the issues endpoint, pull requests are excluded by their
    ``pull_request`` marker so issue and PR populations cannot be conflated.
    """

    if kind not in {"issue", "pull_request"}:
        raise CensusError(f"unsupported population kind: {kind}")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise CensusError("page_size must be an integer between 1 and 100")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise CensusError("max_pages must be a positive integer")

    by_number: dict[int, dict[str, Any]] = {}
    by_digest: dict[int, str] = {}
    for page in range(1, max_pages + 1):
        try:
            rows = fetch_page(page, page_size)
        except Exception as exc:  # noqa: BLE001 - all transport failures fail closed
            raise CensusError(f"failed to collect {kind} page {page}: {exc}") from exc
        if not isinstance(rows, list):
            raise CensusError(f"{kind} page {page} was not a list")
        if not rows:
            return [by_number[number] for number in sorted(by_number)]

        for index, raw_item in enumerate(rows):
            if not isinstance(raw_item, dict):
                raise CensusError(f"page {page} item {index} was not an object")
            if kind == "issue" and "pull_request" in raw_item:
                continue
            number = _item_number(raw_item, page=page, index=index)
            digest = _item_sha256(raw_item)
            prior_digest = by_digest.get(number)
            if prior_digest is not None:
                if prior_digest != digest:
                    raise CensusError(f"conflicting duplicate {kind} identity {number}")
                continue
            item = dict(raw_item)
            item["item_sha256"] = digest
            by_number[number] = item
            by_digest[number] = digest
    raise CensusError(f"{kind} collection exceeded max_pages={max_pages} without an empty page")


def _receipt_items(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: int(row["number"])):
        number = item.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise CensusError("receipt item has invalid number")
        digest = item.get("item_sha256") or _item_sha256(item)
        result.append({"number": number, "item_sha256": digest})
    return result


def build_receipt(
    *,
    repository: str,
    master_sha: str,
    collected_at: str,
    issues: Sequence[Mapping[str, Any]],
    pull_requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic, content-addressed receipt with explicit limits."""

    if not isinstance(repository, str) or not repository:
        raise CensusError("repository is required")
    if not isinstance(master_sha, str) or len(master_sha) != 40 or any(ch not in "0123456789abcdef" for ch in master_sha):
        raise CensusError("master_sha must be a lowercase 40-character SHA-1")
    try:
        parsed_time = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CensusError("collected_at must be ISO-8601") from exc
    if parsed_time.tzinfo is None:
        raise CensusError("collected_at must include a timezone")

    issue_items = _receipt_items(issues)
    pr_items = _receipt_items(pull_requests)
    receipt: dict[str, Any] = {
        "schema_version": "ember-lifecycle-census-v1",
        "repository": repository,
        "master_sha": master_sha,
        "collected_at": collected_at,
        "populations": {"issues": issue_items, "pull_requests": pr_items},
        "counts": {"issues": len(issue_items), "pull_requests": len(pr_items)},
        "claim_limits": ["No issue closure or capability claim follows."],
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
    return receipt


class GitHubApi:
    def __init__(self, repository: str, token: str, *, api_base: str = "https://api.github.com"):
        self.repository = repository
        self.token = token
        self.api_base = api_base.rstrip("/")

    def page(self, endpoint: str, page: int, per_page: int) -> list[dict[str, Any]]:
        query = urlencode({"state": "open", "per_page": per_page, "page": page})
        request = Request(
            f"{self.api_base}/repos/{self.repository}/{endpoint}?{query}",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}", "X-GitHub-Api-Version": "2022-11-28"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise CensusError(f"GitHub {endpoint} page {page} failed: {exc}") from exc
        if not isinstance(payload, list):
            raise CensusError(f"GitHub {endpoint} page {page} was not a list")
        return payload


def collect_live_census(*, repository: str, master_sha: str, collected_at: str, token: str) -> dict[str, Any]:
    api = GitHubApi(repository, token)
    issues = collect_population(lambda page, per_page: api.page("issues", page, per_page), kind="issue")
    pull_requests = collect_population(lambda page, per_page: api.page("pulls", page, per_page), kind="pull_request")
    return build_receipt(
        repository=repository,
        master_sha=master_sha,
        collected_at=collected_at,
        issues=issues,
        pull_requests=pull_requests,
    )


def write_receipt(receipt: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical_json(receipt) + b"\n"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="wordingone/ember")
    parser.add_argument("--master-sha", required=True)
    parser.add_argument("--collected-at", default=None)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("CensusError: GH_TOKEN/GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    collected_at = args.collected_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        receipt = collect_live_census(repository=args.repo, master_sha=args.master_sha, collected_at=collected_at, token=token)
        output = args.output
        if output.suffix == ".json" and output.name != "lifecycle-census.json":
            path = output
        else:
            path = output / f"lifecycle-census-{receipt['receipt_sha256']}.json"
        write_receipt(receipt, path)
        print(json.dumps({"status": "PASS", "path": str(path), "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
        return 0
    except CensusError as exc:
        print(f"CensusError: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
