# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""chunked_download.py -- resumable, HTTP Range-based chunked bulk transport
engine (issue #1440).

`receipt.py`'s `download_url()` is single-shot and capped at 512 MiB
(`MAX_DOWNLOAD_BYTES`) -- fine for individual files, but the corpus program's
bulk sources (Wikipedia XML dumps, PMC OA packages, Stack Exchange 7z dumps,
USPTO bulk grants, ...) are routinely tens of gigabytes. This module is an
entirely separate code path with its own explicit, caller-declared byte
budget: it never touches `MAX_DOWNLOAD_BYTES` and never widens the ordinary
single-fetch cap.

Design summary
---------------
- Transfers are fetched serially, in order, as a sequence of HTTP Range
  requests (`bytes=start-end`). There is no parallelism; resumability and
  auditability were prioritized over throughput.
- The first chunk request doubles as the Range-support probe: any response
  status other than 206 is refused (`RangeNotSupportedError` for the specific
  "server silently sent the whole file" case, `ChunkFetchError` for any other
  unexpected status). A 200 in response to a Range request is never treated
  as data -- accepting it would silently re-read from byte 0 on every
  "chunk", which is exactly the silent-restart failure this module exists to
  prevent.
- The server's `Content-Range: bytes start-end/total` header on that first
  response establishes `total_bytes` for the whole transfer. Every
  subsequent chunk's `Content-Range` is checked against it; any change is a
  `RemoteIdentityChangedError` (the same exception class also covers a
  mid-transfer ETag/Last-Modified flip, when the server supplies those
  headers).
- The number of bytes actually read for a chunk is always compared to the
  length promised by that chunk's own `Content-Range` -- fewer bytes than
  promised (whether the truncated chunk is the last one or not) is a
  `ChunkLengthMismatchError`. This uniformly covers "truncated final chunk"
  without needing a special case.
- Progress is persisted to a `<dest>.bulkstate.json` sidecar after every
  chunk is fsync'd to the `<dest>.partial` file, so a killed process resumes
  from exactly the last durably-committed chunk. On resume, every
  previously-committed chunk's on-disk bytes are re-hashed and checked
  against its recorded sha256 before any new network request is made -- a
  corrupted local partial is refused (`ChunkDigestMismatchError`), never
  silently trusted or silently restarted.
- Disk space is checked (declared budget + margin against the destination
  volume's free space) before any network call. The declared budget is
  checked against the server-reported total before any chunk bytes are
  written to disk.
- On success, the sidecar state file is removed (its job -- enabling resume
  -- is done); the permanent, auditable record is the chunk list returned in
  `BulkFetchResult`, which the caller (`bulk_fetch.py`) writes out as a
  standalone chunk-manifest JSON alongside the standard connector receipt.

Stdlib-only (`urllib.request`, `http.client`), per this package's dependency
posture (see README).
"""
from __future__ import annotations

import http.client
import json
import math
import os
import re
import shutil
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import receipt as rcpt

SCHEMA_STATE = "corpus-bulk-transfer-state-v1"
SCHEMA_CHUNK_MANIFEST = "corpus-bulk-chunk-manifest-v1"

DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MiB
DEFAULT_DISK_MARGIN_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0

_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")


# ---------------------------------------------------------------------------
# Errors -- every one is a rcpt.BlockedError subclass so it composes with the
# existing fail-closed CLI plumbing (rcpt.run_cli prints `BLOCKED <reason>`
# and exits nonzero for any of these). Each name is its own machine-readable
# reason; never one overloaded exception for multiple refusal conditions.
# ---------------------------------------------------------------------------
class RangeNotSupportedError(rcpt.BlockedError):
    """The server did not honour a Range request (responded 200, or a 206
    with no parseable/total-bearing Content-Range)."""


class ChunkFetchError(rcpt.BlockedError):
    """A ranged chunk request got an HTTP status that is neither 206 nor the
    "ignoring Range" 200 case (e.g. 404, 416, 500)."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class BudgetExceededError(rcpt.BlockedError):
    """The remote (or previously-recorded) total size exceeds the caller's
    declared --budget-bytes. The budget is never silently widened."""


class DiskMarginError(rcpt.BlockedError):
    """Free space on the destination volume is below budget + margin."""


class RemoteIdentityChangedError(rcpt.BlockedError):
    """Total size, ETag, or Last-Modified changed between chunk fetches --
    the remote resource was mutated mid-transfer."""


class ChunkLengthMismatchError(rcpt.BlockedError):
    """A chunk response delivered fewer bytes than its own Content-Range
    promised (covers a truncated final chunk and any mid-file truncation)."""


class ResumeStateMismatchError(rcpt.BlockedError):
    """An existing .bulkstate.json does not match this invocation (different
    URL/chunk_size/budget), or a .partial exists with no matching state."""


class PartialFileSizeMismatchError(rcpt.BlockedError):
    """The .partial file's on-disk size does not match what the resume state
    (or the final assembled size) says it should be."""


class ChunkDigestMismatchError(rcpt.BlockedError):
    """A previously-committed chunk's on-disk bytes no longer match its
    receipted sha256 -- the resume is corrupted and must not be trusted."""


class WholeFileDigestMismatchError(rcpt.BlockedError):
    """The assembled file's whole-file sha256 does not match an explicitly
    supplied --sha256."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ChunkRecord:
    index: int
    start: int
    end: int  # inclusive
    bytes: int
    sha256: str
    fetched_at: str

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "fetched_at": self.fetched_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "ChunkRecord":
        return ChunkRecord(
            index=d["index"], start=d["start"], end=d["end"],
            bytes=d["bytes"], sha256=d["sha256"], fetched_at=d["fetched_at"],
        )


@dataclass
class BulkFetchResult:
    dest_file: Path
    total_bytes: int
    sha256: str
    chunk_size: int
    chunks: List[ChunkRecord]
    resumed: bool
    retry_attempts: int = 0
    retry_events: Optional[List[dict]] = None

    def chunk_manifest_dict(self, url: str, budget_bytes: int) -> dict:
        return {
            "schema": SCHEMA_CHUNK_MANIFEST,
            "url": url,
            "dest_file": str(self.dest_file),
            "chunk_size": self.chunk_size,
            "budget_bytes": budget_bytes,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
            "chunk_count": len(self.chunks),
            "resumed": self.resumed,
            "retry_attempts": self.retry_attempts,
            "retry_events": list(self.retry_events or []),
            "chunks": [c.to_dict() for c in self.chunks],
        }


# ---------------------------------------------------------------------------
# Sidecar paths
# ---------------------------------------------------------------------------
def _partial_path(dest_file: Path) -> Path:
    return dest_file.with_name(dest_file.name + ".partial")


def _state_path(dest_file: Path) -> Path:
    return dest_file.with_name(dest_file.name + ".bulkstate.json")


def _write_state(state_path: Path, state: dict) -> None:
    tmp = state_path.with_name(state_path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(state_path)
    except OSError as exc:
        if tmp.exists():
            tmp.unlink()
        raise rcpt.ReceiptWriteError(f"could not write bulk transfer state: {exc}") from exc


def _load_state(state_path: Path) -> Optional[dict]:
    if not state_path.is_file():
        return None
    return json.loads(state_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Disk margin
# ---------------------------------------------------------------------------
def _check_disk_margin(
    target_dir: Path,
    required_bytes: int,
    margin_bytes: int,
    disk_usage_fn: Callable[[str], object],
    context: str = "budget_bytes",
) -> None:
    """Checked once up front against the whole declared budget (context=
    "budget_bytes"), and again before every individual chunk write
    (context="next_chunk_bytes") -- a volume that fills up partway through a
    long transfer must surface as this clean DiskMarginError, not a raw OSError
    out of write()/fsync() several chunks later."""
    probe = target_dir
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    usage = disk_usage_fn(str(probe))
    required = required_bytes + margin_bytes
    if usage.free < required:
        raise DiskMarginError(
            f"free space {usage.free} bytes on {probe} is below required {required} "
            f"({context} {required_bytes} + disk_margin_bytes {margin_bytes})"
        )


# ---------------------------------------------------------------------------
# Content-Range parsing + single-chunk fetch
# ---------------------------------------------------------------------------
def _parse_content_range(value: Optional[str]) -> Tuple[int, int, int]:
    if not value:
        raise RangeNotSupportedError("206 response carried no Content-Range header")
    m = _CONTENT_RANGE_RE.match(value.strip())
    if not m:
        raise RangeNotSupportedError(f"unparseable Content-Range header: {value!r}")
    start_s, end_s, total_s = m.group(1), m.group(2), m.group(3)
    if total_s == "*":
        raise RangeNotSupportedError(
            "server reported an unknown total size (Content-Range: .../*); "
            "a bulk transfer cannot be bounded or completion-detected without it"
        )
    return int(start_s), int(end_s), int(total_s)


def _read_exact(resp, n: int, io_chunk: int = 1 << 20) -> bytes:
    """Read up to n bytes from resp, stopping early (short) on EOF -- whether
    EOF surfaces as an empty read() or as http.client.IncompleteRead."""
    buf = bytearray()
    while len(buf) < n:
        want = min(io_chunk, n - len(buf))
        try:
            piece = resp.read(want)
        except http.client.IncompleteRead as exc:
            buf.extend(exc.partial)
            break
        if not piece:
            break
        buf.extend(piece)
    return bytes(buf)


def _fetch_one_chunk(
    url: str, start: int, end: int, timeout: int, headers: Optional[dict], opener: Optional[Callable]
) -> Tuple[bytes, int, int, Optional[str], Optional[str]]:
    """Issue one Range GET for bytes=start-end (end is a request ceiling; the
    server may clamp it to the resource's actual end). Returns
    (data, resp_end, resp_total, etag, last_modified)."""
    req_headers = {"User-Agent": "ember-corpus-connector/1", "Range": f"bytes={start}-{end}"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, headers=req_headers)
    urlopen = opener or urllib.request.urlopen
    try:
        response_cm = urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # urlopen() raises HTTPError (rather than returning a normal response)
        # for any non-2xx/3xx status by default -- a 404/416/500/etc. answer to
        # a Range request never reaches the status check below unless it is
        # caught here first and turned into the same ChunkFetchError that
        # branch produces. (200 is never raised as an HTTPError -- it is
        # never an error status -- so RangeNotSupportedError's "200 instead of
        # 206" case is unaffected and still handled by the branch below.)
        raise ChunkFetchError(
            f"unexpected HTTP status {exc.code} for Range bytes={start}-{end}",
            status_code=exc.code,
        ) from exc
    with response_cm as resp:
        status = getattr(resp, "status", None)
        if status is None:
            status = resp.getcode()
        if status == 200:
            raise RangeNotSupportedError(
                f"server returned 200 (full content) for a ranged request (Range: "
                f"bytes={start}-{end}) instead of 206 -- Range is not honoured; "
                f"refusing rather than risk silently re-reading from byte 0"
            )
        if status != 206:
            raise ChunkFetchError(
                f"unexpected HTTP status {status} for Range bytes={start}-{end}",
                status_code=status,
            )

        get_header = resp.headers.get if hasattr(resp, "headers") else (lambda *_a, **_kw: None)
        resp_start, resp_end, resp_total = _parse_content_range(get_header("Content-Range"))
        if resp_start != start:
            raise RangeNotSupportedError(
                f"requested Range start {start} but server responded with start "
                f"{resp_start} (Content-Range: {get_header('Content-Range')!r}) -- "
                f"Range is not honoured precisely; refusing"
            )
        # resp_end is server-controlled and must never be trusted past what this
        # request actually asked for (or past what the server's own claimed total
        # allows) BEFORE it drives how many body bytes get read. A server -- hostile
        # or merely broken -- that answers a small requested range with a much larger
        # Content-Range must be refused here, before a single byte of an oversized
        # body is read into memory or written to the .partial file (mirrors
        # receipt.py's download_url(): the ceiling is checked before the write, so
        # overshoot is bounded to one block -- here, one chunk).
        if resp_end < resp_start:
            raise RangeNotSupportedError(
                f"server's Content-Range end {resp_end} is before its own start "
                f"{resp_start} (Content-Range: {get_header('Content-Range')!r}) -- "
                f"malformed range; refusing before reading any body bytes"
            )
        if resp_end > end:
            raise RangeNotSupportedError(
                f"server's Content-Range end {resp_end} exceeds the requested end "
                f"{end} (Content-Range: {get_header('Content-Range')!r}) -- a chunk is "
                f"never trusted past what was actually requested, regardless of what "
                f"the server claims to be sending; refusing before reading a single "
                f"byte of the oversized body"
            )
        if resp_end >= resp_total:
            raise RangeNotSupportedError(
                f"server's Content-Range end {resp_end} is not less than its own "
                f"reported total {resp_total} (Content-Range: "
                f"{get_header('Content-Range')!r}) -- internally inconsistent; "
                f"refusing before reading any body bytes"
            )
        expected_len = resp_end - resp_start + 1
        data = _read_exact(resp, expected_len)
        if len(data) != expected_len:
            raise ChunkLengthMismatchError(
                f"chunk bytes={resp_start}-{resp_end} truncated: expected {expected_len} "
                f"bytes, received {len(data)}"
            )
        etag = get_header("ETag")
        last_modified = get_header("Last-Modified")
        return data, resp_end, resp_total, etag, last_modified


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def fetch_chunked(
    url: str,
    dest_file: Path,
    *,
    budget_bytes: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disk_margin_bytes: int = DEFAULT_DISK_MARGIN_BYTES,
    expected_sha256: Optional[str] = None,
    timeout: int = 60,
    headers: Optional[dict] = None,
    opener: Optional[Callable] = None,
    disk_usage_fn: Optional[Callable[[str], object]] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> BulkFetchResult:
    """Fetch `url` to `dest_file` via resumable HTTP Range chunks, never
    exceeding `budget_bytes`. Raises a BlockedError subclass (see above) on
    any refusal; on success returns a BulkFetchResult and leaves exactly
    `dest_file` on disk (no .partial, no .bulkstate.json)."""
    if budget_bytes <= 0:
        raise rcpt.BlockedError("budget_bytes must be positive")
    if chunk_size <= 0:
        raise rcpt.BlockedError("chunk_size must be positive")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise rcpt.BlockedError("max_retries must be a non-negative integer")
    if (
        not isinstance(backoff_base_seconds, (int, float))
        or isinstance(backoff_base_seconds, bool)
        or not math.isfinite(float(backoff_base_seconds))
        or backoff_base_seconds < 0
    ):
        raise rcpt.BlockedError("backoff_base_seconds must be a non-negative number")

    rcpt.check_no_collision(dest_file)
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    _check_disk_margin(dest_file.parent, budget_bytes, disk_margin_bytes, disk_usage_fn or shutil.disk_usage)

    partial_path = _partial_path(dest_file)
    state_path = _state_path(dest_file)

    chunks: List[ChunkRecord] = []
    total_bytes: Optional[int] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    resumed = False
    retry_attempts = 0
    retry_events: List[dict] = []
    session_created_at = rcpt.utc_now_iso()

    existing_state = _load_state(state_path)
    if existing_state is not None:
        if existing_state.get("schema") != SCHEMA_STATE:
            raise ResumeStateMismatchError(f"unrecognized state schema at {state_path}")
        if existing_state.get("url") != url:
            raise ResumeStateMismatchError(f"resume state at {state_path} is for a different URL")
        if existing_state.get("chunk_size") != chunk_size:
            raise ResumeStateMismatchError(
                f"resume state chunk_size {existing_state.get('chunk_size')} != requested {chunk_size}"
            )
        if existing_state.get("budget_bytes") != budget_bytes:
            raise ResumeStateMismatchError(
                f"resume state budget_bytes {existing_state.get('budget_bytes')} != requested {budget_bytes}"
            )
        if existing_state.get("status") != "in_progress":
            raise ResumeStateMismatchError(
                f"resume state at {state_path} has status {existing_state.get('status')!r}, expected 'in_progress'"
            )
        if not partial_path.is_file():
            raise ResumeStateMismatchError(
                f"resume state exists at {state_path} but partial file {partial_path} is missing"
            )

        chunks = [ChunkRecord.from_dict(c) for c in existing_state.get("chunks", [])]
        total_bytes = existing_state.get("total_bytes")
        etag = existing_state.get("etag")
        last_modified = existing_state.get("last_modified")
        session_created_at = existing_state.get("created_at", session_created_at)

        expected_partial_size = sum(c.bytes for c in chunks)
        actual_partial_size = partial_path.stat().st_size
        if actual_partial_size != expected_partial_size:
            raise PartialFileSizeMismatchError(
                f"partial file {partial_path} is {actual_partial_size} bytes, but resume "
                f"state expects {expected_partial_size} bytes from {len(chunks)} committed chunks"
            )

        # A corrupted resume must never be mistaken for a completed fetch: re-verify
        # every already-committed chunk's on-disk bytes against its receipted digest
        # before trusting any of it (this is a local re-read, not a network re-fetch).
        with partial_path.open("rb") as fh:
            for c in chunks:
                fh.seek(c.start)
                data = fh.read(c.bytes)
                digest = rcpt.sha256_bytes(data)
                if digest != c.sha256:
                    raise ChunkDigestMismatchError(
                        f"chunk {c.index} (bytes {c.start}-{c.end}) in {partial_path} no "
                        f"longer matches its receipted sha256 ({c.sha256}, got {digest}); "
                        f"resume is corrupted -- refusing"
                    )

        if total_bytes is not None and total_bytes > budget_bytes:
            raise BudgetExceededError(
                f"resume state total_bytes {total_bytes} exceeds declared budget_bytes {budget_bytes}"
            )
        resumed = True
    else:
        if partial_path.exists():
            raise ResumeStateMismatchError(
                f"partial file {partial_path} exists with no matching resume state at "
                f"{state_path} -- refusing to guess whether it is safe to reuse; remove "
                f"it manually to start fresh"
            )

    start = sum(c.bytes for c in chunks)
    next_index = len(chunks)
    pf = None
    try:
        if partial_path.exists():
            pf = partial_path.open("r+b")
            pf.seek(0, os.SEEK_END)

        while total_bytes is None or start < total_bytes:
            end = start + chunk_size - 1  # request ceiling; server clamps to its own total
            chunk_retry_attempts = 0
            while True:
                try:
                    data, resp_end, resp_total, resp_etag, resp_last_modified = _fetch_one_chunk(
                        url, start, end, timeout, headers, opener
                    )
                    break
                except Exception as exc:
                    if isinstance(exc, ChunkFetchError):
                        status_code = exc.status_code
                        if status_code is not None and 500 <= status_code <= 599:
                            retry_status = f"http_{status_code}"
                        else:
                            retry_status = None
                    elif isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                        retry_status = "connection_reset"
                    elif isinstance(exc, (TimeoutError, socket.timeout)):
                        retry_status = "timeout"
                    elif isinstance(exc, urllib.error.URLError) and isinstance(
                        exc.reason,
                        (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError, socket.timeout),
                    ):
                        retry_status = (
                            "timeout"
                            if isinstance(exc.reason, (TimeoutError, socket.timeout))
                            else "connection_reset"
                        )
                    else:
                        retry_status = None

                    if retry_status is None or chunk_retry_attempts >= max_retries:
                        raise

                    chunk_retry_attempts += 1
                    retry_attempts += 1
                    retry_events.append(
                        {
                            "chunk_index": next_index,
                            "attempt": chunk_retry_attempts,
                            "status": retry_status,
                        }
                    )
                    sleep_fn(float(backoff_base_seconds) * (2 ** (chunk_retry_attempts - 1)))

            if total_bytes is None:
                total_bytes = resp_total
                if total_bytes > budget_bytes:
                    raise BudgetExceededError(
                        f"remote size {total_bytes} bytes exceeds declared budget_bytes "
                        f"{budget_bytes} for {url}; the bulk budget is never silently widened"
                    )
                etag = resp_etag
                last_modified = resp_last_modified
            else:
                if resp_total != total_bytes:
                    raise RemoteIdentityChangedError(
                        f"remote total size changed mid-transfer: was {total_bytes}, now {resp_total}"
                    )
                if etag is not None and resp_etag is not None and resp_etag != etag:
                    raise RemoteIdentityChangedError(
                        f"ETag changed mid-transfer: was {etag!r}, now {resp_etag!r} -- "
                        f"remote content changed underneath this transfer"
                    )
                if (
                    last_modified is not None
                    and resp_last_modified is not None
                    and resp_last_modified != last_modified
                ):
                    raise RemoteIdentityChangedError(
                        f"Last-Modified changed mid-transfer: was {last_modified!r}, now "
                        f"{resp_last_modified!r} -- remote content changed underneath this transfer"
                    )

            # Re-check disk margin before every chunk write, not just once up front --
            # a multi-hour bulk pull can outlast the volume's free space, and this
            # must surface as a clean DiskMarginError (leaving the .partial + state
            # exactly at the last good chunk, resumable once space frees up) rather
            # than a raw OSError out of write()/fsync() partway through a chunk.
            _check_disk_margin(
                dest_file.parent, len(data), disk_margin_bytes,
                disk_usage_fn or shutil.disk_usage, context="next_chunk_bytes",
            )

            if pf is None:
                pf = partial_path.open("wb")

            pf.write(data)
            pf.flush()
            os.fsync(pf.fileno())

            chunk = ChunkRecord(
                index=next_index, start=start, end=resp_end, bytes=len(data),
                sha256=rcpt.sha256_bytes(data), fetched_at=rcpt.utc_now_iso(),
            )
            chunks.append(chunk)

            _write_state(
                state_path,
                {
                    "schema": SCHEMA_STATE,
                    "url": url,
                    "dest_file": str(dest_file),
                    "chunk_size": chunk_size,
                    "budget_bytes": budget_bytes,
                    "total_bytes": total_bytes,
                    "etag": etag,
                    "last_modified": last_modified,
                    "status": "in_progress",
                    "chunks": [c.to_dict() for c in chunks],
                    "created_at": session_created_at,
                    "updated_at": rcpt.utc_now_iso(),
                },
            )

            start = resp_end + 1
            next_index += 1
    finally:
        if pf is not None:
            pf.close()

    final_size = partial_path.stat().st_size
    if total_bytes is not None and final_size != total_bytes:
        # Terminal failure at the very end of a transfer this code believed was
        # complete -- abandon it (delete both sidecars) exactly like the whole-file
        # digest mismatch below, rather than leave a wrongly-sized .partial (and the
        # disk it occupies) sitting around; a fresh fetch_chunked() call starts clean.
        partial_path.unlink()
        if state_path.exists():
            state_path.unlink()
        raise PartialFileSizeMismatchError(f"assembled file is {final_size} bytes, expected {total_bytes}")

    whole_digest = rcpt.sha256_file(partial_path)
    if expected_sha256 and whole_digest.lower() != expected_sha256.lower():
        # Terminal failure after every chunk individually verified but the whole-file
        # digest still doesn't match the caller's expectation -- abandon the transfer
        # (delete both sidecars) rather than leave a resumable-but-untrusted partial.
        partial_path.unlink()
        if state_path.exists():
            state_path.unlink()
        raise WholeFileDigestMismatchError(f"expected {expected_sha256}, got {whole_digest} for assembled {dest_file}")

    partial_path.replace(dest_file)
    if state_path.exists():
        state_path.unlink()

    return BulkFetchResult(
        dest_file=dest_file,
        total_bytes=total_bytes if total_bytes is not None else final_size,
        sha256=whole_digest,
        chunk_size=chunk_size,
        chunks=chunks,
        resumed=resumed,
        retry_attempts=retry_attempts,
        retry_events=retry_events,
    )
