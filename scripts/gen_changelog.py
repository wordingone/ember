#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""gen_changelog.py -- regenerate CHANGELOG.md from git history.

Grouping decision (read from the real history, not imposed on it)
-------------------------------------------------------------------
A sample of the most recent 1000 commits on `--first-parent` history (559
distinct first-parent commits in that sample) shows:
  - only ~19% of ALL commit subjects (raw `git log`, not first-parent) carry a
    conventional-commit type prefix (feat:/fix:/docs:/...) -- too sparse and
    inconsistent to key a changelog's grouping off `type`.
  - ~91% of FIRST-PARENT commits (the commits that actually land on master,
    one per squash-merged or true-merged PR, collapsing the PR's own internal
    commits) carry an identifiable PR number, via one of two shapes GitHub
    produces: a squash-merge subject ending in `(#123)`, or a true-merge
    commit subject `Merge pull request #123 from <owner>/<branch>`.

So entries are grouped by PR number where the history supports it (the
majority case) and fall back to the bare commit subject when it does not (a
direct-to-master commit outside the PR flow). Entries are ordered
reverse-chronologically and bucketed by the commit's author date (UTC
calendar day) -- there is no reliable `type` axis to bucket by instead, and a
date bucket is honest about what the history actually records: when
something landed, not a category invented for it after the fact.

Traceability: every entry carries its PR number as a GitHub link when one
exists, since that is how work in this repo is actually followed up.

Name-safety note: a true-merge commit's own subject carries no description
(just "Merge pull request #N from <owner>/<branch>"); branch slugs in this
repo routinely embed founder codenames as path segments, and turning a slug
into title-cased prose (an earlier draft of this script did exactly that)
put those tokens into a new tracked file and was correctly rejected by
`tools/repo-guard.sh`'s operator-name denylist check. So a merge commit's
entry text is drawn from its merged branch's own TIP commit subject
(reproduced verbatim, same treatment a squash subject already gets) rather
than fabricated from the slug; see collect_entries() for the exact rule and
its safe fallback.

Stdlib only. No network. Reads git via subprocess against a given ref
(default HEAD) so it works identically in a worktree, in CI, or against any
commit range.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG_PATH = os.path.join(ROOT, "CHANGELOG.md")
REPO_SLUG = "wordingone/ember"

BEGIN_MARKER = "<!-- CHANGELOG-GENERATED-BEGIN -->"
END_MARKER = "<!-- CHANGELOG-GENERATED-END -->"

# Record separator / unit separator: never appear in a commit subject or an
# ISO date, so a single `git log --format` line is safe to split on them.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"

SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
MERGE_PR_RE = re.compile(r"^Merge pull request #(\d+) from \S+/(\S+)\s*$")

# The bot's own regenerate commits must not be mistaken for a second landed
# PR entry when this script is later re-run against history that includes
# them -- they carry no PR number and their own subject is not useful
# changelog content.
BOT_SUBJECT_MARKER = "[skip-changelog]"


def run_git(args, cwd):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"gen_changelog: git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def fetch_subjects(shas, root):
    """Batch-fetch commit subjects for a list of SHAs in one git call."""
    if not shas:
        return {}
    fmt = "%H" + _FIELD_SEP + "%s"
    raw = run_git(["show", "-s", f"--format={fmt}", *shas], cwd=root)
    out = {}
    for line in raw.splitlines():
        if _FIELD_SEP not in line:
            continue
        sha, subject = line.split(_FIELD_SEP, 1)
        out[sha] = subject.strip()
    return out


def collect_entries(ref, root):
    """Walk first-parent history from `ref` and return (date, pr, text) rows.

    A true-merge commit's OWN subject is just `Merge pull request #N from
    <owner>/<branch>` -- no descriptive content. Turning the branch slug
    itself into title-cased display prose is unsafe: this repo's branch
    names routinely embed operator-identifying tokens as ordinary path
    segments, and repo-guard's operator-name denylist rightly blocks that
    text the moment it is written into a new tracked file -- confirmed
    empirically (a first draft of this generator did exactly that and was
    rejected by `tools/repo-guard.sh`'s hashed-denylist name check). So the
    branch slug is NEVER used as display text. Instead: the merged branch's
    own TIP commit (the merge commit's
    second parent) almost always carries the real, human-authored PR summary
    as its subject line (GitHub's default merge title/description mirrors
    it) -- that text is reproduced verbatim, the same "quote history as-is"
    treatment a squash-merge subject already gets, rather than fabricated
    fresh from a slug. If that tip subject is unusable (empty, or itself
    another merge marker -- an octopus/nested merge), the entry falls back to
    a minimal, content-free placeholder that names only the PR number.
    """
    fmt = _FIELD_SEP.join(["%H", "%P", "%ad", "%s"]) + _RECORD_SEP
    raw = run_git(
        [
            "log",
            "--first-parent",
            "--date=format:%Y-%m-%d",
            f"--pretty=format:{fmt}",
            ref,
        ],
        cwd=root,
    )
    records = []
    for record in raw.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_FIELD_SEP, 3)
        if len(parts) != 4:
            continue
        records.append(parts)

    # Pre-fetch every merge commit's second-parent subject in one batch call.
    second_parents = []
    for _sha, parents, _date, subject in records:
        parent_list = parents.split()
        if len(parent_list) == 2 and MERGE_PR_RE.match(subject.strip()):
            second_parents.append(parent_list[1])
    tip_subjects = fetch_subjects(second_parents, root)

    entries = []
    for _sha, parents, date, subject in records:
        subject = subject.strip()
        if not subject or BOT_SUBJECT_MARKER in subject:
            continue
        squash = SQUASH_PR_RE.search(subject)
        merge = MERGE_PR_RE.match(subject)
        if squash:
            pr = int(squash.group(1))
            text = subject
        elif merge:
            pr = int(merge.group(1))
            parent_list = parents.split()
            tip = tip_subjects.get(parent_list[1]) if len(parent_list) == 2 else ""
            tip_squash = SQUASH_PR_RE.search(tip) if tip else None
            usable_tip = bool(
                tip
                and not tip.lower().startswith("merge ")
                and not tip_squash  # avoid double-appending its own (#M)
            )
            text = tip if usable_tip else f"PR #{pr} merged"
        else:
            pr = None
            text = subject
        entries.append((date, pr, text))
    return entries


def render_body(entries):
    if not entries:
        return "_No history found._"
    by_date = OrderedDict()
    seen_per_date = defaultdict(set)
    for date, pr, text in entries:
        # A squash commit and its true-merge sibling never both appear
        # (first-parent walks exactly one commit per landed PR), but the same
        # PR number appearing twice in one date bucket from unrelated commits
        # (e.g. a direct-to-master fixup sharing a day with its own PR) is
        # still deduplicated on (pr, text) so a re-run is never lossier, only
        # ever idempotent.
        key = (pr, text)
        if key in seen_per_date[date]:
            continue
        seen_per_date[date].add(key)
        by_date.setdefault(date, []).append((pr, text))

    lines = []
    for date in sorted(by_date, reverse=True):
        lines.append(f"## {date}")
        lines.append("")
        for pr, text in by_date[date]:
            if pr is not None:
                link = f"([#{pr}](https://github.com/{REPO_SLUG}/pull/{pr}))"
                if text.rstrip().endswith(f"(#{pr})"):
                    # squash-style subject already ends in "(#123)" -- turn
                    # that literal suffix into the link instead of doubling it.
                    stripped = text.rstrip()[: -len(f"(#{pr})")].rstrip()
                    lines.append(f"- {stripped} {link}")
                else:
                    lines.append(f"- {text} {link}")
            else:
                lines.append(f"- {text}")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def render_changelog(entries):
    body = render_body(entries)
    return "\n".join(
        [
            "# Changelog",
            "",
            "Every entry below is regenerated from `git log --first-parent` on",
            "`master` by `scripts/gen_changelog.py`, run automatically by",
            "`.github/workflows/changelog.yml` on every push to `master`. Hand-edit",
            "nothing between the markers -- it is overwritten on the next push.",
            "",
            BEGIN_MARKER,
            body,
            END_MARKER,
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=ROOT)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if CHANGELOG.md would change (no write)",
    )
    parser.add_argument("--changelog", default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    changelog_path = Path(args.changelog) if args.changelog else Path(CHANGELOG_PATH)
    if args.changelog is None and str(root) != ROOT:
        changelog_path = root / "CHANGELOG.md"

    entries = collect_entries(args.ref, str(root))
    new_text = render_changelog(entries)

    old_text = ""
    if changelog_path.is_file():
        old_text = changelog_path.read_text(encoding="utf-8")

    if new_text == old_text:
        print(f"CHANGELOG.md already current ({len(entries)} entries).")
        return 0

    if args.check:
        print("CHANGELOG.md is STALE relative to git history.")
        return 1

    changelog_path.write_text(new_text, encoding="utf-8", newline="\n")
    print(f"CHANGELOG.md regenerated ({len(entries)} entries).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
