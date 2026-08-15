#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""arxiv_fetch.py -- arXiv API (Atom) connector CLI.

    arxiv_fetch.py (--ids ID... | --query Q --max N) [--what meta|pdf|source]
                   [--dest DIR] [--license-filter cc-only|all]
                   [--allow-unverified-license]

Stdlib-only (feedparser/arxiv packages were confirmed ABSENT at build time --
see README "Dependency posture"): queries the public arXiv Atom API directly
via `urllib.request` + `xml.etree.ElementTree`, respecting the API's politeness
contract (<=1 request per 3s, <=100 results per page).

Per-paper license handling (per spec, "arXiv-perpetual license papers are
metadata-only unless filter widened by lead"):
  - an `<arxiv:license>` element whose value is a creativecommons.org URL (or
    the CC0 URL) is treated as a resolved CC license -- eligible for the
    `cc-only` content filter (the default).
  - an `<arxiv:license>` element present but pointing at any other URL
    (typically arXiv's own nonexclusive-distrib license) is a RESOLVED,
    non-CC license -- known, not UNVERIFIED, but not eligible under
    `cc-only`.
  - no `<arxiv:license>` element at all is UNVERIFIED (subject to the
    standard --allow-unverified-license gate).

One receipt per invocation (the frozen schema has a single `license` field
per receipt): for `--what meta` the single file is a JSON listing of the
returned entries (id/title/license/updated); for `--what pdf|source` the
files are the downloaded PDFs/source archives for papers eligible under the
license filter -- per-paper license detail always goes into `notes`.

`--paper-list FILE` (fast-follow): a third, mutually-exclusive source mode
alongside `--ids`/`--query`, for an exact, pre-filtered id list too large to
pass as CLI args (e.g. the output of the separate arXiv bulk OAI-PMH
metadata harvest + license filter, thousands of ids). One id per line;
blank lines and lines starting with `#` are skipped; every id is then routed
through the SAME `query_by_ids()` used by `--ids` (identical batching,
politeness sleep, license handling) -- this is a different id SOURCE, not a
different query mechanism.

`--budget-bytes N` (fast-follow, paired with `--paper-list`): rank-fidelity
budget stop for content fetch (`--what pdf|source`). Walks candidates in the
paper-list FILE'S OWN declared order (not the Atom API's response order,
which is not guaranteed to preserve input order -- entries are explicitly
re-sorted to match), HEAD-probes each candidate's real Content-Length before
downloading it, and stops at the first candidate that would exceed the
budget -- no skip-and-continue past an over-budget candidate to a smaller
later one.

Fail-closed handling for a candidate whose size can't be established up
front (no Content-Length header, a redirect that dropped it, or the HEAD
probe itself failing): rather than stopping blind on an unknown size, the
candidate is downloaded under a RUNNING budget check instead -- streamed via
the same `receipt.download_url` machinery every connector uses, with
`max_bytes` set to the exact remaining budget, so the download itself aborts
mid-stream (`DownloadTooLargeError`) the instant it would exceed what's left.
An abort-on-exceed here ends the walk at that candidate exactly like a
declared over-budget stop -- never skip-and-continue in either case. This
keeps the selected fetch set a pure function of (paper-list, budget), with no
dependence on which server mood happened to answer a given HEAD request (some
servers omit Content-Length, drop it through a redirect, or reject HEAD
outright while still serving GET). Every candidate examined (size, its
source -- head-probed vs streamed, selected/stopped) is written to a sidecar
`_manifests/*.budget-walk.json` file rather than into the receipt's own
`notes` (kept bounded, same lesson as lean_fetch.py's manifest.jsonl fix --
one receipt should never grow with candidate count).
"""
from __future__ import annotations

import argparse
import email.utils
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import receipt as rcpt

CONNECTOR_NAME = "arxiv_fetch"
API_BASE = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
PAGE_SIZE_MAX = 100
RATE_LIMIT_SECONDS = 3.0
WALK_HEARTBEAT_EVERY = 100  # candidates examined between --budget-bytes walk log lines
ARXIV_PERPETUAL_LABEL = "arXiv perpetual, non-exclusive license"


def _is_cc_url(license_url: str) -> bool:
    return "creativecommons.org" in license_url or "publicdomain/zero" in license_url


class HeadSizeMismatchError(rcpt.BlockedError):
    """A candidate's HEAD-declared Content-Length (used for --budget-bytes
    accounting) disagrees with what the GET actually delivered. Fail-closed,
    same posture as chunked_download.py's StreamingSizeMismatchError: a GET
    response larger than its own HEAD declaration would otherwise silently
    break the budget the walk computed the selection against, so the
    downloaded file is refused and removed rather than kept."""


@dataclass
class ArxivEntry:
    arxiv_id: str
    title: str
    raw_license_url: Optional[str]
    updated: Optional[str]

    @property
    def is_cc(self) -> bool:
        if not self.raw_license_url:
            return False
        return _is_cc_url(self.raw_license_url)

    @property
    def license_label(self) -> str:
        if self.raw_license_url is None:
            return rcpt.UNVERIFIED
        if self.is_cc:
            return self.raw_license_url
        return ARXIV_PERPETUAL_LABEL

    @property
    def license_evidence(self) -> str:
        if self.raw_license_url is None:
            return "no arxiv:license element in API response"
        return "arxiv:license Atom element"


def _entry_id_short(id_url: str) -> str:
    # id_url looks like http://arxiv.org/abs/2301.00001v2
    tail = id_url.rstrip("/").rsplit("/", 1)[-1]
    return tail


_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


def _strip_version(arxiv_id: str) -> str:
    """The Atom API's entry ids carry a version suffix (e.g. 2301.00001v2);
    paper-list files built from the OAI-PMH harvest do not. Rank-fidelity
    order matching against a declared paper-list must compare on this
    canonical (unversioned) form on both sides, or every lookup silently
    misses (caught by test_budget_bytes_honors_paper_list_declared_order)."""
    return _VERSION_SUFFIX_RE.sub("", arxiv_id)


def _parse_atom(xml_bytes: bytes) -> List[ArxivEntry]:
    root = ET.fromstring(xml_bytes)
    out = []
    for entry in root.findall("atom:entry", NS):
        id_el = entry.find("atom:id", NS)
        title_el = entry.find("atom:title", NS)
        updated_el = entry.find("atom:updated", NS)
        license_el = entry.find("arxiv:license", NS)
        arxiv_id = _entry_id_short(id_el.text.strip()) if id_el is not None and id_el.text else "unknown"
        title = " ".join(title_el.text.split()) if title_el is not None and title_el.text else ""
        updated = updated_el.text.strip() if updated_el is not None and updated_el.text else None
        raw_license = license_el.text.strip() if license_el is not None and license_el.text else None
        out.append(ArxivEntry(arxiv_id=arxiv_id, title=title, raw_license_url=raw_license, updated=updated))
    return out


FLOW_CONTROL_CODES = (429, 503)
FLOW_CONTROL_POLICY_VERSION = "v2-exponential"
MAX_FLOW_CONTROL_RETRIES = 8
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_FACTOR = 2.0
BACKOFF_MAX_SLEEP_SECONDS = 900.0
BACKOFF_JITTER_FRACTION = 0.25
RETRY_AFTER_CAP_SECONDS = 1800.0

_LOG_PATH: Optional[Path] = None


def log(msg: str) -> None:
    """Single logging surface for the connector's flow-control lifecycle.

    Always goes to stdout (so a shell redirect captures it exactly as the
    prior run's fetch.log did) and additionally appends to --log-file when
    configured, opening/closing per line so an unattended multi-hour run's
    progress is durable on disk even if the process is killed uncleanly --
    the previous death left a single 57-byte log with no evidence of whether
    any retry logic had run at all."""
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    if _LOG_PATH is not None:
        try:
            with _LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            # A broken log sink must never take down a live fetch; stdout above
            # already carried the line.
            pass


def flow_control_policy_line() -> str:
    """The startup declaration proving WHICH backoff policy a live process is
    actually running -- the prior run died on a 429 with no way to tell from
    its log whether retry logic existed, was configured, or had simply never
    been reached. Emitted before the first request of every invocation."""
    return (
        f"FLOW-CONTROL-POLICY version={FLOW_CONTROL_POLICY_VERSION} "
        f"codes={','.join(str(c) for c in FLOW_CONTROL_CODES)} "
        f"max_retries={MAX_FLOW_CONTROL_RETRIES} "
        f"base_seconds={BACKOFF_BASE_SECONDS} factor={BACKOFF_FACTOR} "
        f"max_sleep_seconds={BACKOFF_MAX_SLEEP_SECONDS} "
        f"jitter_fraction={BACKOFF_JITTER_FRACTION} "
        f"retry_after_honored=true retry_after_formats=delta-seconds|http-date "
        f"retry_after_cap_seconds={RETRY_AFTER_CAP_SECONDS} "
        f"politeness_sleep_seconds={RATE_LIMIT_SECONDS}"
    )


def parse_retry_after(raw: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Retry-After per RFC 7231 s7.1.3, which permits EITHER delta-seconds OR
    an HTTP-date -- the prior implementation did a bare int() on the header and
    would raise ValueError on the HTTP-date form, killing the run via the exact
    header it was trying to honor.

    Returns seconds to wait, or None when the header is absent/unparseable (a
    malformed header must degrade to the exponential schedule, never crash).
    Negative or past-dated values clamp to 0."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return max(0.0, (when - reference).total_seconds())


def backoff_sleep_seconds(attempt: int, retry_after: Optional[float], jitter: bool = True) -> float:
    """Exponential schedule for retry `attempt` (0-based), with Retry-After
    honored as a FLOOR rather than a replacement.

    Taking the server's value outright would let a small Retry-After (or a
    header echoed unchanged across repeated refusals) hold the client at a
    constant interval while it is still being rate-limited -- exactly the
    fixed-interval behavior that failed here. Taking max() honors the server's
    stated minimum while still escalating, and the cap keeps a hostile or
    mistaken Retry-After (e.g. 86400) from silently parking an unattended run
    for hours."""
    exponential = min(BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR ** attempt), BACKOFF_MAX_SLEEP_SECONDS)
    if retry_after is not None:
        exponential = max(exponential, min(retry_after, RETRY_AFTER_CAP_SECONDS))
    if jitter:
        # Additive-only jitter: never sleeps LESS than the schedule (or than a
        # server-declared Retry-After floor), while still de-synchronizing
        # retries that would otherwise re-collide in lockstep.
        exponential += random.uniform(0.0, BACKOFF_JITTER_FRACTION * exponential)
    return exponential


def _urlopen_with_backoff(req: "urllib.request.Request", urlopen, timeout: int, sleeper=None):
    """A 429/503 from arXiv, or a bare socket read timeout (TimeoutError raised
    directly by urlopen when the read exceeds `timeout=`), is a politeness/
    transient signal to back off and retry, not a terminal failure -- letting
    it raise straight through (the behavior that was live on 2026-08-15) killed
    an unattended --paper-list run on a single rate-limit hit, leaving a
    one-line log.

    Note the previously-cited precedent does not actually cover this case:
    harvest_oai.py's fetch() retries 503 ONLY, so a 429 falls through to raise
    there too. Retries here are exponential with jitter, honor Retry-After in
    both RFC 7231 formats as a floor, log every retry with its next-attempt
    wall-clock time, and give up after MAX_FLOW_CONTROL_RETRIES so a
    persistently blocked host still fails loudly rather than looping forever."""
    # Resolved at call time, not bound as a default: a module-level default of
    # time.sleep would freeze the reference at import and silently defeat
    # patch.object(arxiv_fetch.time, "sleep", ...) in tests -- which would then
    # sleep for real, or worse, appear to pass while asserting nothing.
    sleep_fn = sleeper or time.sleep
    for attempt in range(MAX_FLOW_CONTROL_RETRIES + 1):
        try:
            return urlopen(req, timeout=timeout)
        except (urllib.error.HTTPError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                if exc.code not in FLOW_CONTROL_CODES:
                    raise
                code = exc.code
                raw_header = exc.headers.get("Retry-After") if exc.headers is not None else None
            else:
                # No status code and no Retry-After header on a bare timeout --
                # same politeness-signal shape as 429/503, treated identically.
                code = "timeout"
                raw_header = None
            retry_after = parse_retry_after(raw_header)
            if attempt == MAX_FLOW_CONTROL_RETRIES:
                log(
                    f"FLOW-CONTROL-EXHAUSTED code={code} url={req.full_url} "
                    f"attempts={MAX_FLOW_CONTROL_RETRIES + 1} -- giving up"
                )
                raise
            sleep_for = backoff_sleep_seconds(attempt, retry_after)
            next_at = datetime.now(timezone.utc) + timedelta(seconds=sleep_for)
            log(
                f"FLOW-CONTROL code={code} attempt={attempt + 1}/{MAX_FLOW_CONTROL_RETRIES} "
                f"retry_after_header={raw_header!r} retry_after_seconds={retry_after} "
                f"sleep_seconds={sleep_for:.1f} next_attempt_at={next_at.isoformat()} "
                f"url={req.full_url}"
            )
            sleep_fn(sleep_for)


def _http_get(url: str, opener=None) -> bytes:
    urlopen = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": "ember-corpus-connector/1"})
    with _urlopen_with_backoff(req, urlopen, 60) as resp:
        return resp.read()


def _head_content_length(url: str, opener=None, timeout: int = 30) -> Optional[int]:
    urlopen = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": "ember-corpus-connector/1"}, method="HEAD")
    with _urlopen_with_backoff(req, urlopen, timeout) as resp:
        cl = resp.headers.get("Content-Length")
        return int(cl) if cl else None


def _write_budget_walk_manifest(
    dest_root: Path,
    key: str,
    budget_bytes: int,
    order_rule: str,
    size_rule: str,
    walk_notes: List[dict],
) -> Path:
    """Sidecar record of every candidate examined during a --budget-bytes walk
    (size, its source -- head-probed vs streamed under a running budget check,
    selected/stopped) -- kept OUT of the receipt's own `notes` field so a large
    candidate list never bloats the receipt (same fix as lean_fetch.py's
    manifest.jsonl O(n^2) growth: one receipt, one bounded notes string, full
    detail lives in a sibling file referenced by relative path)."""
    manifests_dir = dest_root / "_manifests"
    try:
        manifests_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise rcpt.ReceiptWriteError(f"could not create manifests dir: {exc}") from exc
    ts = rcpt.utc_stamp_compact()
    out_path = manifests_dir / f"{ts}-{key}.budget-walk.json"
    if out_path.exists():
        raise rcpt.DestCollisionError(f"budget-walk manifest already exists at {out_path}")
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(
                {
                    "budget_bytes": budget_bytes,
                    "order_rule": order_rule,
                    "size_rule": size_rule,
                    "candidates_examined": len(walk_notes),
                    "selected_count": sum(1 for n in walk_notes if n["status"] == "selected"),
                    "walk": walk_notes,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(out_path)
    except OSError as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise rcpt.ReceiptWriteError(f"could not write budget-walk manifest json: {exc}") from exc
    return out_path


def query_by_ids(ids: List[str], opener=None) -> List[ArxivEntry]:
    entries: List[ArxivEntry] = []
    total_batches = (len(ids) + PAGE_SIZE_MAX - 1) // PAGE_SIZE_MAX
    for i in range(0, len(ids), PAGE_SIZE_MAX):
        chunk = ids[i : i + PAGE_SIZE_MAX]
        url = f"{API_BASE}?id_list={urllib.parse.quote(','.join(chunk))}&max_results={len(chunk)}"
        entries.extend(_parse_atom(_http_get(url, opener)))
        # A large --paper-list spends this whole phase before ANY file is
        # written to dest (539 batches x 3s ~ 27min for a 54k-id list), so
        # without a heartbeat here both the output dir and the log go
        # untouched for half an hour -- indistinguishable from a wedged
        # process to any liveness watch, and to a human reading the log.
        if total_batches > 1:
            log(f"META-BATCH {i // PAGE_SIZE_MAX + 1}/{total_batches} ids={len(chunk)} entries={len(entries)}")
        if i + PAGE_SIZE_MAX < len(ids):
            time.sleep(RATE_LIMIT_SECONDS)
    return entries


def query_by_search(query: str, max_results: int, opener=None) -> List[ArxivEntry]:
    entries: List[ArxivEntry] = []
    start = 0
    remaining = max_results
    while remaining > 0:
        page_size = min(PAGE_SIZE_MAX, remaining)
        url = (
            f"{API_BASE}?search_query={urllib.parse.quote(query)}"
            f"&start={start}&max_results={page_size}"
        )
        page = _parse_atom(_http_get(url, opener))
        if not page:
            break
        entries.extend(page)
        start += len(page)
        remaining -= len(page)
        if remaining > 0:
            time.sleep(RATE_LIMIT_SECONDS)
    return entries


def read_paper_list(path: Path) -> List[str]:
    ids: List[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(line)
    if not ids:
        raise rcpt.BlockedError(f"--paper-list {path} contained no arXiv ids")
    return ids


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch arXiv metadata/content with an L4 receipt.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--ids", nargs="+", metavar="ID", help="explicit arXiv id(s)")
    src.add_argument("--query", help="arXiv search_query string")
    src.add_argument(
        "--paper-list", type=Path, metavar="FILE",
        help="path to a file of arXiv ids, one per line (# comments/blank lines skipped); "
             "for an exact pre-filtered set (e.g. from the bulk metadata harvest) instead of live sampling",
    )
    p.add_argument("--max", type=int, default=50, help="max results for --query mode (default 50)")
    p.add_argument("--what", choices=["meta", "pdf", "source"], default="meta")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/arxiv/<key>)")
    p.add_argument("--license-filter", choices=["cc-only", "all"], default="cc-only")
    p.add_argument("--allow-unverified-license", action="store_true")
    p.add_argument(
        "--budget-bytes", type=int, default=None,
        help="rank-fidelity budget stop for --paper-list content fetch (--what pdf|source): "
             "HEAD-probe each candidate's size in the paper-list file's own declared order, "
             "accumulate, stop at the first candidate that would exceed the budget -- no "
             "skip-and-continue. When a candidate's size can't be established up front (no "
             "Content-Length, HEAD probe fails), it is downloaded under a running budget check "
             "instead (streamed, aborts the instant it would exceed what's left) rather than "
             "stopping blind. Requires --paper-list; ignored for --what meta.",
    )
    p.add_argument(
        "--license-override", dest="license_override", default=None, metavar="URL",
        help="license label to record when the live per-paper arxiv:license Atom element is "
             "UNVERIFIED for a --paper-list candidate whose license was already established "
             "out-of-band (e.g. the OAI-PMH bulk harvest's own <license> element, exact-SPDX "
             "matched). Same hf_fetch.py-style override pattern: fills a genuine gap, never "
             "overrides a live check that actually resolved to something. Must be paired with "
             "--license-override-evidence.",
    )
    p.add_argument(
        "--license-override-evidence", dest="license_override_evidence", default=None, metavar="STR",
        help="required together with --license-override: names the out-of-band source (e.g. "
             "'OAI-PMH bulk harvest <license> element, snapshot <date>, exact-SPDX CC-BY-4.0 match').",
    )
    p.add_argument(
        "--log-file", type=Path, default=None, metavar="FILE",
        help="append the flow-control lifecycle log (startup policy declaration, every retry with "
             "its next-attempt time, per-file progress, terminal error) to FILE in addition to "
             "stdout. Strongly recommended for unattended runs: it is what makes an mtime/staleness "
             "watch and a post-hoc 'did the backoff actually run' check possible.",
    )
    return p


def _content_url(entry: ArxivEntry, what: str) -> str:
    if what == "pdf":
        return f"https://arxiv.org/pdf/{entry.arxiv_id}.pdf"
    return f"https://export.arxiv.org/e-print/{entry.arxiv_id}"


def fetch(args: argparse.Namespace, opener=None) -> Path:
    if args.ids:
        entries = query_by_ids(args.ids, opener)
        key = rcpt.safe_key("-".join(args.ids[:3]) + (f"-plus{len(args.ids)-3}" if len(args.ids) > 3 else ""))
        source_id = ",".join(args.ids)
    elif args.paper_list:
        paper_ids = read_paper_list(args.paper_list)
        entries = query_by_ids(paper_ids, opener)
        key = rcpt.safe_key(args.paper_list.stem)[:60]
        source_id = f"paper-list:{args.paper_list.name} ({len(paper_ids)} ids)"
    else:
        entries = query_by_search(args.query, args.max, opener)
        key = rcpt.safe_key(args.query)[:60]
        source_id = f"query:{args.query}"

    if not entries:
        raise rcpt.BlockedError("no arXiv entries returned for the requested set")

    if args.budget_bytes is not None and not args.paper_list:
        raise rcpt.BlockedError("--budget-bytes requires --paper-list (rank-fidelity order is the file's own order)")

    if (args.license_override is None) != (args.license_override_evidence is None):
        raise rcpt.BlockedError("--license-override and --license-override-evidence must be supplied together")

    def _resolved_license(e: "ArxivEntry") -> "tuple[str, str]":
        # The live Atom API's per-paper arxiv:license element is known-unreliable
        # for entries sourced from the OAI-PMH bulk harvest -- it is frequently
        # absent even for papers the harvest's own <license> element confirms are
        # CC-BY-4.0 (the prior live-per-paper-sampling finding that motivated the
        # bulk-harvest approach in the first place, reconfirmed here for the
        # --paper-list content-fetch path specifically). The override fills that
        # gap; it never substitutes for a live check that actually resolved.
        #
        # Returns (resolved_label, basis) rather than just the label: a
        # live-resolved license and an override-filled one can be the exact
        # same URL string (e.g. both CC-BY-4.0), which would otherwise make
        # the two populations indistinguishable in the receipt -- the basis
        # tag is what lets a reader tell which admission path a given paper
        # actually took.
        if e.license_label == rcpt.UNVERIFIED and args.license_override is not None:
            return args.license_override, "override"
        return e.license_label, "live"

    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "arxiv" / key
    dest_root.mkdir(parents=True, exist_ok=True)

    per_paper_notes = "; ".join(f"{e.arxiv_id}={e.license_label}" for e in entries)
    budget_walk_manifest_path: Optional[Path] = None

    if args.what == "meta":
        meta_path = dest_root / f"meta-{key}.json"
        rcpt.check_no_collision(meta_path)
        import json

        meta_path.write_text(
            json.dumps(
                [
                    {"arxiv_id": e.arxiv_id, "title": e.title, "license": e.license_label, "updated": e.updated}
                    for e in entries
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        files = rcpt.build_file_entries(dest_root, [meta_path.relative_to(dest_root)])
        downloaded_paths = [meta_path]
        license_str = "public (arXiv API metadata only; per-paper licenses in notes)"
        license_evidence = "arXiv API metadata (titles/ids/updated) carries no separate reuse license"
    else:
        # Eligibility must evaluate the RESOLVED (post-override) license, not
        # the pre-override live label: filtering on e.is_cc alone means an
        # override can never rescue a live-UNVERIFIED paper under cc-only,
        # forcing callers to widen to --license-filter all just to exercise
        # the override -- which then also admits live-resolved NON-CC papers,
        # a real license-admission leak. Precedence still holds: the override
        # closure only substitutes when live is UNVERIFIED, so a live-resolved
        # non-CC paper (e.g. the arXiv perpetual label) stays excluded under
        # cc-only even when an override was supplied for it -- live-resolved
        # always wins, a conflict means exclude, not fetch.
        eligible = entries if args.license_filter == "all" else [e for e in entries if _is_cc_url(_resolved_license(e)[0])]
        # A silent collapse here is invisible anywhere else in the run's output --
        # the walk phase only ever sees the post-filter `eligible` list, so a
        # 53,615-candidate pool that collapses to 492 eligible produces a
        # completely clean, zero-error run (WALK-END examined=492 selected=491)
        # with nothing in the log to distinguish "492 really is the whole
        # license-clean population" from "the filter silently ate 99% of the
        # pool" (A-train-2, 2026-08-15). Logged unconditionally (not just when it
        # looks wrong) since the threshold for "suspicious" isn't knowable in
        # general -- a reader comparing this line against the paper-list's own
        # size is the check.
        if args.license_filter != "all":
            live_cc = sum(1 for e in entries if e.is_cc)
            override_rescued = sum(
                1 for e in entries if e.license_label == rcpt.UNVERIFIED and args.license_override is not None
            )
            excluded = len(entries) - live_cc - override_rescued
            log(
                f"ELIGIBILITY-FILTER candidates_in={len(entries)} eligible_out={len(eligible)} "
                f"(live_cc={live_cc}, override_rescued={override_rescued}) excluded={excluded} "
                f"license_filter={args.license_filter}"
            )
        if not eligible:
            raise rcpt.BlockedError(
                f"no license-clean papers eligible for content fetch under --license-filter cc-only "
                f"(use --license-filter all to override); per-paper: {per_paper_notes}"
            )

        budget_note = ""
        streamed_paths: dict = {}  # arxiv_id -> Path, for candidates already fetched during the walk
        declared_sizes: dict = {}  # arxiv_id -> HEAD-declared Content-Length, for the post-download size check below
        if args.budget_bytes is not None:
            # Rank-fidelity: honor the paper-list file's OWN declared order, not
            # the Atom API's response order (not guaranteed to preserve input order).
            # The API's entry ids carry a version suffix (e.g. 2301.00001v2) that
            # the harvest-derived paper-list does not -- match on the stripped
            # (canonical) form on both sides, never the raw entry id.
            order_index = {arxiv_id: i for i, arxiv_id in enumerate(paper_ids)}
            eligible = sorted(eligible, key=lambda e: order_index.get(_strip_version(e.arxiv_id), len(paper_ids)))
            selected: List[ArxivEntry] = []
            walk_notes: List[dict] = []
            cumulative = 0
            head_count = 0
            streamed_count = 0
            examined = 0
            walk_end_reason = "list-exhausted"
            for e in eligible:
                # The walk is otherwise silent for its entire duration (no other
                # log() call in this loop) -- at RATE_LIMIT_SECONDS=3.0/candidate,
                # a multi-thousand-candidate walk can run for HOURS with zero
                # output, indistinguishable from a wedged process to a human or
                # the liveness watch (same lesson as 973ff18's META-BATCH fix for
                # the metadata phase, one stage later in the same pipeline).
                examined += 1
                if examined % WALK_HEARTBEAT_EVERY == 0:
                    log(
                        f"WALK-BATCH examined={examined} selected={len(selected)} "
                        f"cumulative_bytes={cumulative} budget_bytes={args.budget_bytes}"
                    )
                url = _content_url(e, args.what)
                try:
                    size = _head_content_length(url, opener=opener)
                except (urllib.error.HTTPError, urllib.error.URLError, OSError):
                    size = None
                if size is not None:
                    if cumulative + size > args.budget_bytes:
                        walk_notes.append(
                            {"id": e.arxiv_id, "bytes": size, "status": "stopped", "size_source": "head", "reason": "would exceed budget"}
                        )
                        walk_end_reason = f"budget-stop id={e.arxiv_id}"
                        break
                    selected.append(e)
                    cumulative += size
                    head_count += 1
                    declared_sizes[e.arxiv_id] = size
                    walk_notes.append(
                        {"id": e.arxiv_id, "bytes": size, "status": "selected", "size_source": "head", "cumulative_bytes": cumulative}
                    )
                    time.sleep(RATE_LIMIT_SECONDS)
                    continue
                # Size undeterminable up front (no Content-Length, a redirect dropped
                # it, or the HEAD probe itself failed) -- fail-closed via a RUNNING
                # budget check instead of stopping blind on an unknown size: stream
                # the actual content with max_bytes capped to what's left, aborting
                # mid-download the instant it would exceed the remaining budget. Keeps
                # the selected set a pure function of (paper-list, budget), independent
                # of which server mood answered this particular HEAD request.
                remaining_budget = args.budget_bytes - cumulative
                ext = ".pdf" if args.what == "pdf" else ".tar"
                dest_file = dest_root / f"{rcpt.safe_key(e.arxiv_id)}{ext}"
                try:
                    actual_size, _digest = rcpt.download_url(url, dest_file, opener=opener, max_bytes=remaining_budget)
                except rcpt.DownloadTooLargeError:
                    walk_notes.append(
                        {"id": e.arxiv_id, "status": "stopped", "size_source": "streamed",
                         "reason": f"streamed past remaining budget ({remaining_budget} bytes); size undeterminable up front"}
                    )
                    walk_end_reason = f"budget-stop id={e.arxiv_id}"
                    break
                except Exception as exc:
                    # Only budget conditions may end the walk early. A single
                    # permanently-unavailable candidate (dead link, 404, transient
                    # server fault) is NOT a budget condition -- terminating the
                    # entire walk on it silently stranded 7.6GB of unused budget
                    # in A-train-2 (2026-08-15, id=2212.07920v4, real root cause).
                    # Skip this one candidate and keep walking the rest of the list.
                    walk_notes.append(
                        {"id": e.arxiv_id, "status": "skipped", "size_source": "streamed", "reason": f"streamed fetch failed: {exc!r}"}
                    )
                    log(f"WALK-SKIP id={e.arxiv_id} reason={exc!r}")
                    continue
                selected.append(e)
                streamed_paths[e.arxiv_id] = dest_file
                cumulative += actual_size
                streamed_count += 1
                walk_notes.append(
                    {"id": e.arxiv_id, "bytes": actual_size, "status": "selected", "size_source": "streamed", "cumulative_bytes": cumulative}
                )
                time.sleep(RATE_LIMIT_SECONDS)
            eligible = selected
            log(
                f"WALK-END examined={examined} selected={len(eligible)} "
                f"cumulative_bytes={cumulative} budget_bytes={args.budget_bytes} "
                f"end_reason={walk_end_reason}"
            )
            if not eligible:
                raise rcpt.BlockedError(
                    f"rank-fidelity budget stop selected zero candidates under budget_bytes={args.budget_bytes} "
                    f"(first candidate in declared order alone exceeds budget, or its size was undeterminable "
                    f"and streaming it under a running budget check also exceeded budget)"
                )
            try:
                budget_walk_manifest_path = _write_budget_walk_manifest(
                    dest_root, key, args.budget_bytes,
                    order_rule="paper-list file declared order (ascending, as written)",
                    size_rule="HEAD Content-Length where available; else streamed download capped to the "
                              "remaining budget via max_bytes, aborting mid-download on exceed (fail-closed, "
                              "never a blind stop on unknown size)",
                    walk_notes=walk_notes,
                )
            except rcpt.BlockedError:
                # Streamed-under-budget files are already on disk with no receipt
                # to cover them if the manifest write itself fails -- clean them up
                # before re-raising rather than leaving orphans (same posture as
                # lean_fetch.py's own manifest-write-failure cleanup).
                for p in streamed_paths.values():
                    if p.is_file():
                        try:
                            p.unlink()
                        except OSError:
                            pass
                raise
            budget_note = (
                f"; budget_bytes={args.budget_bytes}; candidates_in_list={len(order_index)}; "
                f"examined={len(walk_notes)}; selected={len(eligible)} (via_head={head_count}, via_stream={streamed_count}); "
                f"selected_bytes={cumulative}; "
                f"budget_walk_manifest={budget_walk_manifest_path.relative_to(dest_root).as_posix()}"
            )

        downloaded_paths: List[Path] = []
        progress_total = len(eligible)
        progress_bytes = 0
        progress_started = time.monotonic()
        log(f"FETCH-BEGIN eligible={progress_total} what={args.what} dest_root={dest_root}")
        for e in eligible:
            if e.arxiv_id in streamed_paths:
                # Already fetched during the budget walk under a running budget cap --
                # re-downloading here would both waste a request and hit download_url's
                # own collision check against the file it just wrote.
                downloaded_paths.append(streamed_paths[e.arxiv_id])
                continue
            url = _content_url(e, args.what)
            ext = ".pdf" if args.what == "pdf" else ".tar"
            dest_file = dest_root / f"{rcpt.safe_key(e.arxiv_id)}{ext}"
            declared = declared_sizes.get(e.arxiv_id)
            # A HEAD-selected candidate was charged its declared Content-Length
            # for --budget-bytes accounting -- if the GET actually delivers more,
            # that silently breaks the budget the walk computed the selection
            # against. Cap the download at the declared size so an over-large
            # response aborts mid-stream (DownloadTooLargeError) instead of
            # completing and being kept; a response that completes SMALLER than
            # declared isn't caught by the cap, so it's checked explicitly below.
            try:
                actual_size, _digest = rcpt.download_url(
                    url, dest_file, opener=opener,
                    max_bytes=declared if declared is not None else rcpt.MAX_DOWNLOAD_BYTES,
                )
            except rcpt.DownloadTooLargeError as exc:
                raise HeadSizeMismatchError(
                    f"{e.arxiv_id}: GET exceeded its own HEAD-declared Content-Length "
                    f"({declared} bytes, used for --budget-bytes accounting): {exc}"
                ) from exc
            if declared is not None and actual_size != declared:
                dest_file.unlink()
                raise HeadSizeMismatchError(
                    f"{e.arxiv_id}: HEAD declared Content-Length {declared} bytes (used for "
                    f"--budget-bytes accounting) but the GET delivered {actual_size} bytes -- "
                    f"refusing rather than silently admitting a fetch the budget walk didn't "
                    f"actually account for"
                )
            downloaded_paths.append(dest_file)
            progress_bytes += actual_size
            elapsed = max(time.monotonic() - progress_started, 1e-9)
            log(
                f"PROGRESS n={len(downloaded_paths)}/{progress_total} id={e.arxiv_id} "
                f"bytes={actual_size} cumulative_bytes={progress_bytes} "
                f"elapsed_s={elapsed:.1f} files_per_min={len(downloaded_paths) / elapsed * 60:.2f} "
                f"bytes_per_min={progress_bytes / elapsed * 60:.0f}"
            )
            time.sleep(RATE_LIMIT_SECONDS)
        files = rcpt.build_file_entries(dest_root, [p.relative_to(dest_root) for p in downloaded_paths])
        resolved_by_id = {e.arxiv_id: _resolved_license(e) for e in eligible}
        distinct_licenses = sorted({label for label, _basis in resolved_by_id.values()})
        license_str = distinct_licenses[0] if len(distinct_licenses) == 1 else "cc-mixed (see notes)"
        if args.license_override is not None and any(e.license_label == rcpt.UNVERIFIED for e in eligible):
            license_evidence = (
                f"arxiv:license Atom element where live-resolved; "
                f"--license-override applied where live-UNVERIFIED: {args.license_override_evidence}"
            )
        else:
            license_evidence = "arxiv:license Atom element, per paper (cc-only filter applied)"
        # Notes describe what was actually FETCHED (eligible/selected), never the
        # full --paper-list candidate pool -- a large paper-list must not bloat
        # this receipt's notes field (same bounded-notes discipline as the
        # budget-walk sidecar manifest above, and as lean_fetch.py's own fix).
        # Each entry tags its admission basis (live vs override) -- a
        # live-resolved license and an override-filled one can share the exact
        # same URL string, so the basis tag is the only thing that lets a
        # reader tell the two populations apart.
        per_paper_notes = (
            "; ".join(f"{aid}={label}({basis})" for aid, (label, basis) in resolved_by_id.items()) + budget_note
        )

    # Note: the top-level receipt `license` field above is always a resolved
    # label (a specific CC URL, "cc-mixed", the arXiv-perpetual label, or the
    # metadata-only label) -- never UNVERIFIED -- because unresolved per-paper
    # licenses are excluded from content fetch under the default cc-only
    # filter and are merely listed (with their own UNVERIFIED label) in
    # per-paper notes for meta-only pulls. The --allow-unverified-license flag
    # is still accepted for CLI-contract consistency across connectors and
    # would apply if a future revision surfaces a batch-level UNVERIFIED case.

    receipt = rcpt.Receipt(
        source="arxiv",
        source_id=source_id,
        canonical_url="https://export.arxiv.org/api/query",
        license=license_str,
        license_evidence=license_evidence,
        revision=None,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=f"what={args.what}; license_filter={args.license_filter}; per_paper: {per_paper_notes}",
    )
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    global _LOG_PATH
    args = build_parser().parse_args(argv)
    if args.log_file is not None:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        _LOG_PATH = args.log_file
    # Startup declaration BEFORE the first request: proves from the log alone
    # which policy a live process is running, rather than leaving a reader to
    # infer it from source that may not be what was deployed.
    log(f"START connector={CONNECTOR_NAME} what={args.what} dest={args.dest}")
    log(flow_control_policy_line())

    def _run() -> Path:
        try:
            return fetch(args)
        except BaseException as exc:
            # Terminal path: the log must carry the cause even though run_cli's
            # own BLOCKED line only reaches stdout. TERMINAL is the token the
            # liveness watch greps for to alert immediately rather than waiting
            # for the staleness threshold to expire.
            log(f"TERMINAL {type(exc).__name__}: {exc}")
            raise

    rc = rcpt.run_cli(_run)
    if rc == 0:
        log("DONE receipt committed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
