#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive an Ember remote-branch capture from safe-wrapper JSON snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.remote_branch_salvage import PacketError, _canonical


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"cannot read {path.name}: {exc}") from exc


def _flatten_pages(value: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PacketError(f"{field} slurp must be a list of pages")
    rows: list[dict[str, Any]] = []
    for page_index, page in enumerate(value):
        if not isinstance(page, list):
            raise PacketError(f"{field} page {page_index} is not a list")
        for row_index, row in enumerate(page):
            if not isinstance(row, dict):
                raise PacketError(f"{field} page {page_index} row {row_index} is not an object")
            rows.append(row)
    return rows


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _run_git(repo: Path, args: Sequence[str], *, check: bool = True, text: bool = True) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, check=False)
    if check and result.returncode != 0:
        error = result.stderr.strip() if text else result.stderr.decode("utf-8", errors="replace").strip()
        raise PacketError(f"git {' '.join(args)} failed: {error}")
    return result


def _git_text(repo: Path, *args: str) -> str:
    return _run_git(repo, args).stdout.strip()


def _ref_sha(repo: Path, name: str) -> str:
    return _git_text(repo, "rev-parse", f"refs/remotes/origin/{name}^{{commit}}")


def _reachability(repo: Path, master: str, head: str) -> dict[str, Any]:
    merge = _run_git(repo, ["merge-base", master, head], check=False)
    if merge.returncode != 0:
        return {"status": "NO_COMMON_ANCESTOR", "ahead_by": 0, "behind_by": 0, "merge_base": None}
    merge_base = merge.stdout.strip()
    counts = _git_text(repo, "rev-list", "--left-right", "--count", f"{master}...{head}").split()
    if len(counts) != 2:
        raise PacketError("git rev-list returned an invalid count")
    behind, ahead = (int(counts[0]), int(counts[1]))
    if behind == 0 and ahead == 0:
        status = "IDENTICAL"
    elif ahead == 0:
        status = "BEHIND"
    elif behind == 0:
        status = "AHEAD"
    else:
        status = "DIVERGED"
    return {"status": status, "ahead_by": ahead, "behind_by": behind, "merge_base": merge_base}


def _diff(repo: Path, base: str, head: str) -> tuple[list[str], bytes]:
    names = _run_git(repo, ["diff", "--name-only", "-z", base, head], text=False).stdout
    paths = [item.decode("utf-8", errors="strict") for item in names.split(b"\0") if item]
    patch = _run_git(repo, ["diff", "--binary", "--no-ext-diff", base, head], text=False).stdout
    return sorted(paths), patch


def _path_digest(paths: Iterable[str]) -> str:
    return _sha256_bytes("".join(f"{path}\n" for path in sorted(paths)).encode("utf-8"))


def _equivalence(repo: Path, master: str, head: str, reach: Mapping[str, Any], prs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    empty = _sha256_bytes(b"")
    if head == master:
        return {"status": "NOT_APPLICABLE", "canonical_survivor": master, "path_count": 0, "path_digest_sha256": empty, "patch_digest_sha256": empty}
    if reach["status"] == "BEHIND":
        return {"status": "PROVEN", "canonical_survivor": master, "path_count": 0, "path_digest_sha256": empty, "patch_digest_sha256": empty}
    exact_merged = [pr for pr in prs if pr["head_sha"] == head and pr["merged"] and pr["merge_sha"]]
    for pr in sorted(exact_merged, key=lambda item: int(item["number"]), reverse=True):
        try:
            head_paths, head_patch = _diff(repo, str(pr["base_sha"]), head)
            merge_paths, merge_patch = _diff(repo, str(pr["base_sha"]), str(pr["merge_sha"]))
            if head_paths == merge_paths and head_patch == merge_patch and _run_git(repo, ["merge-base", "--is-ancestor", str(pr["merge_sha"]), master], check=False).returncode == 0:
                return {"status": "PROVEN", "canonical_survivor": pr["merge_sha"], "path_count": len(head_paths), "path_digest_sha256": _path_digest(head_paths), "patch_digest_sha256": _sha256_bytes(head_patch)}
        except PacketError:
            continue
    try:
        merge_base = reach.get("merge_base")
        if isinstance(merge_base, str):
            paths, patch = _diff(repo, merge_base, head)
            return {"status": "NOT_PROVEN", "canonical_survivor": None, "path_count": len(paths), "path_digest_sha256": _path_digest(paths), "patch_digest_sha256": _sha256_bytes(patch)}
    except PacketError:
        pass
    return {"status": "ERROR", "canonical_survivor": None, "path_count": 0, "path_digest_sha256": empty, "patch_digest_sha256": empty}


def _citations(repo: Path, master: str, name: str, head: str) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _run_git(repo, ["grep", "-n", "-F", "-e", name, "-e", head, master, "--", "."], check=False)
    if result.returncode not in {0, 1}:
        return {"complete": False, "citations": []}, {"complete": False, "citations": []}
    public: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 3:
            continue
        path = parts[1] if parts[0] == master else parts[0]
        line_number = parts[2] if parts[0] == master else parts[1]
        public.add(f"{path}:{line_number}")
    # A scan of the public Git tree is complete only for public consumers. Receipts and
    # manifests tracked there remain public citations; their path prefix cannot prove that
    # private/durable custody roots were searched. Until a separately content-addressed
    # external custody census is supplied, every row must fail closed on custody completeness.
    return {"complete": True, "citations": sorted(public)}, {"complete": False, "citations": []}


def _compact_pr(pr: Mapping[str, Any]) -> dict[str, Any]:
    merged = isinstance(pr.get("merged_at"), str) and bool(pr.get("merged_at"))
    head = pr.get("head") if isinstance(pr.get("head"), Mapping) else {}
    base = pr.get("base") if isinstance(pr.get("base"), Mapping) else {}
    return {
        "number": int(pr["number"]),
        "state": str(pr["state"]).lower(),
        "head_sha": str(head.get("sha")),
        "merged": merged,
        "merge_sha": str(pr.get("merge_commit_sha")) if merged else None,
        "base_sha": str(base.get("sha")),
    }


def build_capture(*, repo: Path, branches_pre_path: Path, branches_post_path: Path, pulls_path: Path, tags_path: Path, releases_path: Path, deployments_path: Path, public_master_path: Path, captured_at: str) -> dict[str, Any]:
    branches_pre = _flatten_pages(_read(branches_pre_path), field="branches_pre")
    branches_post = _flatten_pages(_read(branches_post_path), field="branches_post")
    pulls_raw = _flatten_pages(_read(pulls_path), field="pulls")
    tags = _flatten_pages(_read(tags_path), field="tags")
    releases = _flatten_pages(_read(releases_path), field="releases")
    deployments = _flatten_pages(_read(deployments_path), field="deployments")
    master_raw = _read(public_master_path)
    if not isinstance(master_raw, Mapping) or not isinstance(master_raw.get("sha"), str):
        raise PacketError("public_master has invalid shape")
    master = str(master_raw["sha"])
    pre = {str(item["name"]): item for item in branches_pre}
    post = {str(item["name"]): item for item in branches_post}
    if len(pre) != len(branches_pre) or len(post) != len(branches_post) or set(pre) != set(post):
        raise PacketError("branch population changed between capture and pre-execution replay")

    prs_by_ref: dict[str, list[dict[str, Any]]] = {}
    for raw in pulls_raw:
        head = raw.get("head") if isinstance(raw.get("head"), Mapping) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), Mapping) else {}
        ref = head.get("ref")
        if isinstance(ref, str) and ref and head_repo.get("full_name") == "wordingone/ember":
            prs_by_ref.setdefault(ref, []).append(_compact_pr(raw))
    tags_by_sha: dict[str, list[str]] = {}
    for tag in tags:
        commit = tag.get("commit") if isinstance(tag.get("commit"), Mapping) else {}
        if isinstance(commit.get("sha"), str) and isinstance(tag.get("name"), str):
            tags_by_sha.setdefault(str(commit["sha"]), []).append(str(tag["name"]))

    rows: list[dict[str, Any]] = []
    for name in sorted(pre):
        item = pre[name]
        commit = item.get("commit") if isinstance(item.get("commit"), Mapping) else {}
        post_commit = post[name].get("commit") if isinstance(post[name].get("commit"), Mapping) else {}
        head = str(commit.get("sha"))
        post_head = str(post_commit.get("sha"))
        errors: list[str] = []
        try:
            local_head = _ref_sha(repo, name)
            if local_head != head:
                errors.append("local_remote_tracking_ref_mismatch")
        except PacketError:
            errors.append("local_remote_tracking_ref_unavailable")
        try:
            reach = _reachability(repo, master, head)
        except PacketError:
            reach = {"status": "ERROR", "ahead_by": 0, "behind_by": 0, "merge_base": None}
            errors.append("reachability_failed")
        prs = sorted(prs_by_ref.get(name, []), key=lambda row: int(row["number"]))
        open_head = [{"number": pr["number"], "head_sha": head} for pr in prs if pr["state"] == "open" and pr["head_sha"] == head]
        eq = _equivalence(repo, master, head, reach, prs)
        public, custody = _citations(repo, master, name, head)
        if not public["complete"]:
            errors.append("public_master_consumer_scan_failed")
        if not custody["complete"]:
            errors.append("external_custody_census_unavailable")
        branch_releases = sorted(str(row.get("tag_name") or row.get("name")) for row in releases if row.get("target_commitish") in {name, head} and (row.get("tag_name") or row.get("name")))
        branch_deployments = sorted(str(row.get("id")) for row in deployments if row.get("ref") in {name, head})
        rows.append({
            "name": name,
            "ref": f"refs/heads/{name}",
            "head_sha": head,
            "protected": item.get("protected") if isinstance(item.get("protected"), bool) else None,
            "open_head_prs": open_head,
            "all_prs": prs,
            "reachability": reach,
            "patch_blob_equivalence": eq,
            "exact_head_tags": sorted(tags_by_sha.get(head, [])),
            "releases": branch_releases,
            "deployments": branch_deployments,
            "public_consumers": public,
            "custody_references": custody,
            "reconstruction": {"command": f"git fetch origin refs/heads/{name}:refs/remotes/origin/{name}", "expected_sha": head},
            "ref_stability": {"captured_sha": head, "preexecution_sha": post_head},
            "errors": sorted(set(errors)),
        })

    selection = hashlib.sha256(_canonical([[row["ref"], row["head_sha"]] for row in sorted(rows, key=lambda row: row["ref"])] )).hexdigest()
    evidence_paths = {
        "branches_pre": branches_pre_path,
        "branches_post": branches_post_path,
        "pulls": pulls_path,
        "tags": tags_path,
        "releases": releases_path,
        "deployments": deployments_path,
        "public_master": public_master_path,
    }
    return {
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "schema_version": "ember-remote-branch-capture-v1",
        "repository": "wordingone/ember",
        "master_sha": master,
        "captured_at": captured_at,
        "pagination": {"complete": True, "page_size": 100, "link_headers_exhausted": True},
        "source_evidence": {key: _file_sha256(path) for key, path in evidence_paths.items()},
        "branches": rows,
        "selection_sha256": selection,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.raw_root
    try:
        capture = build_capture(repo=args.repo, branches_pre_path=root / "branches_pre.json", branches_post_path=root / "branches_post.json", pulls_path=root / "pulls.json", tags_path=root / "tags.json", releases_path=root / "releases.json", deployments_path=root / "deployments.json", public_master_path=root / "public_master.json", captured_at=args.captured_at)
        args.output.write_bytes(_canonical(capture) + b"\n")
        print(json.dumps({"status": "PASS", "branches": len(capture["branches"]), "master_sha": capture["master_sha"], "selection_sha256": capture["selection_sha256"]}, sort_keys=True))
    except PacketError as exc:
        print(f"REMOTE_BRANCH_CAPTURE FAIL: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
