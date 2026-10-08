"""Issue #2119 clause 1 (production wiring): the governed post-hour step. Every hour's dispatch calls it after the hour and before anything can
promote; it is the only door from an hour's custody to `scored_pair_cli`, so promotion is enforced by the dispatch path instead of being a tool
somebody may or may not run.

    post_hour_promotion_gate.py --identity IDENTITY.json --custody receipts/measurement-<run_id> --parent RECEIPTS_ROOT
                                [--entry ENTRY.json] [--arms ARMS.json] [--ruling RULING_ID]

Paths (each writes one receipt, `post-hour-promotion.json`, atomically, in the custody directory):
* identity is not a JSON object / custody is not a directory / --entry missing for a bound identity: REFUSED, exit 3, nothing written.
* identity has no scored-pair binding (no sha256 `scored_pair_binding_sha256`, or `training_job_purpose` is not RETENTION_ELIGIBLE_EXPERIMENT,
  e.g. a CONTINUE_TRAINING lineage hour): NO_PROMOTION_PATH, exit 5. The hour has no frozen prelaunch entry to score against, so this step never
  promotes it; the selected head moves only by the operator-ruled `promote_with_pending_v1` on a frozen score, as before. The receipt says so.
* bound identity: delegate to `scored_pair_cli.main` with the same arguments; exit code and its one-line JSON are recorded and returned
  (0 chain completed, 3 refusal before any write, 4 promoter refused or failed).
* `--advance-child SHA` (row 20, the declared learning-evidence cadence a8ffe5a5): the chain says which trained child it intends to make the head.
  Before any other path runs, `--score-receipt PATH --score-receipt-sha256 SHA` must name a scorer-v12 receipt whose bytes hash to that digest, whose
  schema is ember-2119-child-episode-nll-v1, scored on the frozen plan 9a6fd054, for exactly that child. Otherwise: CADENCE_REFUSED, exit 6, the receipt
  names every problem, the head stays where it is ("a missing score receipt means no advance"). `--cadence-declaration FILE` additionally requires the
  declaration's bytes to hash to a8ffe5a5.... The receipt records the cadence block on every path. Exit 6 stops the chain like 3 and 4.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECEIPT_FILENAME = 'post-hour-promotion.json'
RECEIPT_SCHEMA = 'ember-post-hour-promotion-gate-v1'
BOUND_PURPOSE = 'RETENTION_ELIGIBLE_EXPERIMENT'
EXIT_REFUSED = 3
EXIT_NO_PROMOTION_PATH = 5
EXIT_CADENCE_REFUSED = 6

# Row 20 (#2119): the frozen learning-evidence cadence declared 2026-10-06 08:57 AM LA; the declaration file is pinned by
# CADENCE_DECLARATION_SHA256 below. "A missing score receipt means no advance." Changing any
# constant below takes a new dated declaration.
CADENCE_DECLARATION_SHA256 = 'a8ffe5a5b35871d5f46f86af0ae16f08e5ea2096371c2d9978cef747fbf86c05'
CADENCE_SCORE_SCHEMA = 'ember-2119-child-episode-nll-v1'
CADENCE_PLAN_SHA256 = '9a6fd05492538593662d9b1e62cc15fd7a19b226d0de386ea4b31dddc8848248'
CADENCE_SCORER_MARKER = 'v12'
_SHA256 = re.compile(r'[0-9a-f]{64}')


def cadence_problems(advance_child: str, score_receipt: Path | None, score_receipt_sha256: str | None, declaration: Path | None = None) -> list[str]:
    """Why a head advance to `advance_child` is refused under the declared cadence (empty list = a scorer-v12 receipt for exactly this
    child, on the frozen plan, whose bytes hash to the digest the caller cites). Every check reads bytes; nothing is taken from the caller's say-so."""
    problems = []
    if not isinstance(advance_child, str) or _SHA256.fullmatch(advance_child) is None:
        return ['the child manifest digest to advance to is not a sha256']
    if declaration is not None:
        try:
            declared = hashlib.sha256(Path(declaration).read_bytes()).hexdigest()
        except OSError as error:
            problems.append(f'the cadence declaration is unreadable: {type(error).__name__}')
        else:
            if declared != CADENCE_DECLARATION_SHA256:
                problems.append('the cadence declaration bytes differ from the frozen declaration (a8ffe5a5...)')
    if score_receipt is None or not isinstance(score_receipt_sha256, str) or _SHA256.fullmatch(score_receipt_sha256) is None:
        problems.append('no scorer-v12 score receipt (path and sha256 are both required): a missing score receipt means no advance')
        return problems
    try:
        raw = Path(score_receipt).read_bytes()
    except OSError as error:
        problems.append(f'the score receipt is unreadable: {type(error).__name__}: a missing score receipt means no advance')
        return problems
    if hashlib.sha256(raw).hexdigest() != score_receipt_sha256:
        problems.append('the score receipt bytes do not hash to the cited sha256')
        return problems
    try:
        receipt = json.loads(raw)
    except ValueError:
        problems.append('the score receipt is not JSON')
        return problems
    bindings = receipt.get('bindings') if isinstance(receipt, dict) else None
    if not isinstance(receipt, dict) or not isinstance(bindings, dict):
        problems.append('the score receipt is not an object with bindings')
        return problems
    if receipt.get('schema') != CADENCE_SCORE_SCHEMA:
        problems.append(f'the score receipt schema is not {CADENCE_SCORE_SCHEMA}')
    if CADENCE_SCORER_MARKER not in str(receipt.get('label', '')).split():
        problems.append(f'the score receipt label does not name scorer {CADENCE_SCORER_MARKER}')
    if bindings.get('episode_plan_sha256') != CADENCE_PLAN_SHA256:
        problems.append('the score receipt was not scored on the frozen plan 9a6fd054')
    if bindings.get('checkpoint_manifest_sha256') != advance_child:
        problems.append('the score receipt scores a different checkpoint than the child to advance to (a twin or branch is never lineage evidence)')
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import continuity_sources
    missing_scores = continuity_sources.scores_problem(receipt)
    if missing_scores is not None:
        problems.append(f'the score receipt carries no scores ({missing_scores}): a header alone is not a measurement')
    return problems


def _write_receipt(custody: Path, body: dict) -> None:
    target = custody / RECEIPT_FILENAME
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(dict(body, schema=RECEIPT_SCHEMA), sort_keys=True, indent=1, default=str) + '\n', encoding='utf-8', newline='\n')
    os.replace(temporary, target)


def _refuse(message: str) -> int:
    print(json.dumps({'status': 'REFUSED', 'error': message}, sort_keys=True))
    return EXIT_REFUSED


def main(argv=None, *, cli_main=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--custody', required=True, type=Path)
    parser.add_argument('--parent', required=True, type=Path)
    parser.add_argument('--entry', type=Path)
    parser.add_argument('--arms', type=Path)
    parser.add_argument('--ruling')
    parser.add_argument('--advance-child', help='sha256 of the trained child the chain intends to make the selected head; turns on the row 20 cadence check')
    parser.add_argument('--score-receipt', type=Path, help='the hour\'s scorer-v12 score receipt (cadence item 5)')
    parser.add_argument('--score-receipt-sha256')
    parser.add_argument('--cadence-declaration', type=Path, help='the frozen cadence declaration file; its bytes must hash to a8ffe5a5...')
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.identity.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        return _refuse(f'the identity file is unreadable: {type(error).__name__}: {error}')
    identity = raw.get('identity', raw) if isinstance(raw, dict) else None
    if not isinstance(identity, dict):
        return _refuse('the identity file is not a JSON object')
    if not args.custody.is_dir():
        return _refuse('the custody path is not a directory')
    cadence = {'requested': False}
    if args.advance_child is not None:
        problems = cadence_problems(args.advance_child, args.score_receipt, args.score_receipt_sha256, args.cadence_declaration)
        cadence = {'requested': True, 'advance_child': args.advance_child, 'score_receipt': str(args.score_receipt) if args.score_receipt else None,
                   'score_receipt_sha256': args.score_receipt_sha256, 'problems': problems}
        if problems:
            _write_receipt(args.custody, {'status': 'CADENCE_REFUSED', 'cadence': cadence,
                                          'reason': 'the declared cadence (a8ffe5a5) requires a scorer-v12 receipt for this child before any head advance; the head stays where it is'})
            print(json.dumps({'status': 'CADENCE_REFUSED', 'problems': problems}, sort_keys=True))
            return EXIT_CADENCE_REFUSED
    purpose = identity.get('training_job_purpose')
    binding = identity.get('scored_pair_binding_sha256')
    bound = purpose == BOUND_PURPOSE and isinstance(binding, str) and re.fullmatch(r'[0-9a-f]{64}', binding) is not None
    if not bound:
        _write_receipt(args.custody, {
            'status': 'NO_PROMOTION_PATH', 'cadence': cadence, 'training_job_purpose': purpose, 'scored_pair_binding_present': isinstance(binding, str),
            'reason': 'no frozen scored-pair prelaunch binding on this identity; this step never promotes it. The selected head moves only by the '
                      'operator-ruled promote_with_pending_v1 on a frozen score.'})
        print(json.dumps({'status': 'NO_PROMOTION_PATH', 'training_job_purpose': purpose}, sort_keys=True))
        return EXIT_NO_PROMOTION_PATH
    if args.entry is None:
        return _refuse('a bound identity needs --entry (the frozen prelaunch entry)')
    cli_argv = ['--identity', str(args.identity), '--entry', str(args.entry), '--custody', str(args.custody), '--parent', str(args.parent)]
    if args.arms is not None:
        cli_argv += ['--arms', str(args.arms)]
    if args.ruling:
        cli_argv += ['--ruling', args.ruling]
    if cli_main is None:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import scored_pair_cli
        cli_main = scored_pair_cli.main
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = cli_main(cli_argv)
    text = captured.getvalue().strip()
    try:
        outcome = json.loads(text.splitlines()[-1]) if text else None
    except ValueError:
        outcome = {'unparsed_output_tail': text[-300:]}
    _write_receipt(args.custody, {'status': 'DELEGATED', 'cadence': cadence, 'scored_pair_cli_exit': code, 'ruling': args.ruling or None, 'outcome': outcome})
    print(text)
    return code


if __name__ == '__main__':
    sys.exit(main())
