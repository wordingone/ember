# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# Hour preparer moved into the repo for `ember-lab resume` (source sha256 97277b54c3e8fd37, operator names and the
# hard-coded headless-helper path removed). Changes: --hidden-helper is an explicit, sha-bound argument;
# --resume-identity makes the image slot come from resume_identity.py's derivation and refuses any
# --image-text-manifest that disagrees with it; EMBER_RUN_CERTIFICATE_SHA256 is on the worker env allowlist.
"""Prepare one v5 CIA measurement packet; never start or dispatch a process cohort.

Run only under the operator's bounded headless Python envelope. Preparation reads
the complete bound corpus and queries GPU identity, but allocates no model.
Public merge verification and resource ownership remain execution prerequisites.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import purpose_binding  # noqa: E402

sys.dont_write_bytecode = True
GIB = 1024 ** 3
MAX_METADATA = 512 * 1024

# Arm-selection variables are passed through to the governed worker ONLY when both exported in the
# dispatching shell AND listed here -- a variable absent from this list never reaches the manifest,
# which makes the arm INERT inside the very measurement meant to score it while every mode string
# still says it was selected. Every new arm flag adds its name here in the same change that adds
# the flag itself. Recurred 2026-09-28 after EMBER_FUSED_LOGIT_WIDEN's own
# 2026-09-22 incident: EMBER_BACKWARD_HOLDOFF and its counter path were exported by every leg of the
# gate-ab-engine-thread treatment pair and dropped here, so the worker ran with the mechanism off
# while its own receipt said enabled=True. Auditing every EMBER_* export in dispatch_a1_hour.sh and
# the two backward-holdoff dispatch wrappers against this list found a SECOND, independent instance
# of the same class in the same audit: EMBER_STAGE_OPTIMIZER_OVERLAP, a real cia_step_runner.py flag
# exported by both legs of this same pair, never allowlisted, never read anywhere. Both are added
# below. apply_arm_env_allowlist() is the single source of truth for both the pass-through and the
# class-kill refusal, so they cannot drift out of sync the way the old tuple-plus-nothing-else shape
# did.
ARM_ENV_ALLOWLIST = (
    # 2026-09-29: stochastic-rounding AdamW (default OFF; key and parent rounding are required, no defaults).
    'EMBER_OPT_SR', 'EMBER_OPT_SR_KEY', 'EMBER_OPT_SR_PARENT_ROUNDING',
    'EMBER_FP16_ACCUM', 'EMBER_FP16_ACCUM_EXPERTS', 'EMBER_FP8_LINEAR',
    'EMBER_FP8_DELAYED_SCALE', 'EMBER_FP8_MIN_GEMM_ELEMENTS',
    'EMBER_FP8_CALIBRATION_CALLS', 'EMBER_PARAM_LAYOUT_DB',
    'EMBER_FUSED_LOGIT_WIDEN', 'EMBER_MERGED_KV',
    'EMBER_FP8_GROUPED', 'EMBER_SKIP_KEEP', 'EMBER_SKIP_KEEP_FFN',
    'EMBER_SKIP_KEEP_EXPERT', 'EMBER_MAX_POSITIONS', 'EMBER_MICRO_DOCUMENTS',
    # 2026-09-24: the governed 1,024 that cleared 80k ran with these three; the hour must too.
    'EMBER_PACK_LOOKAHEAD', 'EMBER_STAGE_OWNER_IDENTITY', 'EMBER_STAGE_NEXT_STEP',
    # 2026-09-25: host-stall and checkpoint-reverify treatments.
    'EMBER_SWITCH_INTERVAL_S', 'EMBER_GC_GEN0', 'EMBER_CIA_PARENT_MEMO',
    'EMBER_PRELAUNCH_FORWARD', 'EMBER_DEFERRED_VERDICT', 'EMBER_GC_DISABLE_MEASURED',
    'EMBER_SEGMENT_OPTIMIZER', 'EMBER_DECODE_TWO_AHEAD', 'EMBER_STAGE_AFTER_OPTIMIZER',
    'EMBER_HOST_PRIORITY', 'EMBER_LEAK_PROBE',
    # 2026-09-26: answer-target loss weight (gate D treatment).
    'EMBER_ANSWER_WEIGHT',
    # 2026-09-28: gate-ab-engine-thread backward-holdoff pair, plus the same-day
    # EMBER_STAGE_OPTIMIZER_OVERLAP recovery (both found by this fix's own audit, see above).
    'EMBER_BACKWARD_HOLDOFF', 'EMBER_BACKWARD_HOLDOFF_COUNTER_PATH', 'EMBER_STAGE_OPTIMIZER_OVERLAP',
    # 2026-09-28: gate-D caption-truncation cure probe -- added in the SAME
    # change as the allowlist fix itself, per the operator explicit instruction, so this probe flag never
    # repeats the exact defect this change exists to kill.
    'EMBER_ANSWER_CAPTION_TOKENS',
    # 2026-09-28: bounded governed-path profiler window, measured steps 4-9; default off,
    # no training or throughput qualification credit from a run carrying it.
    'EMBER_GOVERNED_PROFILE_SIX',
    # 2026-09-29: successor supervision + plan-row cap: full-prompt loss switch and the group-plan row cap.
    'EMBER_FULL_PROMPT_LOSS', 'EMBER_GROUP_PLAN_MAX_ROWS',
    # 2026-09-29: amendment 20 paired-contrast recipe: quad image-first stream and L_pair.
    'EMBER_QUAD_IMAGE_FILL', 'EMBER_PAIR_LOSS',
    # 2026-09-29: lookahead bit-identity proof legs: stop a learning comparison at N updates.
    'EMBER_LEARNING_STOP_AT', 'EMBER_DEFER_READBACK', 'EMBER_EARLY_PREFETCH', 'EMBER_WRAPPER_TIMERS', 'EMBER_PAIR_LOSS_MODE',
    # 2026-09-29: default-off pack kick and hour-only digest removal.
    'EMBER_PACK_KICK', 'EMBER_HOUR_DIGEST_OFF',
    # 2026-09-29: sequential FP32 optimizer shadow, learning proof leg only.
    'EMBER_OPT_SHADOW',
    # 2026-10-01: stem-preserving caption carrier matched-arm settings: pair count and image row offset.
    'EMBER_PAIRS_PER_DOCUMENT', 'EMBER_IMAGE_ROW_START',
    # 2026-11-09: archived-ancestor attestation (lead ruling 82046 (c)). The worker's end-of-hour child receipt
    # (cia_hour.verify_checkpoint_restore) reopens the whole chain with no operation open; without this name the
    # variable never reaches the worker and the hour trains for 33 minutes then dies at the closure check (H44 v2).
    'EMBER_CIA_ANCESTOR_CUSTODY_DIR',
)

# EMBER_* variables legitimately exported in the calling shell for orchestration this preparer (or
# its direct caller, dispatch_a1_hour.sh) reads by a different path -- never meant to reach the
# worker manifest through ARM_ENV_ALLOWLIST, so they are exempt from the class-kill refusal below.
KNOWN_NON_ARM_EMBER_VARS = frozenset((
    'EMBER_LOOP_HYP',              # read by dispatch_a1_hour.sh before this preparer is invoked
    'EMBER_ARM_ROOT',              # read by dispatch_a1_hour.sh before this preparer is invoked
    'EMBER_HEAD',                  # read by dispatch_a1_hour.sh before this preparer is invoked
    'EMBER_TRAINING_JOB_PURPOSE',  # passed through as --training-job-purpose, not manifest env
    'EMBER_GATE_AUTHORIZED',       # fixed key this script sets unconditionally into env
    'EMBER_GPU_LOCK_PATH',         # fixed key this script sets unconditionally into env
    'EMBER_SEAT',                  # seat identity; gpu_window.sh open --hypothesis requires it, not an arm flag
    # GitHub App credentials, Windows MACHINE-level env vars (confirmed via
    # [Environment]::GetEnvironmentVariable(...,'Machine')) -- present in every process on this
    # host regardless of dispatch shell, not arm-selection flags. Found by the red test itself:
    # without this exemption every real dispatch would refuse on an unrelated cause.
    'EMBER_GH_APP_ID', 'EMBER_GH_INSTALLATION_ID', 'EMBER_GH_PRIVATE_KEY_PATH',
))


def apply_arm_env_allowlist(env):
    """Pass through every allowlisted EMBER_* arm flag set in the calling shell into `env` (mutated
    in place), then refuse -- naming every offender -- if any EMBER_* variable is exported that is
    neither allowlisted nor a known non-arm orchestration variable. This is the single code path for
    both halves of the mechanism so they cannot drift apart the way the pre-2026-09-28 shape did."""
    for _arm in ARM_ENV_ALLOWLIST:
        if os.environ.get(_arm) is not None:
            env[_arm] = os.environ[_arm]
    _allowed_ember_names = frozenset(ARM_ENV_ALLOWLIST) | KNOWN_NON_ARM_EMBER_VARS
    _unlisted_ember_vars = sorted(
        name for name in os.environ
        if name.startswith('EMBER_') and name not in _allowed_ember_names
    )
    if _unlisted_ember_vars:
        raise ValueError(
            'REFUSE unlisted EMBER_* variable(s) exported and would be dropped from the governed '
            'manifest, never reaching the worker: ' + ', '.join(_unlisted_ember_vars) +
            '. Add each to ARM_ENV_ALLOWLIST (or KNOWN_NON_ARM_EMBER_VARS if it is genuinely '
            'orchestration-only) in the same change that adds its flag.'
        )


def declared_layer_template(text, governed):
    """The hour identity's layer declaration ({mode: full} or keep sets). A governed hour without one is refused here, in preparation."""
    if text is None:
        if governed:
            raise ValueError('governed-hour-v1 preparation requires --layer-template (full or keep sets); the launcher refuses an identity without it')
        return None
    if text == 'full':
        return {'mode': 'full'}
    return json.loads(text)


def declared_hour_wall(text, governed):
    """The hour identity's declared wall (seconds), an exact integer string. Absent keeps today's behaviour (the field is omitted)."""
    if text is None:
        return None
    if not governed:
        raise ValueError('--hour-wall-seconds applies to governed-hour-v1 preparation only')
    if not re.fullmatch(r'[0-9]+', text):
        raise ValueError('--hour-wall-seconds must be an exact integer')
    return int(text)


def checked_declared_cursor(data, parent_cursor):
    """(H19 cursor finding). The mixture plan's declared data.cursor must be PRESENT and well formed, and for a chained hour it must equal the parent checkpoint's own
    data_cursor. Neither value is substituted for the other: the parent's cursor used to overwrite the declared one silently, so the hour trained from a cursor the mixture
    identity never named. Returns the declared cursor on success; raises ValueError otherwise."""
    declared = data.get('cursor')
    if (not isinstance(declared, dict) or set(declared) != {'shard_index', 'token_offset'}
            or isinstance(declared['shard_index'], bool) or isinstance(declared['token_offset'], bool)
            or not isinstance(declared['shard_index'], int) or not isinstance(declared['token_offset'], int)):
        raise ValueError(f'mixture plan data.cursor is absent or malformed: {declared!r}')
    if parent_cursor is not None and (declared['shard_index'], declared['token_offset']) != (int(parent_cursor['shard_index']), int(parent_cursor['token_offset'])):
        raise ValueError(
            f'mixture plan data.cursor {declared} differs from the parent checkpoint data_cursor {parent_cursor}; '
            'neither is substituted for the other')
    return declared


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_METADATA:
        raise ValueError('input metadata exceeds bound')
    with path.open('rb') as stream:
        raw = stream.read(MAX_METADATA + 1)
    if len(raw) > MAX_METADATA:
        raise ValueError('input metadata exceeds bound')
    return json.loads(raw)


def check_image_slot(identity, manifest):
    """Resume binds the image slot from the identity's resume_derivation only; a disagreeing flag is refused."""
    slot = identity['resume_derivation']['image_slot']['image_text']
    if slot is None and manifest is not None:
        raise ValueError('the resume identity runs this hour text-only; --image-text-manifest is refused')
    if slot is not None and (manifest is None or hashlib.sha256(Path(manifest).resolve(strict=True).read_bytes()).hexdigest() != slot['manifest_sha256']):
        raise ValueError('--image-text-manifest differs from the resume identity image slot')


def hidden_run(command):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return subprocess.run(command, check=True, text=True, capture_output=True,
                          timeout=20, shell=False, startupinfo=startup,
                          creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()


def canonical_directory(path):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                               wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0, 7, None, 3, 0x02000000, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError('cannot open custody directory identity')
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not 0 < length < len(buffer):
            raise OSError('cannot resolve custody directory identity')
        return buffer.value
    finally:
        kernel.CloseHandle(handle)


def resolve_continuation_parent(explicit_parent_checkpoint, receipts_root, digest, read_json,
                                 selected_continuation_head, allow_genesis):
    """Issue #2119 section 5 restart: when explicit_parent_checkpoint is None, derive the parent
    from the selected-continuation-head pointer instead of defaulting to a zero-parent bootstrap.
    When explicit_parent_checkpoint IS given, it must name exactly the checkpoint the pointer
    currently selects, or this refuses -- an explicit flag that silently diverged from the
    lineage pointer is exactly the class of mistake a compare-and-swap pointer exists to catch.
    GENESIS (no pointer ever written) never equals a real sha256, so an explicit flag is always
    refused while the pointer is unset.

    issue #2119 s5 REDO (operator-caught defect): an unset pointer with no explicit flag used to
    fall back to a zero-parent bootstrap unconditionally. That silently restarts a lineage from
    genesis -- wrong for this tool's actual live lineage, which already has trained children and
    whose pointer had simply never been written. Zero-parent is never a default now: at GENESIS,
    this refuses unless `allow_genesis` is explicitly True (the preparer's --from-genesis flag),
    naming the seed command as the correct next step for a lineage with real history. The lawful
    path to continue an existing, unseeded lineage is
    `python selected_continuation_head.py seed ...` first, not this flag.

    Pure with respect to argparse, git and the GPU: takes an already-resolved digest function
    and read_json helper, and the already-imported selected_continuation_head module, so it is
    unit-testable directly against real temp-directory fixtures rather than a mock.

    Returns (chain, cursor): chain is None or {'root', 'manifest_sha256'} (the value to bind at
    identity['parent_checkpoint']); cursor is None or {'shard_index', 'token_offset'} (to merge
    into the dispatch's data['cursor']). Raises ValueError on disagreement, staleness, or an
    unseeded genesis without allow_genesis, leaving nothing written.
    """
    receipts_root = Path(receipts_root)
    pointer_sha256 = selected_continuation_head.current_head_sha256(receipts_root)
    if explicit_parent_checkpoint is not None:
        parent_root = Path(explicit_parent_checkpoint).resolve(strict=True)
        explicit_sha256 = digest(parent_root / 'checkpoint-manifest.json')
        if explicit_sha256 != pointer_sha256:
            raise ValueError(
                '--parent-checkpoint disagrees with the selected continuation head: explicit '
                f'checkpoint manifest digest {explicit_sha256!r}, pointer digest '
                f'{pointer_sha256!r}'
            )
        parent_manifest = read_json(parent_root / 'checkpoint-manifest.json')
        pc = parent_manifest['data_cursor']
        cursor = dict(shard_index=int(pc['shard']), token_offset=pc['record_index'])
        return dict(root=str(parent_root), manifest_sha256=explicit_sha256), cursor
    if pointer_sha256 == selected_continuation_head.GENESIS_SENTINEL:
        if not allow_genesis:
            raise ValueError(
                'the selected continuation head has never been set and --parent-checkpoint was '
                'not given -- a lineage with real trained history is never silently restarted '
                'from genesis. Seed the pointer first (python selected_continuation_head.py '
                'seed --root ... --receipts-root ... --checkpoint ... --hour-result ... '
                '--reason ...), or pass --from-genesis to confirm this dispatch is a deliberate '
                'zero-parent bootstrap.'
            )
        return None, None
    pointer = selected_continuation_head.load_selected_continuation_head(
        selected_continuation_head.pointer_path(receipts_root))
    parent_root = (Path(pointer['hour_result_path']).parent / 'trained-child').resolve(strict=True)
    # Re-derive from disk rather than trusting the pointer's own stored digest -- the same
    # "never trust the caller" discipline selected_continuation_head.py applies to itself,
    # applied a second time here since bytes on disk could have moved since the pointer last
    # advanced.
    derived_sha256 = digest(parent_root / 'checkpoint-manifest.json')
    if derived_sha256 != pointer_sha256:
        raise ValueError(
            'selected continuation head pointer is stale: pointer names manifest digest '
            f'{pointer_sha256!r}, the checkpoint on disk at {parent_root} is '
            f'{derived_sha256!r}'
        )
    parent_manifest = read_json(parent_root / 'checkpoint-manifest.json')
    pc = parent_manifest['data_cursor']
    cursor = dict(shard_index=int(pc['shard']), token_offset=pc['record_index'])
    return dict(root=str(parent_root), manifest_sha256=derived_sha256), cursor


def resolve_continuation_parent_or_legacy(parent_checkpoint, custody_root, selected_continuation_head,
                                           training_continuity_ledger, digest, read_json, from_genesis):
    """Issue #2119 s5 (team-lead fix, 2026-09-28): dispatch to resolve_continuation_parent when
    the source tree ships the selected-continuation-head pointer, or to the pre-#2119 legacy
    explicit-parent contract when it does not -- every #1945 arm worktree today is a pre-#2119
    head carrying neither selected_continuation_head nor training_continuity_ledger, and an
    unconditional import of either raised ModuleNotFoundError at hour preparation and refused a
    live profiling leg. Extracted verbatim from main()'s inline branch (byte-for-byte the same
    statements) so it is testable directly rather than only through a full CLI invocation;
    resolve_continuation_parent itself is unchanged by this extraction.

    Legacy contract (selected_continuation_head is None): --from-genesis refuses outright (it
    names a source tree that ships the pointer, and this tree does not); an explicit
    --parent-checkpoint binds chain and cursor straight from its own manifest with no pointer
    comparison at all, because there is no pointer to compare against; omitting it gives a zero
    parent -- the pre-#2119 default this tool always had on these worktrees.
    """
    if selected_continuation_head is None:
        if from_genesis:
            raise ValueError('--from-genesis needs a source tree that ships the selected continuation head')
        chain = cursor = None
        if parent_checkpoint is not None:
            parent_root = Path(parent_checkpoint).resolve(strict=True)
            pc = read_json(parent_root / 'checkpoint-manifest.json')['data_cursor']
            chain = dict(root=str(parent_root), manifest_sha256=digest(parent_root / 'checkpoint-manifest.json'))
            cursor = dict(shard_index=int(pc['shard']), token_offset=pc['record_index'])
        return chain, cursor
    # custody_root is the dispatch custody (<receipts root>/<dispatch>); the runner's
    # custody is one level below it (<dispatch>/measurement-*) and calls ledger_root(custody.parent),
    # i.e. ledger_root(<dispatch>). Passing <dispatch>.parent here resolved one level too high (the drive's work root)
    # and read the pointer as never set.
    receipts_root = training_continuity_ledger.ledger_root(Path(custody_root))
    return resolve_continuation_parent(parent_checkpoint, receipts_root, digest, read_json,
                                        selected_continuation_head, from_genesis)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--expected-source-sha', required=True)
    parser.add_argument('--custody', type=Path, required=True)
    parser.add_argument('--mixture-plan', type=Path, required=True)
    parser.add_argument('--mixture-sha256', required=True)
    parser.add_argument('--seed', type=int, required=True)
    purpose_binding.add_arguments(parser)
    parser.add_argument('--support-experts', type=int, nargs='+', required=True)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--batch-documents', choices=('true', 'false'), required=True)
    parser.add_argument('--expected-step-seconds', type=float, required=True)
    parser.add_argument('--basis', required=True)
    parser.add_argument('--execution-mode', choices=('resident-segmented-capture', 'resident-dynamic-capture'))
    parser.add_argument('--arm', required=True, choices=('control', 'treatment'))
    parser.add_argument('--probe', action='store_true')
    # #1945 A1 section 9: the 16,384-update learning comparison (cia_hour.LEARNING_SNAPSHOTS) on the A1 mixture.
    parser.add_argument('--learning', action='store_true')
    parser.add_argument('--image-text-manifest', type=Path)
    # Resume: the image slot is resume_derivation.image_slot of this mixture identity, never a flag or env default.
    parser.add_argument('--resume-identity', type=Path)
    parser.add_argument('--hidden-helper', type=Path, required=True)
    # Host layout (formerly literals): the GPU lock file, and the system and data volume roots the reserves guard.
    parser.add_argument('--gpu-lock-path', type=Path, required=True)
    parser.add_argument('--system-volume-root', required=True)
    parser.add_argument('--data-volume-root', required=True)
    # #1945 gate D full-answer-context: the frozen group plan is part of the TRAINING image-text binding (data block),
    # so it reaches the frozen manifest, the worker and the input identity; it is never a process-level setting.
    parser.add_argument('--group-plan', type=Path)
    parser.add_argument('--group-plan-sha256')
    parser.add_argument('--continuation-hour-result', type=Path)
    parser.add_argument('--local-routing-mode', choices=('per-chunk', 'batched'))
    parser.add_argument('--checkpoint-probe', type=Path)
    # Chained start: the hour trains FROM this admitted checkpoint; the data cursor is the checkpoint's own.
    parser.add_argument('--parent-checkpoint', type=Path)
    # issue #2119 s5 REDO: an unset selected-continuation-head pointer refuses by default rather
    # than silently falling back to a zero-parent bootstrap. This confirms a deliberate,
    # from-scratch dispatch; the ordinary path for an existing but unseeded lineage is
    # `python selected_continuation_head.py seed ...`, not this flag.
    parser.add_argument('--from-genesis', action='store_true',
                         help='confirm a deliberate zero-parent bootstrap when the selected '
                              'continuation head has never been set; refused by default')
    parser.add_argument('--resident-capacity', type=int)
    parser.add_argument('--allocator-gib', type=float)
    parser.add_argument('--training-head', choices=('native', 'cce-document-v1', 'saved-bf16-logprob-document-v1'))
    # One plan file shared by the checkpoint probe and the hour: validate_probe_inputs requires the two
    # identities' experiment_plan bindings to be EQUAL, so the path and bytes must be the same. Its geometry
    # carries only documents_per_step and sequence_length (all the runner joins), not measured_steps.
    parser.add_argument('--experiment-plan-path', type=Path)
    parser.add_argument('--hour-wall-seconds', help='exact integer; the runner accepts 5,657..7,200 for governed-hour-v1; absent keeps the 5,656 default')
    parser.add_argument('--layer-template', help='"full", or JSON {"mode": "full"} or {"attention_keep": "...", "ffn_keep": "...", "expert_keep": "..."}; required for governed-hour-v1')
    args = parser.parse_args()
    if os.name != 'nt':
        raise ValueError('Windows canonical custody preparation is required')
    if args.resident_capacity is not None or args.allocator_gib is not None:
        raise ValueError('this helper supports the fixed runner contract only; capacity knobs require an explicitly reviewed runner API adapter')
    root = args.root.resolve(strict=True)
    custody = args.custody.resolve(strict=True)
    if custody.drive.upper() != 'B:' or not custody.is_dir():
        raise ValueError('custody must be an existing B directory')
    if not re.fullmatch('[0-9a-f]{40}', args.expected_source_sha):
        raise ValueError('expected source SHA must be an explicit full git commit')
    def check_source():
        if hidden_run(['git', '-C', str(root), 'rev-parse', 'HEAD']) != args.expected_source_sha:
            raise ValueError('checkout does not match expected source SHA')
        if hidden_run(['git', '-C', str(root), 'status', '--porcelain']):
            raise ValueError('checkout is dirty')
    check_source()
    sys.path.insert(0, str(root / 'src'))
    sys.path.insert(0, str(root / 'src/ember/infrastructure/tools/ember-restart-3b'))
    # Issue #2119 section 5: the durable selected-continuation-head pointer, imported (never
    # reimplemented) so this preparer can derive --parent-checkpoint from it, or check an
    # explicit flag against it. Plain top-level imports, matching the convention this repo
    # already uses for same-directory sibling modules once their directory is on sys.path.
    # The pointer is a property of the SOURCE TREE being dispatched: a pre-#2119 head (every #1945 arm
    # worktree today) carries neither module, and its dispatch keeps the explicit-parent contract it
    # was measured under. Only a tree that ships the pointer is held to it.
    try:
        import selected_continuation_head
        import training_continuity_ledger
    except ModuleNotFoundError:
        selected_continuation_head = training_continuity_ledger = None
    entry = root / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
    spec = importlib.util.spec_from_file_location('cia_measurement_preparation_subject', entry)
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)
    if runner.ROOT.resolve() != root:
        raise ValueError('runner root differs')
    digest = runner.file_sha256
    if args.probe and args.learning:
        raise ValueError('a checkpoint probe is not a learning comparison')
    selector = dict(hour=dict(schema='checkpoint-probe-v1' if args.probe else 'learning-comparison-v1' if args.learning
                              else 'governed-hour-v1', arm=args.arm,
        minimum_wall_seconds=0 if args.probe or args.learning else 3600,
        minimum_measured_steps=2 if args.probe else 16383 if args.learning else 1024))
    layer_template = declared_layer_template(args.layer_template, not (args.probe or args.learning) and hasattr(runner, 'canonical_layer_template'))
    if layer_template is not None:
        selector['hour']['layer_template'] = layer_template
    hour_wall = declared_hour_wall(args.hour_wall_seconds, not (args.probe or args.learning))
    if hour_wall is not None:
        selector['hour']['wall_seconds'] = hour_wall
    if args.continuation_hour_result is not None:
        if args.probe:
            raise ValueError('checkpoint probe cannot be a continuation source')
        selector['continuation'] = dict(source_hour_result_path=str(args.continuation_hour_result.resolve(strict=True)),
                                        source_hour_result_sha256=digest(args.continuation_hour_result))
    if args.execution_mode is not None:
        selector['execution_mode'] = args.execution_mode
    if args.training_head is not None:
        selector['training_head'] = args.training_head
        if args.training_head == 'saved-bf16-logprob-document-v1':  # the runner validates fixed 4x1024 geometry while binding sources
            _g = read_json(args.geometry)
            selector['geometry'] = dict(documents_per_step=_g['documents_per_step'], sequence_length=_g['sequence_length'])
    runner.hour_mode(selector)
    source_names = runner.required_sources(selector)
    helper = (Path.home() / '.codex/headless-python.ps1').resolve(strict=True)
    hidden = args.hidden_helper.resolve(strict=True)
    outputs = {name: custody / name for name in ('prediction.json', 'dispatch-manifest-frozen.json', 'daemon-handles-frozen.json')}
    if any(path.exists() for path in outputs.values()):
        raise FileExistsError('prepared packet already exists; custody is single use')
    if digest(args.mixture_plan) != args.mixture_sha256:
        raise ValueError('approved mixture identity differs')
    mixture = read_json(args.mixture_plan)
    data, geometry = mixture['data'], read_json(args.geometry)
    if args.resume_identity is not None:
        check_image_slot(read_json(args.resume_identity), args.image_text_manifest)
    if args.image_text_manifest is not None:
        # A1: one image-text document per update (slot 3 of 4), pair order shuffled by the run seed.
        manifest_path = args.image_text_manifest.resolve(strict=True)
        image_text = dict(manifest_path=str(manifest_path), manifest_sha256=digest(manifest_path), seed=args.seed)
        if (args.group_plan is None) != (args.group_plan_sha256 is None):
            raise ValueError('--group-plan and --group-plan-sha256 are bound together')
        if args.group_plan is not None:
            plan_path = args.group_plan.resolve(strict=True)
            if digest(plan_path) != args.group_plan_sha256:
                raise ValueError('group plan bytes differ from --group-plan-sha256')
            image_text.update(group_plan_path=str(plan_path), group_plan_sha256=args.group_plan_sha256)
        data = dict(data, image_text=image_text)
    elif args.group_plan is not None:
        raise ValueError('--group-plan needs --image-text-manifest')
    # Issue #2119 section 5 restart: see resolve_continuation_parent's and
    # resolve_continuation_parent_or_legacy's docstrings.
    chain, cursor = resolve_continuation_parent_or_legacy(
        args.parent_checkpoint, custody, selected_continuation_head, training_continuity_ledger,
        digest, read_json, args.from_genesis)
    if args.learning:
        # The section 14 learning pair is not a resume path; its parent binding stays outside the repo.
        raise ValueError('--learning is not supported by prepare_hour.py (resume path only)')
    # (H19 cursor finding): the declared cursor is never substituted (see checked_declared_cursor).
    checked_declared_cursor(data, cursor)
    if cursor is not None:
        data = dict(data, cursor=cursor)
    # A head carrying the image-order cure (cia_hour.chained_image_start) binds the image-text stream
    # to the parent's published step; the runner recomputes the binding with that start, so the
    # prediction must too or prepare_execution refuses on identity. Older heads lack the function.
    _hour = runner.load_hour_module()
    _start = {}
    if hasattr(_hour, 'chained_image_start'):
        _start = dict(image_start=_hour.chained_image_start(runner, {'parent_checkpoint': chain} if chain else {}))
    prepared = _hour.prepare_inputs(runner, data, geometry, **_start)
    # Promote the stream's resolved ledger to an explicit dispatch data binding.
    # Reopen through the same production consumer before freezing the projection.
    resolved_ledger = prepared['binding']['shard_ledger_path']
    if resolved_ledger is not None and data['shard_ledger_path'] != resolved_ledger:
        data = dict(data, shard_ledger_path=resolved_ledger,
                    shard_ledger_sha256=prepared['binding']['shard_ledger_sha256'])
        prepared = _hour.prepare_inputs(runner, data, geometry, **_start)
    rows = hidden_run(['nvidia-smi', '--query-gpu=uuid,memory.total', '--format=csv,noheader,nounits']).splitlines()
    if len(rows) != 1:
        raise ValueError('exactly one GPU identity required')
    gpu_uuid, total_mib = [part.strip() for part in rows[0].split(',')]
    if not re.fullmatch('GPU-[0-9a-fA-F-]+', gpu_uuid) or not total_mib.isdigit():
        raise ValueError('malformed GPU identity')
    total = int(total_mib) * 1024 ** 2
    limits = runner.resource_limits(selector)
    if total <= limits['total_gpu_bytes']:
        raise ValueError('selected device total must exceed the fixed device ceiling')
    reserves = [{'root': args.system_volume_root, 'minimum_free_bytes': limits['min_c_free_bytes']},
                {'root': args.data_volume_root, 'minimum_free_bytes': limits['min_b_free_bytes']}]
    vram = {'applicability': 'required', 'contract': {
        'provider': 'nvidia_smi_total_device_upper_bound', 'device_uuid': gpu_uuid,
        'maximum_process_fraction_millionths': limits['total_gpu_bytes'] * 1_000_000 // total,
        'minimum_free_bytes': 4 * GIB, 'consecutive_breach_samples': 3, 'sample_interval_ms': 2000}}
    effective_used_ceiling = min(
        total * vram['contract']['maximum_process_fraction_millionths'] // 1_000_000,
        total - vram['contract']['minimum_free_bytes'])
    if effective_used_ceiling <= 0 or limits['allocator_bytes'] >= effective_used_ceiling:
        raise ValueError('allocator ceiling must be below the effective total-device used ceiling')
    walls = [{'volume_root': args.data_volume_root, 'write_root': str(custody), 'maximum_write_bytes': int(limits['max_b_write_gib'] * GIB),
              'minimum_free_bytes': limits['min_b_free_bytes'], 'sample_interval_ms': 2000,
              'maximum_measurement_duration_ms': 250}]
    outer = dict(profile='cia_measurement', maximum_job_memory_bytes=limits['host_memory_bytes'],
        simulated_peak_commit_bytes=limits['host_memory_bytes'],
        required_available_maximum_commit_bytes=limits['host_memory_bytes'] + 10 * GIB,
        storage_reserves=reserves, vram_wall=vram, disk_write_walls=walls,
        cpu_pacing_class='governed', cpu_rate_percent=90, window_contract='headless_no_windows')
    run_id = uuid.uuid4().hex
    identity = dict(run_id=run_id, source_commit=args.expected_source_sha,
        source_sha256={name: digest(root / name) for name in source_names},
        config_sha256=digest(root / runner.CONFIG), data=data, seed=args.seed,
        support={'locus': 'core+expert-set', 'experts': args.support_experts},
        optimizer={'name': 'AdamW', 'foreach': False, 'lr': 0.001, 'betas': [0.9, 0.999],
                   'eps': 1e-8, 'weight_decay': 0.01, 'membership': 'complete_parameter_inventory'},
        geometry=geometry, batch_documents=args.batch_documents == 'true', resources=limits,
        input_binding=prepared['binding'], gpu_uuid=gpu_uuid, dispatch_resources=outer)
    if args.execution_mode is not None:
        identity['execution_mode'] = args.execution_mode
    identity['hour'] = selector['hour']
    if args.training_head is not None:
        identity['training_head'] = args.training_head
    if args.training_head is not None and args.training_head != 'native':
        if args.experiment_plan_path is None:
            raise ValueError('a streamed training head needs --experiment-plan-path')
        fused = dict(identity['optimizer'], fused=True) if args.arm == 'treatment' else identity['optimizer']
        selectors = dict(training_head=runner.training_head(identity), execution_mode=runner.execution_mode(identity),
                         local_routing_mode=runner.local_routing_mode(identity), **runner.attention_selection(identity))
        if args.training_head == 'saved-bf16-logprob-document-v1':
            selectors['answer_weight'] = runner.answer_weight()
        plan = dict(schema='ember-1945-experiment-plan-v1',
                    claim_boundary='prepare-time declaration revalidated at execute-time; not an independent pre-registration',
                    candidate_function_id=args.training_head, source_commit=identity['source_commit'],
                    source_sha256=identity['source_sha256'], optimizer=fused, support=identity['support'],
                    seed=identity['seed'], data=identity['data'],
                    geometry=dict(documents_per_step=geometry['documents_per_step'],
                                  sequence_length=geometry['sequence_length']), selectors=selectors)
        plan_bytes = canonical(plan)
        plan_path = args.experiment_plan_path
        if plan_path.exists():
            if plan_path.read_bytes() != plan_bytes:
                raise ValueError('shared experiment plan exists with different bytes')
        else:
            plan_path.write_bytes(plan_bytes)
        identity['experiment_plan'] = dict(path=str(plan_path.resolve(strict=True)),
                                           sha256=hashlib.sha256(plan_bytes).hexdigest(),
                                           candidate_function_id=args.training_head)
    if args.local_routing_mode is not None:
        identity['local_routing_mode'] = args.local_routing_mode
    if 'continuation' in selector:
        identity['continuation'] = selector['continuation']
    identity['production_mixture'] = mixture['production_mixture']
    if chain is not None:
        identity['parent_checkpoint'] = chain
    if args.checkpoint_probe is not None:
        identity['checkpoint_probe'] = read_json(args.checkpoint_probe)
    if args.arm == 'treatment':
        identity['optimizer']['fused'] = True
    purpose_binding.apply(identity, args, runner)
    count = geometry['sequence_length'] * geometry['documents_per_step']
    if args.expected_step_seconds <= 0:
        raise ValueError('expected duration must be positive')
    prediction = dict(schema='ember-cia-step-prediction-v1', identity=identity,
        expected_step_seconds=args.expected_step_seconds,
        expected_positions_per_second=count / args.expected_step_seconds, basis=args.basis)
    runner.validate_prediction(prediction, expected_identity=identity, positions_per_step=count)
    runner.prepare_execution(prediction)
    prediction_bytes = canonical(prediction)
    prediction_sha = hashlib.sha256(prediction_bytes).hexdigest()
    env = {'EMBER_GATE_AUTHORIZED': '1', 'EMBER_GPU_LOCK_PATH': str(args.gpu_lock_path),
           'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '8', 'MKL_NUM_THREADS': '8'}
    if os.environ.get('EMBER_RUN_CERTIFICATE_SHA256') is not None:
        env['EMBER_RUN_CERTIFICATE_SHA256'] = os.environ['EMBER_RUN_CERTIFICATE_SHA256']
    # Arm-selection variables are passed through ONLY when set in the dispatching shell, so an
    # unset variable leaves the manifest byte-identical to every prior run and no control arm
    # changes meaning. The worker environment is an explicit allowlist -- a variable absent from
    # here never reaches the model, which would make the arm INERT inside the very measurement
    # meant to score it while every mode string still said it was selected. That defect has a
    # receipt on this campaign and this pass-through is what prevents it here.
    if os.environ.get('EMBER_FP16_ACCUM') is not None:
        env['EMBER_FP16_ACCUM_RECEIPT'] = str(custody / 'fp16-accum-dispatch.json')
    if os.environ.get('EMBER_FP16_ACCUM_EXPERTS') is not None:
        env['EMBER_FP16_EXPERTS_RECEIPT'] = str(custody / 'fp16-experts-dispatch.json')
    if os.environ.get('EMBER_FP8_LINEAR') is not None:
        env['EMBER_FP8_RECEIPT'] = str(custody / 'fp8-linear-dispatch.json')
    if os.environ.get('EMBER_FP8_GROUPED') is not None:
        env.setdefault('EMBER_FP16_EXPERTS_RECEIPT', str(custody / 'expert-dispatch.json'))
    if os.environ.get('EMBER_FUSED_LOGIT_WIDEN') is not None:
        env['EMBER_LOSS_WIDEN_RECEIPT'] = str(custody / 'loss-widen-counts.json')
    if os.environ.get('EMBER_SKIP_KEEP') is not None:
        env['EMBER_LAYER_TEMPLATE_RECEIPT'] = str(custody / 'layer-template-counts.json')
    if os.environ.get('EMBER_MERGED_KV') is not None:
        env['EMBER_MERGED_KV_RECEIPT'] = str(custody / 'merged-kv-counts.json')
    # The MSVC toolchain, passed through when the dispatching shell has it. Triton compiles
    # a kernel on its FIRST launch, which for a new kernel happens inside the warm step or
    # inside the capture -- so a missing compiler is not a setup error, it is a governed run
    # failing partway through. CC alone is not enough on this host: triton's Windows driver
    # finds MSVC through its own hardcoded path, which resolves to a Visual Studio directory
    # carrying no toolset, so cl.exe runs with no vcruntime include or lib path and fails at
    # C1083. VCINSTALLDIR and VCToolsVersion are what make its search succeed. Found by a
    # delegated author whose kernel would not compile at all until all three were set, and
    # reported against its brief rather than patched into the launcher -- which is why this
    # is here instead of being discovered by a refused window.
    for _toolchain in ('CC', 'VCINSTALLDIR', 'VCToolsVersion'):
        if os.environ.get(_toolchain) is not None:
            env[_toolchain] = os.environ[_toolchain]
    apply_arm_env_allowlist(env)
    for name, directory in runner.CACHE_DIRS.items():
        env[name] = str(custody / 'daemon-cache' / directory)
    bindings = {}
    def bind(path, kind):
        path = Path(path).resolve(strict=True)
        bindings[str(path)] = {'kind': kind, 'path': str(path), 'sha256': digest(path)}
    for name in source_names:
        bind(root / name, 'verifier')
    bind(root / runner.CONFIG, 'config')
    for path in (hidden, helper, data['receipt_path'], data['tokenizer_path']):
        bind(path, 'verifier')
    if data['shard_ledger_path'] is not None:
        bind(data['shard_ledger_path'], 'manifest')
    bind(args.mixture_plan, 'manifest')
    if 'experiment_plan' in identity:
        bind(identity['experiment_plan']['path'], 'manifest')
    for name in ('admission_receipt_path', 'catalog_export_path', 'spans_path', 'staging_manifest_path'):
        if mixture['production_mixture'][name] is not None:
            bind(mixture['production_mixture'][name], 'manifest')
    if args.checkpoint_probe is not None:
        bind(args.checkpoint_probe, 'manifest')
        prior_root = Path(identity['checkpoint_probe']['custody_root'])
        for name in ('hour-result.json', 'prediction.json', 'owned.json', 'disk.json', 'worker-terminal.json',
                     'trained-child/checkpoint-manifest.json', 'trained-child/parameter-counter-receipt.json'):
            bind(prior_root / name, 'manifest')
    if 'continuation' in identity:
        prior_root = args.continuation_hour_result.resolve(strict=True).parent
        for name in ('hour-result.json', 'prediction.json', 'owned.json', 'disk.json', 'worker-terminal.json',
                     'rows.jsonl', 'continuation-reference.json', 'continuation-hour.json', 'continuation-next-pack.json',
                     'trained-child/checkpoint-manifest.json', 'trained-child/parameter-counter-receipt.json'):
            bind(prior_root/name, 'manifest')
        bind(prior_root.parent/'operator/operator-outcome.json', 'manifest')
    bindings[str(outputs['prediction.json'])] = {'kind': 'manifest', 'path': str(outputs['prediction.json']), 'sha256': prediction_sha}
    now = int(time.time() * 1000)
    manifest = dict(schema_version='ember-lab-dispatch-manifest-v5', job_id=run_id,
        source_commit=args.expected_source_sha, not_before_ms=now, expires_at_ms=now + 5_400_000,
        resource_lease='gpu:' + run_id,
        program={'path': str(Path(sys.executable).resolve(strict=True)), 'sha256': digest(sys.executable)},
        args=['-B', str(entry), '--daemon-run', '--live', '--custody', str(custody),
              '--hidden-helper', str(hidden), '--prediction', str(outputs['prediction.json']),
              '--prediction-sha256', prediction_sha],
        workload_profile={'profile_id': 'cia_measurement', 'pinned_host_producers': [
            {'kind': 'measurement_candidate_state', 'maximum_bytes': limits['host_memory_bytes']}],
            'requires_ui_responsiveness': False, 'cpu_rate_percent': 90},
        memory_model_authority=None, env=env, bindings=list(bindings.values()), custody_root=str(custody),
        minimum_free_vram_bytes=0, preflight_receipt=str(custody / 'daemon-preflight.json'),
        **{key: value for key, value in outer.items() if key not in ('profile', 'cpu_rate_percent')})
    manifest_bytes = canonical(manifest)
    canonical_root = canonical_directory(custody)
    canonical_sha = hashlib.sha256(canonical_root.encode()).hexdigest()
    handles = dict(status='frozen', run_id=run_id, input_root=str(custody),
        canonical_root_string=canonical_root, canonical_root_sha256=canonical_sha,
        pipe='\\\\.\\pipe\\ember-lab-certified-' + canonical_sha[:16],
        db=str(custody / 'ember-lab.sqlite3'), manifest=str(outputs['dispatch-manifest-frozen.json']),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        prediction=str(outputs['prediction.json']), prediction_sha256=prediction_sha,
        daemon=runner.daemon_identity(), preparation_helper_sha256=digest(__file__),
        measured_device_total_bytes=total,
        effective_device_used_ceiling_bytes=effective_used_ceiling,
        allocator_ceiling_bytes=limits['allocator_bytes'],
        claim='preparation only; public merge, live daemon source identity, resource ownership and cleanup remain unverified')
    payloads = {'prediction.json': prediction_bytes, 'dispatch-manifest-frozen.json': manifest_bytes,
                'daemon-handles-frozen.json': canonical(handles)}
    if any(len(raw) > MAX_METADATA for raw in payloads.values()):
        raise ValueError('output metadata exceeds bound')
    check_source()
    for name, raw in payloads.items():
        with outputs[name].open('xb') as stream:
            stream.write(raw)
    for name, directory in runner.CACHE_DIRS.items():
        (custody / 'daemon-cache' / directory).mkdir(parents=True, exist_ok=True)
    print(canonical(handles).decode())


if __name__ == '__main__':
    main()
