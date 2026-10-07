"""Issue #2119 (review 64093: "provide the actual scorer caller"): the command-line caller the post-hour scoring step runs after the scorer has written
both arms' scored receipts.

    scored_pair_cli.py --identity IDENTITY.json --entry ENTRY.json --custody receipts/measurement-<run_id> --parent RECEIPTS_ROOT
                       [--arms ARMS.json] [--ruling RULING_ID] [--rows-out ROWS.jsonl]

Order of work (the real order): (1) when `--arms` is given and the custody has no arm-publication.json, write it (`scored_pair_entry.write_arm_publication`:
every digest derived from the files); (2) `scored_pair_entry.finalize_scored_pair` (entry bound to the identity digest, producer, finalizer, verdict,
pending-aware promotion only with `--ruling`). Nothing here takes a binding from the command line: bindings come from the frozen prelaunch entry, per-arm
digests from the publication. `--arms` is a JSON object {"control": null | {published_checkpoint_root, hour_result_path, applied_positions, receipt,
checkpoint_receipt}, "treatment": ...}.

Exit codes: 0 chain completed (promotion attempted or deliberately not), 3 refusal before any write (nothing changed), 4 the promoter refused or failed.
NOT wired into any dispatcher or production flow until the owner's recheck passes and the release authority rules it.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
DEFAULT_PROMOTE_CALLER = Path(os.environ['EMBER_PROMOTE_CALLER']) if os.environ.get('EMBER_PROMOTE_CALLER') else None
for _path in (HERE, ROOT / 'src'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import scored_pair_entry as entry_mod  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _identity(path: Path) -> dict:
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    identity = raw.get('identity', raw) if isinstance(raw, dict) else None
    if not isinstance(identity, dict):
        raise entry_mod.ScoredPairRefusal('the identity file is not a JSON object')
    return identity


def main(argv=None, *, runner=None, promote_caller=None, pending=None, sch=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--entry', required=True, type=Path)
    parser.add_argument('--custody', required=True, type=Path)
    parser.add_argument('--parent', required=True, type=Path)
    parser.add_argument('--arms', type=Path)
    parser.add_argument('--ruling')
    parser.add_argument('--rows-out', type=Path)
    parser.add_argument('--promote-caller', type=Path, default=DEFAULT_PROMOTE_CALLER)
    parser.add_argument('--niko-module-dir', type=Path, default=HERE)
    args = parser.parse_args(argv)
    try:
        identity = _identity(args.identity)
        runner = runner or _load('scored_pair_cli_runner', HERE / 'cia_step_runner.py')
        entry_mod.load_frozen_binding(identity, args.entry)      # a foreign entry refuses before the publication is written
        if args.arms is not None and not (args.custody / entry_mod.PUBLICATION_FILENAME).exists():
            entry_mod.write_arm_publication(args.custody, arms=json.loads(args.arms.read_text(encoding='utf-8')))
        if promote_caller is None and args.promote_caller is None:
            raise entry_mod.ScoredPairRefusal('no promote caller: pass --promote-caller or set EMBER_PROMOTE_CALLER')
        promote_caller = promote_caller or _load('scored_pair_cli_promote_caller', args.promote_caller)
        pending = pending or _load('scored_pair_cli_pending', args.niko_module_dir / 'pending_continuation.py')
        sch = sch or _load('scored_pair_cli_sch', args.niko_module_dir / 'selected_continuation_head.py')
        rows_out = args.rows_out or (args.custody / 'promotion-rows.jsonl')

        def row(**fields):
            with open(rows_out, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(fields, sort_keys=True, default=str) + '\n')

        def promote_fn(spec, *, ruling):
            return promote_caller.promote(spec, pending=pending, sch=sch, row=row, ruling=ruling)

        out = entry_mod.finalize_scored_pair(identity, entry_path=args.entry, custody=args.custody, parent=args.parent, runner=runner,
                                             promote_fn=promote_fn, ruling=args.ruling)
    except (entry_mod.ScoredPairRefusal, entry_mod.producer.ArmProducerRefusal, entry_mod.elig.EligibilityRefusal, OSError, ValueError) as error:
        print(json.dumps({'status': 'REFUSED', 'error': f'{type(error).__name__}: {error}'}, sort_keys=True))
        return 3
    print(json.dumps(out, sort_keys=True, default=str))
    promotion = out['promotion']
    return 4 if isinstance(promotion, dict) and promotion.get('code') not in (0, None) else 0


if __name__ == '__main__':
    sys.exit(main())
