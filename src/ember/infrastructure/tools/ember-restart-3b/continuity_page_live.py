"""Issue #2119 row 8 (live page): regenerate the continuity page from live receipts, and say STALE when an input is missing or old.

The committed page block (`gen_readme_status`) is rendered from the committed snapshot only; the merge gate cannot read the receipts
drive. This module is the page a reader opens where the receipts ARE visible: it reads the live selected head, the newest receipts and the
snapshot, and writes one markdown page. It holds no hand-written fact; every line is a receipt field or a derived comparison.

The page is CURRENT only when ALL hold; otherwise its first line is a red STALE banner naming each failed input, and the snapshot (if
readable) is shown beneath it labelled "last snapshot, NOT current". An old fact is never shown as current:
  1. the snapshot is readable and valid;
  2. the live selected head is readable and equals the snapshot's head;
  3. every named receipt exists and is not newer than the snapshot's `captured_at`;
  4. no source named as ABSENT at capture exists now (a marker, measurement or hold record that appears after the snapshot).

  freshness(...)            -> {'state': 'CURRENT'|'STALE', 'reasons': [...], ...}
  render_live_page(...)     -> markdown text
  generate_live_page(...)   -> writes the page atomically; returns the verdict
  python continuity_page_live.py --snapshot S --receipts-root R --out PAGE [--receipt FILE ...] [--absent FILE ...]   (exit 0 CURRENT, 1 STALE; the page is written either way)

Triggered by `continuity_snapshot_hook.publish_snapshot` (spec key `page_path`) at the same publication boundary that writes the
snapshot, i.e. after the hour-end pointer advance.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import calendar
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

SNAPSHOT_SCHEMA = 'ember-training-continuity-snapshot-v1'   # continuity_snapshot.SNAPSHOT_SCHEMA; a test compares the two
GOVERNANCE_SCRIPTS = Path(__file__).resolve().parents[3] / 'governance' / 'scripts'
BANNER_PREFIX = '> **[RED] STALE - this page is NOT current.**'


def _stamp(epoch: float) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def _parse_stamp(text: str) -> float:
    return float(calendar.timegm(time.strptime(text, '%Y-%m-%dT%H:%M:%SZ')))


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _evaluate(snapshot_path: Path, *, live_head: Callable[[], str], receipt_paths: Iterable[Path],
              absent_paths: Iterable[Path] = ()) -> tuple[dict[str, Any], Any, str | None]:
    """Return (verdict, validated snapshot object or None, content fingerprint of the bytes that were validated or None). Never raises."""
    reasons: list[str] = []
    verdict: dict[str, Any] = {'snapshot_head': None, 'live_head': None, 'captured_at': None, 'newest_receipt_utc': None}
    captured_epoch = None
    validated = None
    fingerprint = None
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
        if not isinstance(snapshot, dict) or snapshot.get('schema_version') != SNAPSHOT_SCHEMA:
            raise ValueError('not a continuity snapshot')
        verdict['snapshot_head'] = snapshot['head_manifest_sha256']
        verdict['captured_at'] = snapshot['captured_at']
        captured_epoch = _parse_stamp(snapshot['captured_at'])
    except Exception as error:  # noqa: BLE001
        reasons.append(f'snapshot missing or unreadable ({type(error).__name__})')
    if captured_epoch is not None:
        # "readable and valid" is the strict loader's answer, not a schema_version string: a snapshot the page cannot render is not current
        try:
            before = _fingerprint(snapshot_path)
            validated = _renderer().load_continuity_status(Path(snapshot_path))
            if _fingerprint(snapshot_path) != before:
                raise ValueError('snapshot changed while it was validated')
            # the head and time that are compared below come from THIS validated object, not from the earlier plain parse
            verdict['snapshot_head'] = validated['head_manifest_sha256']
            verdict['captured_at'] = validated['captured_at']
            captured_epoch = _parse_stamp(validated['captured_at'])
            fingerprint = before
        except Exception as error:  # noqa: BLE001
            validated = None
            reasons.append(f'snapshot failed validation ({type(error).__name__}: {error})')
    try:
        live = live_head()
        if not isinstance(live, str) or not live:
            raise ValueError('empty head')
        verdict['live_head'] = live
    except Exception as error:  # noqa: BLE001
        reasons.append(f'live selected head unreadable ({type(error).__name__})')
    if verdict['snapshot_head'] and verdict['live_head'] and verdict['snapshot_head'] != verdict['live_head']:
        reasons.append(f"snapshot describes head {verdict['snapshot_head']} but the live selected head is {verdict['live_head']}")
    for path in absent_paths:   # named at capture as absent: its appearing means the snapshot's UNKNOWN / no-window answer is no longer the live one
        if os.path.lexists(path):
            reasons.append(f'source appeared after the snapshot: {Path(path).name}')
    newest = None
    for path in receipt_paths:
        try:
            moved = float(int(os.stat(path).st_mtime))   # captured_at has one-second resolution; compare at that resolution
        except OSError:
            reasons.append(f'receipt missing: {Path(path).name}')
            continue
        if newest is None or moved > newest[0]:
            newest = (moved, Path(path).name)
    if newest is not None:
        verdict['newest_receipt_utc'] = _stamp(newest[0])
        if captured_epoch is not None and newest[0] > captured_epoch:
            reasons.append(f'newest receipt {newest[1]} ({_stamp(newest[0])}) is newer than the snapshot captured_at ({verdict["captured_at"]})')
    verdict['state'] = 'STALE' if reasons else 'CURRENT'
    verdict['reasons'] = reasons
    return verdict, validated, fingerprint


def freshness(snapshot_path: Path, *, live_head: Callable[[], str], receipt_paths: Iterable[Path], absent_paths: Iterable[Path] = ()) -> dict[str, Any]:
    """Compare the snapshot with the live head and the newest receipts. Never raises: every unreadable input is a STALE reason."""
    return _evaluate(snapshot_path, live_head=live_head, receipt_paths=receipt_paths, absent_paths=absent_paths)[0]


def _go_stale(verdict: dict[str, Any], reason: str) -> None:
    verdict['state'] = 'STALE'
    verdict['reasons'] = list(verdict['reasons']) + [reason]


def _render_block(validated: Any) -> str:
    gen = _renderer()
    return gen.render_continuity_status_block(validated).rstrip('\n')


def _renderer():
    spec = importlib.util.spec_from_file_location('continuity_page_live_gen_readme_status', GOVERNANCE_SCRIPTS / 'gen_readme_status.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def render_live_page(snapshot_path: Path, verdict: dict[str, Any], *, generated_at: str, block: str | None = None) -> str:
    """Pure formatting: the snapshot facts arrive as `block`, rendered from the object that freshness validated. The file is never re-read here."""
    lines: list[str] = []
    stale = verdict['state'] != 'CURRENT'
    if stale:
        lines.append(f"{BANNER_PREFIX} {'; '.join(verdict['reasons'])}.")
        lines.append('')
    lines.append(f"# Training continuity (live page, generated {generated_at})")
    lines.append('')
    lines.append(f"State: **{verdict['state']}**. Live selected head: `{verdict['live_head']}`. Snapshot head: `{verdict['snapshot_head']}`, "
                 f"captured `{verdict['captured_at']}`. Newest receipt read: `{verdict['newest_receipt_utc']}`.")
    lines.append('')
    if block is None:
        lines.append('No snapshot facts are shown: the snapshot did not load or render.')
        return '\n'.join(lines) + '\n'
    if stale:
        lines.append('## Last snapshot, NOT current (reference only)')
        lines.append('')
    lines.append(block.rstrip('\n'))
    return '\n'.join(lines) + '\n'


def generate_live_page(*, snapshot_path: Path, receipts_root: Path | None, out_path: Path, receipt_paths: Iterable[Path] = (), absent_paths: Iterable[Path] = (),
                       current_head: Callable[[], str] | None = None, now: float | None = None) -> dict[str, Any]:
    """Write `out_path` (atomic replace, LF) and return the verdict. The pointer file is always among the receipts compared."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import selected_continuation_head
    receipts = [Path(path) for path in receipt_paths]
    if current_head is None:
        if receipts_root is None:
            raise ValueError('generate_live_page needs a receipts root or a head reader')
        current_head = lambda: selected_continuation_head.current_head_sha256(Path(receipts_root))  # noqa: E731
    if receipts_root is not None:
        receipts.append(selected_continuation_head.pointer_path(Path(receipts_root)))
    verdict, validated, fingerprint = _evaluate(snapshot_path, live_head=current_head, receipt_paths=receipts, absent_paths=[Path(path) for path in absent_paths])
    block = None
    if validated is not None:
        try:
            block = _render_block(validated)
        except Exception as error:  # noqa: BLE001
            _go_stale(verdict, f'page render failed ({type(error).__name__}: {error})')
    generated_at = _stamp(time.time() if now is None else now)
    text = None
    for _attempt in range(2):
        try:
            # the file must still be the bytes that were validated; a deletion or rewrite after the check is a STALE page, not a CURRENT one
            if fingerprint is not None:
                try:
                    unchanged = _fingerprint(snapshot_path) == fingerprint
                except OSError:
                    unchanged = False
                if not unchanged:
                    raise ValueError('snapshot changed or vanished after it was validated')
            text = render_live_page(snapshot_path, verdict, generated_at=generated_at, block=block)
            break
        except Exception as error:  # noqa: BLE001
            _go_stale(verdict, f'page generation failed ({type(error).__name__}: {error})')
            fingerprint = None            # already stale; the retry formats the red banner without the failed check
            block = None
    if text is None:                      # formatting itself failed twice: write the minimal red page
        text = f"{BANNER_PREFIX} {'; '.join(verdict['reasons'])}.\n"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + '.tmp')
    with open(tmp, 'wb') as stream:
        stream.write(text.encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, out_path)
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--receipts-root', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--receipt', action='append', default=[])
    parser.add_argument('--absent', action='append', default=[], help='a source that did not exist when the snapshot was captured; the page is STALE once it does')
    args = parser.parse_args(argv)
    verdict = generate_live_page(snapshot_path=Path(args.snapshot), receipts_root=Path(args.receipts_root), out_path=Path(args.out),
                                 receipt_paths=[Path(item) for item in args.receipt], absent_paths=[Path(item) for item in args.absent])
    print(json.dumps(verdict, sort_keys=True))
    return 0 if verdict['state'] == 'CURRENT' else 1


if __name__ == '__main__':
    sys.exit(main())
