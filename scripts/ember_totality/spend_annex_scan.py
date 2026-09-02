#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""spend_annex_scan.py -- C(-1) spend-coverage annex scanner (gh issue #17, FROZEN SPEC v1).

C(-1) is RED: 301/319 decisive receipts (verdict-bearing, per
test_c_neg1._decisive_claim_files) never declare api_spend_usd /
paid_api_surface_used. Editing historical receipts is banned (fabrication:
you cannot retroactively add a field to a receipt without changing what
that receipt attests). This scanner builds an ANNEX instead -- a separate,
additive artifact that proves zero-spend for undeclared decisive receipts
via MACHINE evidence, never self-declaration.

CORPUS-MEMBERSHIP RULE (2026-07-03, annex-round-3 change A): this scanner's OWN output
family, receipts/spend-annex/spend-annex-*.json, is excluded from the decisive-claim
corpus before per-row classification even begins. Every spend-annex-*.json this scanner
itself writes carries a `verdict` field (PASS/FAIL/UNEVALUABLE), which makes each one a
"decisive-claim receipt" under test_c_neg1._decisive_claim_files()'s structural
definition -- but the annex's `verdict` field describes ANNEX-SCAN COVERAGE ("zero rows
show a paid-surface dependency..."), not a training/eval/experimental result. Without this
rule, every regeneration of the annex adds a brand-new undeclared decisive receipt (this
scanner's own most-recent-prior output) that CONVENTION_MAP intentionally never maps (see
the comment above CONVENTION_MAP: mapping the scanner to itself makes it re-scan its own
source text, which contains paid-client-pattern substrings as detector text) -- a
self-row treadmill where the uncovered count can never reach zero no matter how many
other rows get resolved. Matched rows are diverted into a separate `excluded_ledger` list
(counted in the run summary, full paths always listed, nothing hidden) and take no
`evidence_class` at all -- they are never "unresolvable", never any other classification,
and never contribute to the uncovered tally.

For every decisive-claim receipt this script does exactly one of:

  (c) declared      -- the receipt already carries both api_spend_usd and
                        paid_api_surface_used. Pass through unchanged
                        (verbatim values recorded, no re-derivation).

  (a) script_scanned_clean -- the receipt records its generating script
                        (searched recursively across a fixed, ordered set
                        of candidate field names -- cmd/command/script/
                        rerun_command/... including one level of nesting,
                        e.g. reproducibility.rerun_command). That script is
                        resolved IN-TREE (_lane14_common.resolve_in_tree --
                        must exist under ROOT, off-tree paths are treated
                        as missing) and its source text is scanned for
                        paid-API client imports/calls AND for paid-API-key
                        environment-variable names. Zero hits on both =
                        clean.

  script_scanned_clean_via_convention -- mapping pass (2026-07-03, gh issue
                        #17 follow-up): when NO candidate field yields a
                        script, the receipt's basename is matched against
                        CONVENTION_MAP -- a fixed table of (filename-pattern
                        -> generating-script) entries, each added only after
                        actually reading that script and confirming the
                        exact write-site line that constructs this receipt's
                        filename (see the comment above CONVENTION_MAP for
                        every quoted write-site). A distinct evidence_class
                        from field-based script_scanned_clean so the two
                        resolution paths stay separately auditable. Same
                        paid-surface scan as (a); a hit here still escalates
                        to paid_surface_violation.

  external_live_generator / external_generator_content_clean -- FOURTH disposition
                        (2026-07-03, annex-round-3 change B), distinct from
                        CONVENTION_MAP, generator_absent_historical, and plain
                        unresolvable. Covers a specific "train-daemon family" of
                        receipts (the conv_c03_* convergence-comparison segments and the
                        ceff_* gate-closure/repudiation analyses derived from them): a
                        train-daemon-dispatched, currently-LIVE sibling infra repo
                        actually assembles and writes these receipts. This tree's own
                        scripts/timeshare_pretrain.py defines no --conv / opt_variant
                        flag at all (confirmed: zero matches for either string anywhere
                        in that file), so the conv_c03_*_live.py wrappers' constructed
                        sys.argv could never even be processed by this tree's copy --
                        the receipt-assembly write-site for this family cannot resolve
                        to any script this tree ships, a stronger and independently
                        re-verified basis than the earlier CONVENTION_MAP exclusion note
                        (which only observed that the wrappers write nc2-manifest.json
                        checkpoint manifests, never this receipt). Matched rows carry a
                        structural `external_generator_evidence` field quoting the
                        receipt's own distinguishing field (ticket/opt_variant, or the
                        cross-reference field for a derivative ceff_* analysis) plus the
                        redacted external-origin note "(external live infra tree, path
                        redacted)" -- never an absolute cross-tree path. Same narrowing
                        as generator_absent_historical: every matched row is ALSO scanned
                        on its own raw text with the identical PAID_CLIENT_PATTERNS /
                        API_KEY_ENV_NAME_RE. Content-CLEAN -> evidence_class
                        `external_generator_content_clean` (same not-yet-landed
                        annex-coverage-qualification note as generator_absent_content_clean
                        carries -- a separate, not-yet-made enforcement change).
                        Content-DIRTY -> evidence_class stays `external_live_generator`
                        with a `content_scan_hits` field naming exactly what matched;
                        does not itself flip paid_surface_violation or the overall
                        verdict (same gap as generator_absent_historical, see above).

  paid_surface_violation -- the resolved generating script DOES reference a
                        paid-API client or a paid-API-key env name. This is
                        the row shape the sandbox negative control (FROZEN
                        SPEC v1, control ii) must produce.

                        GAP (documented 2026-07-03, per session review on the
                        generator-absent-historical narrowing): this class is
                        reached ONLY through _resolve_generating_script /
                        _resolve_via_convention's RESOLVED SCRIPT text (plus
                        the tree_wide_hit escalation onto that same resolved
                        script) -- it never inspects a receipt's OWN raw JSON
                        content. A content-dirty generator_absent_historical or
                        external_live_generator row (see content_scan_hits) is
                        therefore NEVER escalated to paid_surface_violation by any
                        existing code path, and this scanner does not widen that path
                        to do so (a real paid-surface dependency living only
                        in a decisive receipt's own hand-pasted content would
                        currently still classify honestly as coverage-
                        classification-only, not as a verdict-flipping
                        violation). Closing this gap is a separate, not-yet-
                        made change.

  generator_absent_historical -- second-pass bucket (2026-07-03, gh issue #17
                        follow-up): no candidate field AND no CONVENTION_MAP
                        entry resolved a script, but the ABSENCE itself is
                        evidenced rather than merely asserted -- see the
                        comment above GENERATOR_ABSENT_HISTORICAL_BASENAMES
                        for the three admissible evidence types (external-tree
                        import, git-archaeology-confirmed-gone, manually-
                        authored-by-design). Never used as an easier substitute
                        for CONVENTION_MAP or via_convention -- every entry is
                        checked against real script resolution first. Like
                        unresolvable, does not block PASS and is always listed
                        in full.

                        NARROWING (2026-07-03, session review ruling on
                        scratch/c-neg1-annex-amendment-generator-absent-
                        historical.md): evidence (a)/(b) prove the SCRIPT is
                        absent, not that SPEND is absent -- a human could have
                        hand-pasted paid-model output with no script in the
                        loop at all, and _tree_wide_scan only covers scripts/
                        + config/, never a receipt's own content. So every row
                        that would classify here is now ALSO scanned on its
                        OWN raw text with the identical PAID_CLIENT_PATTERNS +
                        API_KEY_ENV_NAME_RE used for resolved scripts. A row
                        carries a structural `evidence_subtype` field --
                        "external_tree_import" | "git_archaeology_gone" |
                        "manually_authored" -- derived from which table/branch
                        actually matched (never parsed back out of free-text
                        notes). Content-CLEAN rows get the new evidence_class
                        `generator_absent_content_clean` (see below).
                        Content-DIRTY rows KEEP the `generator_absent_historical`
                        class (the SCRIPT-absence evidence is still true and
                        still worth recording) but gain a `content_scan_hits`
                        field naming exactly what matched -- never silently
                        dropped. A content hit here does NOT itself flip the
                        row to paid_surface_violation and does NOT itself flip
                        the overall verdict (see verdict computation below) --
                        this is a coverage-classification split, not a new
                        FAIL trigger; widening paid_surface_violation to cover
                        receipt-own-content is a separate, not-yet-made change
                        (see the note above the verdict computation for the
                        gap this leaves).

  generator_absent_content_clean -- (2026-07-03 narrowing) a
                        generator_absent_historical candidate whose own raw
                        receipt text produced ZERO hits on the same paid-client
                        / paid-API-key scan used everywhere else in this file.
                        This is the only generator-absent bucket eligible to be
                        added to test_c_neg1's annex-coverage allow-list (a
                        separate, not-yet-landed enforcement change -- this
                        scanner only emits the class, per the FROZEN SPEC v1
                        point-2 boundary: enforcement-file changes are
                        session-reviewed and landed separately, never live-
                        edited by a scanner pass).

  unresolvable       -- no candidate field, no CONVENTION_MAP entry, and no
                        GENERATOR_ABSENT_HISTORICAL evidence. A genuine,
                        unexplained coverage gap. Listed HONESTLY, never
                        hidden, never silently coerced into "clean".

VOID-SUPERSESSION SEMANTICS (2026-07-07, gh issue #353): a decisive-claim receipt
named in ANY VOID receipt's `supersedes` list -- matched by (basename, sha256),
since every VOID receipt in this repo's convention records only a bare `filename`
in its supersedes entries, never a directory-qualified path, and sha256-pinning is
what actually disambiguates a basename collision -- is excluded from the
decisive-claim classification set entirely, BEFORE per-row classification begins
(same treatment as the corpus-membership rule above, structurally: a separate
`excluded_superseded` list, always listed in full, never an `evidence_class`, never
counted toward unresolvable/uncovered). The superseded receipt has been formally
disposed; continuing to demand spend-coverage on it would be litigating a claim the
repo has already voided. The VOID receipt itself is NOT excluded -- it stays IN the
decisive-claim set and is classified via a new structural rule inside
_check_generator_absent_historical (verdict=="VOID" AND a `supersedes` list is
present): evidence_subtype "manually_authored" (a VOID disposition is, by
definition, hand-authored governance text, never a script output), subject to the
identical content re-scan every generator_absent_historical row gets -- a VOID
receipt whose own reason-text happens to be content-dirty gets
`generator_absent_historical` (still-dirty), not silently waved through as clean.

ATTESTATION SIDECARS (2026-07-07, gh issue #353): a durable replacement for the
2026-07-07 incident where a throwaway build-time helper (`scratch/attest_extend.py`,
never committed) hand-stamped `evidence_class` directly onto a frozen annex JSON
snapshot for 17 receipts without ever teaching THIS generator's own classification
tables about them -- so the very next real regeneration silently lost all 17
upgrades back to `unresolvable`. Sidecar files under
`receipts/spend-annex/attestations/*.json` are the fix: each names a `target_path`,
a PINNED `target_sha256`, a proposed `evidence_class` (restricted to
ATTESTATION_ADMISSIBLE_CLASSES -- a sidecar can never invent a brand-new class that
bypasses classification review), free-text `evidence`, and `cites` (real evidence
pointers -- receipts, scripts, git commits). The generator itself loads every
sidecar on each run (_load_attestation_sidecars), and for any receipt that would
otherwise fall through every other resolution path to `unresolvable`:

  1. PIN CHECK -- the sidecar's `target_sha256` must equal the target's CURRENT
     on-disk sha256. A mismatch means the target mutated since attestation was
     written; the attestation is REJECTED (row stays `unresolvable`, notes name
     the pin failure) rather than silently trusted.
  2. CONTENT CHECK -- content-dirty ALWAYS overrides a valid attestation: the
     target's own raw text is re-scanned with the identical PAID_CLIENT_PATTERNS /
     API_KEY_ENV_NAME_RE detectors used everywhere else in this file. A dirty hit
     REJECTS the attestation (row stays `unresolvable`, content_scan_hits named)
     regardless of what the sidecar claims.
  3. Only if BOTH checks pass does the row take the sidecar's declared
     evidence_class, with evidence_subtype "attested_sidecar" and an
     `attestation_sidecar` field naming which sidecar file resolved it -- fully
     reproducible: every future regeneration re-verifies the same pin and re-runs
     the same content scan against the same sidecar, nothing is ever hand-stamped
     onto an output snapshot again.

REDACTION-CHAIN PIN (2026-07-08, gh issue #428 durability amendment): a receipt can
legitimately mutate AFTER its attestation was written -- the custody redaction pass
strips founder-scoped local paths from a receipt's own fields and writes a `redaction`
block back onto that SAME receipt recording `original_sha256` (the PRE-redaction hash),
`reason`, and `redaction_ts`. Disclosed by gh issue #428: a fresh regen of 3 already-
attested receipts (cbase-gpu-verify-20260707T064453Z, cbase-gpu-verify-
REAL-20260707T063919Z, cbase-verify-attempt3-20260707T073843) silently regressed to
`unresolvable` because each was redacted (2026-07-07T18:48:51Z) AFTER its attestation
sidecar was written (2026-07-07T11:32:00Z) -- the direct pin check correctly rejected
the now-stale hash, but had no way to recognize the mutation as an EVIDENCED,
receipt-self-disclosed one rather than an unexplained drift. The fix: if the direct pin
fails, and the receipt carries a `redaction` dict whose own `original_sha256` equals
the sidecar's `target_sha256`, the pin is ALSO considered valid -- the redaction event
is itself the evidence (self-documented on the receipt, naming its own reason and
timestamp), never a bare exemption. This does NOT weaken the content check: the
re-scan in step 2 always runs against the receipt's CURRENT (post-redaction) raw text,
never the pre-redaction content, so a redaction that happened to introduce a
paid-surface reference would still be caught. Rows resolved this way carry
`attestation_pin_match: "redaction_chain"` (a direct match carries `"direct"`) so the
distinction is always disclosed, never silently folded into one undifferentiated shape.

Malformed sidecars (missing required fields, or an evidence_class outside the
admissible set) are never silently dropped -- they are collected into
`attestation_sidecar_skipped` in the result, always disclosed.

(b) Tree-wide, independent of any single receipt: every *.py/*.ts/*.js/
    *.mjs/*.sh under scripts/ is scanned (sorted walk) for paid-API-key
    env-var names, and every file under config/ or configs/ is scanned for
    an "api_key"-shaped line naming a paid provider. This is recorded once
    in the summary as `tree_wide_scan` -- systemic evidence, not a per-row
    gate -- EXCEPT that if a tree-wide hit lands on a script this run had
    already resolved as some row's generating script, that row is escalated
    to paid_surface_violation too (a receipt cannot be "clean" while its own
    generating script independently trips the tree-wide sweep).

verdict = PASS iff zero rows are paid_surface_violation. unresolvable rows
do not block PASS (they are coverage gaps, not spend evidence) but are
always listed in full, never summarized away.

Deterministic: sorted globs/walks throughout, fixed candidate-field
iteration order, no wall-clock value read anywhere in the classification
logic (the only timestamp used anywhere is generated_at_utc, pure output
metadata, and the caller-supplied output filename).

Root resolution is delegated entirely to test_c_neg1 (same EMBER_TOTALITY_ROOT
env var, same CANDIDATE_ROOTS fallback) so a sandbox run
(EMBER_TOTALITY_ROOT=<scratch dir> python spend_annex_scan.py) scans the
sandbox tree exactly the way test_c_neg1.py would, with no separate root
logic to drift out of sync.

This script does NOT touch probes/ or the conditions registry -- that
amendment is a separate DRAFT at scratch/c-neg1-annex-amendment.md, landed
only via session review (FROZEN SPEC v1, point 2). This script also never
edits an existing receipt file; every receipt under receipts/ is opened
read-only.
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import test_c_neg1 as c_neg1  # noqa: E402  (reuse root resolution + _decisive_claim_files)
from _lane14_common import resolve_in_tree, sha256_file  # noqa: E402
import void_supersession  # noqa: E402  (shared VOID-supersession partition, gh issue #358)

ROOT = c_neg1.ROOT
SPEND_KEY = c_neg1.SPEND_KEY
PAID_FLAG_KEY = c_neg1.PAID_FLAG_KEY
GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
TICKET = "ISSUE-586-SPEND-ANNEX-ROUND4"
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

# --- Corpus-membership rule (2026-07-03, annex-round-3 change A) -- see the
# CORPUS-MEMBERSHIP RULE paragraph in the module docstring. Matches this scanner's
# own output family by path, scoped to the spend-annex/ directory so it can never
# over-match anything else named similarly elsewhere in the tree.
SPEND_ANNEX_SELF_ROW_RE = re.compile(r"^receipts/spend-annex/spend-annex-.*\.json$")

# --- Candidate field names that may record a receipt's generating script/command,
# in fixed priority order. Searched recursively (one level of nesting, e.g.
# reproducibility.rerun_command) so both flat and nested receipt shapes are covered.
CMD_FIELD_CANDIDATES = [
    "script",
    "script_path",
    "candidate_script_path",
    "harness_interface_path",
    "source_file",
    "cmd",
    "command",
    "commands",
    "rerun_command",
    "next_executable_command",
    "dryrun_command",
    "build_cmd",
    "ac_command",
    "producer",
    "generator",
    "generated_by",
    "runner",
    "harness",
]

_SCRIPT_TOKEN_RE = re.compile(r"[^\s'\"()]+\.(?:py|ts|js|mjs|cjs|sh|ps1)\b")

# --- Paid-API-client import/instantiation markers. Precise (import/require/domain
# patterns), never a bare provider-name substring -- this repo's own docs/scripts
# mention "claude"/"anthropic" constantly in non-paid-API contexts (this IS a
# Claude-authored codebase), so a loose substring match would false-positive on
# nearly every file.
PAID_CLIENT_PATTERNS = {
    "openai_import": re.compile(r"^\s*(?:import\s+openai\b|from\s+openai\b)", re.M),
    "openai_client_call": re.compile(r"\bopenai\.(OpenAI|ChatCompletion|Completion)\s*\(", re.I),
    "openai_js": re.compile(r"""(?:require\(\s*['"]openai['"]\s*\)|from\s+['"]openai['"])"""),
    "anthropic_import": re.compile(r"^\s*(?:import\s+anthropic\b|from\s+anthropic\b)", re.M),
    "anthropic_client_call": re.compile(r"\banthropic\.(Anthropic|Client)\s*\(", re.I),
    "anthropic_js": re.compile(r"""(?:require\(\s*['"]@anthropic-ai/sdk['"]\s*\)|from\s+['"]@anthropic-ai/sdk['"])"""),
    "googleapis_client": re.compile(r"\b(?:google\.generativeai|googleapiclient|genai\.configure)\s*\(?", re.I),
    "replicate_import": re.compile(r"^\s*import\s+replicate\b", re.M),
    "replicate_client_call": re.compile(r"\breplicate\.(Client|run)\s*\(", re.I),
    "together_import": re.compile(r"^\s*import\s+together\b", re.M),
    "together_client_call": re.compile(r"\btogether\.(Client|Complete)\s*\(", re.I),
    "cohere_import": re.compile(r"^\s*import\s+cohere\b", re.M),
    "cohere_client_call": re.compile(r"\bcohere\.Client\s*\(", re.I),
    "mistralai_import": re.compile(r"^\s*import\s+mistralai\b", re.M),
    "mistralai_client_call": re.compile(r"\bmistralai\.", re.I),
    "paid_endpoint_url": re.compile(
        r"(?:api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|"
        r"api\.replicate\.com|api\.together\.(?:xyz|ai)|api\.cohere\.ai|api\.mistral\.ai)",
        re.I,
    ),
}

# Deliberately requires an actual CONSUMPTION context (os.environ / os.getenv /
# process.env immediately before the key name) -- not a bare substring match.
# A script that merely *mentions* "OPENAI_API_KEY" (e.g. to check whether some
# OTHER document/README references it, as an admissibility gate would) is not
# consuming a paid credential; matching on the bare token name over-triggers on
# exactly that shape (confirmed false positive: scripts/ember_paperbench_admission.py
# checks `"OPENAI_API_KEY" in readme` to detect a benchmark's OWN paid-key
# requirement, never reads the env var itself).
API_KEY_ENV_NAME_RE = re.compile(
    r"(?:os\.environ(?:\.get)?\s*\(?\s*[\"']|os\.getenv\s*\(\s*[\"']|process\.env\.)"
    r"(OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY|"
    r"GOOGLE_GENERATIVE_AI_API_KEY|REPLICATE_API_TOKEN|REPLICATE_API_KEY|"
    r"TOGETHER_API_KEY|COHERE_API_KEY|MISTRAL_API_KEY)\b"
)

PAID_PROVIDER_NAME_RE = re.compile(
    r"\b(openai|anthropic|google|replicate|together|cohere|mistral)\b", re.I
)

SCANNED_SURFACES = sorted(PAID_CLIENT_PATTERNS.keys()) + ["paid_api_key_env_name"]

SCRIPT_SCAN_EXTS = (".py", ".ts", ".js", ".mjs", ".cjs", ".sh")

# --- Filename-convention mapping table (gh issue #17 mapping pass, 2026-07-03).
# Each entry maps a receipt BASENAME regex to its generating script. Every entry
# here was added only after READING that script and finding the exact write-site
# line that constructs this receipt's filename -- confirmed, quoted line numbers
# below; a mapping without a confirmed write-site is NEVER added. This is a
# fallback, tried only when field-based resolution (_resolve_generating_script)
# found nothing -- a receipt that declares a real cmd/script field is still
# resolved via that field first.
#
#   c7-selftest-*.json                       scripts/ember_phase5_c7/c7_selftest.py:65
#     SELFTEST_RECEIPT_PATH: pathlib.Path = RECEIPTS_DIR / f"c7-selftest-{_TS}.json"
#   citation-check-*.json                    src/ember/governance/scripts/check_goal_citations.py:804
#     receipt_path = RECEIPTS_DIR / f"citation-check-{receipt['timestamp']}.json"
#   publication-gate-*.json                  src/ember/governance/scripts/check_publication_gate.py:963
#     receipt_path = RECEIPTS_DIR / f"publication-gate-{receipt['ts']}.json"
#   proof-judge-admission-*.json             scripts/proofs/judge_admission_sweep.py:686
#     out_path = out_dir / f"proof-judge-admission-{stamp}.json"
#   p-gate-*.json                            scripts/p_gate.py:299,430
#     receipt_path = _RECEIPTS / f"p-gate-{ts}.json"
#   training-throughput-anchor-check-all-*.json  scripts/proofs/training_throughput_anchor_check.py:223
#     out_path = RECEIPTS_DIR / f"training-throughput-anchor-check-all-{ts}.json"
#   official-abc-wheel-runner-*.json         scripts/ember_mvp_wheel_runner.py:99
#     out = root / "receipts" / "wheel-runner" / f"official-abc-wheel-runner-{ts}.json"
#   proof-replay-consistency-*.json          scripts/proofs/replay_consistency_check.py:792
#     out_path = receipts_out_dir / f"proof-replay-consistency-{stamp}.json"
#   scienceagentbench-first-loop-*.json      scripts/ember_scienceagentbench_first_loop.py:260
#     out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"scienceagentbench-first-loop-{ts}.json"
#   eng123-timeshare-dryrun-*.json           scripts/timeshare_dryrun.py:275
#     out_path = os.path.join(receipts_dir, f"eng123-timeshare-dryrun-{ts}.json")
#   proof-frontier-protocol-*.json           scripts/proofs/frontier_projection.py:467
#     out_path = out_dir / f"proof-frontier-protocol-{receipt['ts']}.json"
#   proof-ocal-sweep-*.json                  scripts/proofs/ocal_calibration_sweep.py:617
#     out_path = out_dir / f"proof-ocal-sweep-{receipt['ts']}.json"
#   wheel-real-*.json                        scripts/ember_wheel_harness.py:241
#     out = root / "receipts" / "wheel" / f"wheel-real-{ts}.json"
#   wheel-heldout-*.json                     scripts/ember_wheel_harness.py:452
#     out = root / "receipts" / "wheel" / f"wheel-heldout-{ts}.json"
#   contamination-verbatim-*.json            scripts/proofs/contamination_verbatim_check.py:319,326
#     out_path = RECEIPTS_DIR / f"contamination-verbatim-{receipt['ts']}.json"
#   fp35c-weight-cache-ab-*.json             scripts/fp35c_weight_cache_ab.py:389
#     out_path = os.path.join(RECEIPTS, f"fp35c-weight-cache-ab-{ts}.json")
#   placement-9p-bleed-*.json                scripts/proofs/placement_9p_bleed_probe.py:667
#     out_path = RECEIPTS_DIR_WIN / f"placement-9p-bleed-{stamp}.json"
#   proof-verifier-surface-coverage-*.json   scripts/proofs/verifier_surface_coverage.py:689
#     out_path = receipts_out_dir / f"proof-verifier-surface-coverage-{stamp}.json"
#
# --- Second pass (gh issue #17 follow-up, 2026-07-03) -- 22 more write-site-confirmed
# entries, found by tracing every remaining unresolvable receipt's basename against
# scripts/ (rg fixed-string, source files only) then reading the hit to confirm it is
# an actual write call (out_path = ... / f"<pattern>-{ts}.json"), never a comment,
# docstring, or PRIOR_RECEIPT-style consumer reference (several near-misses were
# rejected for exactly that reason, e.g. cbase_v0_segment_bf16ns5_live.py:7 only
# *mentions* ceff-closure-gate9-shatter-bf16ns5 in a docstring; it writes
# nc2-manifest.json, not that receipt -- stays unresolvable, see exclusion note below):
#   c12-cognitive-mode-ablation-*.json       src/ember/governance/scripts/ember_cognitive_mode_ablation.py:275
#     out_path = out_dir / f"c12-cognitive-mode-ablation-{receipt['ts']}.json"
#   cuda-graph-ab-*.json                     src/ember/governance/scripts/cuda_graph_ab.py:495
#     out = os.path.join(RECEIPTS, f"cuda-graph-ab-{ts}.json")
#   d-gate-*.json                            src/ember/governance/scripts/d_gate.py:405
#     receipt_path = _RECEIPTS / f"d-gate-{artifact_stem}-{ts}.json"
#   density-ab-verdict-*.json                src/ember/governance/scripts/density_ab_verdict.py:113,185,244
#     out = f"{RECEIPTS}/density-ab-verdict-{ts_now}.json"
#   econ-pass-loopecon-adapter-*.json        scripts/econ_pass.py:242
#     adapter_path = receipts_dir / f"econ-pass-loopecon-adapter-{ts}.json"
#   fp10-idiom-*.json                        src/ember/governance/scripts/fp10_idiom.py:324
#   fp11-denominator-*.json                  scripts/fp11_denominator.py:265
#   fp12-band-*.json                         scripts/fp12_band.py:233
#   fp13-concentration-*.json                src/ember/governance/scripts/fp13_concentration.py:270
#   fp30d-shard-gate-*.json                  scripts/fp30d_shard_gate.py:189
#   fp33-e2-full-tune-ceiling-*.json         scripts/fp33_e2_full_tune_ceiling.py:234
#   fp33-e5-fp8-bench-*.json                 scripts/fp33_e5_fp8_bench.py:255
#   fp33-fp8-linear-ab-*.json                scripts/fp33_fp8_linear_ab.py:380
#   fp33-p1-native-fp8-probe-*.json          scripts/fp33_p1_native_fp8_probe.py:164
#   fp35-fused-muon-kernel-ab-*.json         src/ember/governance/scripts/fp35_fused_muon_kernel_ab.py:545 (distinct from
#     fp35-fused-muon-ab-*.json, no "kernel" -- that one has NO confirmed writer, excluded below)
#   fp35d-k4096-steady-state-*.json          scripts/fp35d_k4096_steady_state.py:216
#   fp35g-width-cond-fp8-ab-*.json           scripts/fp35g_width_cond_fp8_ab.py:484
#   fp38-l9-flash-ab-*.json                  scripts/fp38_l9_flash_ab.py:239
#   fp38b-l9-completion-*.json               scripts/fp38b_l9_completion.py:232
#   fp38c-l9-eager-*.json                    scripts/fp38c_l9_eager.py:213
#   fp38d-l9-prod-flash-*.json               scripts/fp38d_l9_prod_flash.py:274
#   fp39-density-power-audit-*.json          scripts/fp39_density_power_audit.py:190
#   fp40-l10-optimizer-ab-*.json             scripts/fp40_l10_optimizer_ab.py:596
#   native-smoke-*.json                      scripts/t_native_smoke.py:99
#     return receipts_dir / f"native-smoke-{ts}.json"
#   probe-meminfo-*.json                     scripts/probe_meminfo.py:37
#     path = f"{NC}/receipts/probe-meminfo-{ts}.json"
#   resident-training-gate-*.json            scripts/ember_resident_training_gate.py:945,1165,1172
#     checked_write(str(out_path), receipt) where out_path comes from the REQUIRED
#     --out CLI arg (ap.error(...) if missing) -- the script itself names no fixed
#     timestamp convention (caller supplies the full filename), but the naming
#     convention it documents for itself (line 925, its own next-command generator)
#     is exactly "resident-training-gate-<timestamp>.json", matching this receipt.
#   resume-drill-*.json                      scripts/train_multimodal_v0.py:3189
#     receipt_path = receipts_dir / f"resume-drill-{ts}.json"
#   selective-recompute-ab-*.json            scripts/selective_recompute_ab.py:444
#   v0-live-<digits>.json (excludes -import-edition, see below)  scripts/timeshare_pretrain.py:2092
#     out = os.path.join(repo, "receipts", f"v0-live-{receipt['ts']}.json")
#   v0ext-dryrun-*.json                      scripts/timeshare_pretrain.py:2049
#   wsl9p-probe-*.json                       scripts/wsl9p_probe.py:353
#     default_output = f".../receipts/wsl9p-probe-{ts...}.json" (default path is an
#     absolute WSL nc-ladder path; this repo's copy required an explicit --out
#     override, confirmed by the file existing at a non-default receipts/ location)
#   neural_policy_update_trace.json          scripts/ember_train_multimodal_resident_adapter.py:313
#   train_multimodal_resident_adapter_receipt.json  scripts/ember_train_multimodal_resident_adapter.py:317
#   policy_update_trace.json (exact basename, distinct from neural_policy_update_trace.json)
#                                             scripts/ember_resident_training_candidate.py:217
#   resident_training_candidate_receipt.json scripts/ember_resident_training_candidate.py:222
#
# Deliberately EXCLUDED after a real search turned up no confirmed writer (these
# stay unresolvable, honestly, rather than guessed): cbase-grow-dryrun-*.json
# (its own receipt's "script" field claims src/ember/governance/scripts/cbase_grow_dryrun.py, which
# does not exist on disk -- a stale pointer, not a convention); wheel-bound-*.json (no
# writer found anywhere in scripts/); arm-a-benchmark-*/arm-b-benchmark-*/
# benchmark-c-arm-*.json (no writer found); ember-totality-*.json (the spec
# runner writes these under scripts/ember_totality/receipts-totality/, which is
# OUTSIDE receipts/ entirely -- _decisive_claim_files() never sees them, so no
# row exists to map in the first place); conv-full_fused_adamw-*.json,
# conv-muon_ns3-*.json, conv-muon_split-*.json, conv-muon_split_bf16ns5-*.json,
# conv-muon_split_fast-*.json, ceff-closure-gate9-shatter-bf16ns5-*.json,
# ceff-shatter-REPUDIATED-*.json, fp35-fused-muon-ab-*.json (the in-tree
# conv_c03_*.py / conv_c03_*_live.py / cbase_v0_segment_bf16ns5_live.py scripts
# only write nc2-manifest.json checkpoint manifests and are documented as
# "exec'd by the train-daemon (an external live infra tree's train-daemon server (path redacted)) with NO
# CLI args" -- the receipt-assembly step for these lives in that EXTERNAL,
# currently-live infra repo, never in this tree; NOT the same evidentiary
# situation as generator_absent_historical below, so left unresolvable rather
# than misclassified -- flagged for a policy decision, see issue #17 second-pass
# report). v0-live-import-edition-*.json is EXCLUDED from the v0-live-* mapping
# above on purpose (see GENERATOR_ABSENT_HISTORICAL_BASENAMES: same ticket shape
# as v0-live but the exact literal "-import-edition-" suffix is never constructed
# by scripts/timeshare_pretrain.py or anywhere else in tree -- a likely post-hoc
# rename, not a script-confirmed convention).
# spend-annex-*.json (this scanner's own output, confirmed generator:
# scripts/ember_totality/spend_annex_scan.py:557-563,567) is DELIBERATELY left out of
# CONVENTION_MAP: mapping the scanner to itself makes it re-scan its own source text,
# where PAID_CLIENT_PATTERNS itself literally contains the substring "googleapiclient"
# as detector-pattern text -- a confirmed false paid_surface_violation on pure
# self-reference, not real usage (verified: adding the mapping flips verdict to FAIL
# with paid-client pattern googleapis_client on both spend-annex rows). Stays
# unresolvable, honestly, rather than risk a self-referential carve-out.
CONVENTION_MAP = [
    (re.compile(r"^c7-selftest-.*\.json$"), "scripts/ember_phase5_c7/c7_selftest.py"),
    (re.compile(r"^citation-check-.*\.json$"), "src/ember/governance/scripts/check_goal_citations.py"),
    (re.compile(r"^publication-gate-.*\.json$"), "src/ember/governance/scripts/check_publication_gate.py"),
    (re.compile(r"^proof-judge-admission-.*\.json$"), "scripts/proofs/judge_admission_sweep.py"),
    (re.compile(r"^p-gate-.*\.json$"), "scripts/p_gate.py"),
    (re.compile(r"^training-throughput-anchor-check-all-.*\.json$"),
     "scripts/proofs/training_throughput_anchor_check.py"),
    (re.compile(r"^official-abc-wheel-runner-.*\.json$"), "scripts/ember_mvp_wheel_runner.py"),
    (re.compile(r"^proof-replay-consistency-.*\.json$"), "scripts/proofs/replay_consistency_check.py"),
    (re.compile(r"^scienceagentbench-first-loop-.*\.json$"), "scripts/ember_scienceagentbench_first_loop.py"),
    (re.compile(r"^eng123-timeshare-dryrun-.*\.json$"), "scripts/timeshare_dryrun.py"),
    (re.compile(r"^proof-frontier-protocol-.*\.json$"), "scripts/proofs/frontier_projection.py"),
    (re.compile(r"^proof-ocal-sweep-.*\.json$"), "scripts/proofs/ocal_calibration_sweep.py"),
    (re.compile(r"^wheel-real-.*\.json$"), "scripts/ember_wheel_harness.py"),
    (re.compile(r"^wheel-heldout-.*\.json$"), "scripts/ember_wheel_harness.py"),
    (re.compile(r"^contamination-verbatim-.*\.json$"), "scripts/proofs/contamination_verbatim_check.py"),
    (re.compile(r"^fp35c-weight-cache-ab-.*\.json$"), "scripts/fp35c_weight_cache_ab.py"),
    (re.compile(r"^placement-9p-bleed-.*\.json$"), "scripts/proofs/placement_9p_bleed_probe.py"),
    (re.compile(r"^proof-verifier-surface-coverage-.*\.json$"), "scripts/proofs/verifier_surface_coverage.py"),
    # --- second pass (gh issue #17 follow-up, 2026-07-03) ---
    # spend-annex-*.json deliberately NOT mapped here -- see comment above CONVENTION_MAP.
    (re.compile(r"^c12-cognitive-mode-ablation-.*\.json$"), "src/ember/governance/scripts/ember_cognitive_mode_ablation.py"),
    (re.compile(r"^cuda-graph-ab-.*\.json$"), "src/ember/governance/scripts/cuda_graph_ab.py"),
    (re.compile(r"^d-gate-.*\.json$"), "src/ember/governance/scripts/d_gate.py"),
    (re.compile(r"^density-ab-verdict-.*\.json$"), "src/ember/governance/scripts/density_ab_verdict.py"),
    (re.compile(r"^econ-pass-loopecon-adapter-.*\.json$"), "scripts/econ_pass.py"),
    (re.compile(r"^fp10-idiom-.*\.json$"), "src/ember/governance/scripts/fp10_idiom.py"),
    (re.compile(r"^fp11-denominator-.*\.json$"), "scripts/fp11_denominator.py"),
    (re.compile(r"^fp12-band-.*\.json$"), "scripts/fp12_band.py"),
    (re.compile(r"^fp13-concentration-.*\.json$"), "src/ember/governance/scripts/fp13_concentration.py"),
    (re.compile(r"^fp30d-shard-gate-.*\.json$"), "scripts/fp30d_shard_gate.py"),
    (re.compile(r"^fp33-e2-full-tune-ceiling-.*\.json$"), "scripts/fp33_e2_full_tune_ceiling.py"),
    (re.compile(r"^fp33-e5-fp8-bench-.*\.json$"), "scripts/fp33_e5_fp8_bench.py"),
    (re.compile(r"^fp33-fp8-linear-ab-.*\.json$"), "scripts/fp33_fp8_linear_ab.py"),
    (re.compile(r"^fp33-p1-native-fp8-probe-.*\.json$"), "scripts/fp33_p1_native_fp8_probe.py"),
    (re.compile(r"^fp35-fused-muon-kernel-ab-.*\.json$"), "src/ember/governance/scripts/fp35_fused_muon_kernel_ab.py"),
    (re.compile(r"^fp35d-k4096-steady-state-.*\.json$"), "scripts/fp35d_k4096_steady_state.py"),
    (re.compile(r"^fp35g-width-cond-fp8-ab-.*\.json$"), "scripts/fp35g_width_cond_fp8_ab.py"),
    (re.compile(r"^fp38-l9-flash-ab-.*\.json$"), "scripts/fp38_l9_flash_ab.py"),
    (re.compile(r"^fp38b-l9-completion-.*\.json$"), "scripts/fp38b_l9_completion.py"),
    (re.compile(r"^fp38c-l9-eager-.*\.json$"), "scripts/fp38c_l9_eager.py"),
    (re.compile(r"^fp38d-l9-prod-flash-.*\.json$"), "scripts/fp38d_l9_prod_flash.py"),
    (re.compile(r"^fp39-density-power-audit-.*\.json$"), "scripts/fp39_density_power_audit.py"),
    (re.compile(r"^fp40-l10-optimizer-ab-.*\.json$"), "scripts/fp40_l10_optimizer_ab.py"),
    (re.compile(r"^native-smoke-.*\.json$"), "scripts/t_native_smoke.py"),
    (re.compile(r"^probe-meminfo-.*\.json$"), "scripts/probe_meminfo.py"),
    (re.compile(r"^resident-training-gate-.*\.json$"), "scripts/ember_resident_training_gate.py"),
    (re.compile(r"^resume-drill-.*\.json$"), "scripts/train_multimodal_v0.py"),
    (re.compile(r"^selective-recompute-ab-.*\.json$"), "scripts/selective_recompute_ab.py"),
    # anchored to digits-only so it never swallows v0-live-import-edition-*.json
    (re.compile(r"^v0-live-\d{8}T\d{6}Z\.json$"), "scripts/timeshare_pretrain.py"),
    (re.compile(r"^v0ext-dryrun-.*\.json$"), "scripts/timeshare_pretrain.py"),
    (re.compile(r"^wsl9p-probe-.*\.json$"), "scripts/wsl9p_probe.py"),
    (re.compile(r"^neural_policy_update_trace\.json$"), "scripts/ember_train_multimodal_resident_adapter.py"),
    (re.compile(r"^train_multimodal_resident_adapter_receipt\.json$"),
     "scripts/ember_train_multimodal_resident_adapter.py"),
    (re.compile(r"^policy_update_trace\.json$"), "scripts/ember_resident_training_candidate.py"),
    (re.compile(r"^resident_training_candidate_receipt\.json$"), "scripts/ember_resident_training_candidate.py"),
]

# Exact-path writer bindings for receipt names that are not globally unique.
# These are deliberately path-scoped: for example, capture-receipt.json is a
# generic basename and must never cause an unrelated receipt to inherit the
# Ember CLI capture writer.  Each writer below constructs the named output in
# the same commit that introduced the receipt (issue #586 round-4 refresh).
CONVENTION_PATH_MAP = {
    "receipts/ember-c-scale/land210j-public-revalidation-20260729T135005Z.json":
        "scripts/land210j_public_revalidation.py",
    "receipts/ember-cli/issue-1043-text-wrap/capture-receipt.json":
        "tools/ember-cli/src/build-tools/capture-text-wrap-1043.ts",
    "receipts/issue-457-current-acceptance-20260730.json":
        "scripts/issue457_acceptance.py",
}

# --- Generator-absent-historical table (gh issue #17 second pass, 2026-07-03).
# A THIRD disposition, distinct from both CONVENTION_MAP (a confirmed live in-tree
# writer) and plain "unresolvable" (an honest coverage gap that might just need more
# searching). This bucket is for receipts where the search was exhaustive and the
# generating script is genuinely not findable in this tree, for one of three
# evidenced reasons -- never used as an easier substitute for CONVENTION_MAP; every
# entry below was checked against CONVENTION_MAP resolution first.
#
# Evidence (a) EXTERNAL-TREE IMPORT: the receipt's own JSON content names an
#   absolute path under an external founder-state working tree (path redacted) or a disposable
#   clean-room checkout (C:/tmp/ember-clean-post-*, a disposable staging checkout (path redacted)/...)
#   as its true origin. These were generated in a DIFFERENT founder's external
#   working tree (or a throwaway checkout) and later copied wholesale into
#   receipts/ember-mvp/ (or the surface-adjacent dirs below) as a historical
#   snapshot; no script under THIS repo's scripts/ or tools/ ever produced them.
#   Applies to every receipts/ember-mvp/* file except c12-cognitive-mode-ablation-*
#   (that one is a fresh, in-tree-generated exception -- see CONVENTION_MAP above)
#   plus the specific basenames listed below that carry the same external-path
#   signature despite living outside the ember-mvp/ directory.
#
# Evidence (b) GIT-ARCHAEOLOGY CONFIRMED GONE: `git log --follow` on the receipt
#   shows the commit that added it contains ONLY the receipt JSON (+ docs/docs/domains/governance/authority/STATE.md
#   at most), never an accompanying script; `git log HEAD -S "<literal-filename-prefix>"`
#   and `--diff-filter=D` both return no in-tree script for this name anywhere in
#   this repo's HEAD-reachable history. The generating code was run ambient/ad-hoc
#   and never committed to this tree (confirmed for fp32-l6-compile-ab and
#   fp35-fused-muon-ab: both receipts landed in commits a63974a/9236963 that add
#   ONLY receipts + docs/domains/governance/archive/pre-restart/compute-ceiling-program-v1.md, no .py file).
#
# Evidence (c) MANUALLY-AUTHORED, NO GENERATOR BY DESIGN: the receipt's own
#   schema/content proves it is a hand-typed review, audit, or adjudication
#   document -- schema=="adjudication/v1"; an explicit "method" field describing a
#   manual consolidation pass (e.g. "<reviewer> gate consolidation -- pointers grepped
#   live + receipt contents read (not asserted)"); or prose "claim"/"verdict"
#   fields with no measured-data shape. Several are cross-confirmed via
#   git-archaeology too (receipt-only commits, e.g. pr1-review-verdict,
#   raw-corpus-materiality, cloud-reference-leg-disposition, heartbeat-runner-selftest).
#
# Evidence (d) CROSS-BRANCH UNMERGED (2026-07-08, gh issue #431): distinct from (b)
#   git-archaeology-gone -- the generating script is NOT vacant; it is confirmed to
#   exist, with a confirmed write-site constructing this exact receipt filename, via
#   `git show <commit>:<path>`. But that commit is reachable ONLY from a sibling branch
#   of this same repository (confirmed via `git merge-base --is-ancestor <commit> HEAD`
#   returning false, and `git branch --all --contains <commit>` naming the branches it
#   DOES live on) -- never merged into, or reachable from, master's own HEAD history.
#   These three receipts were generated on the `goalforge/definitive-goal-20260701` /
#   `lane/ceff-ab-run` branch family and later imported into master's receipts/ via the
#   #415/#432 custody restoration; their generating scripts were never part of that
#   restoration and remain off-branch. Stronger evidence than (b): the real generating
#   script's actual source text (not just the receipt's own content) was read directly
#   off that branch and re-scanned with the identical PAID_CLIENT_PATTERNS /
#   API_KEY_ENV_NAME_RE detectors used everywhere else in this file -- confirmed clean,
#   quoted per-entry below. The receipt's own content still gets the same content-dirty
#   re-scan every generator_absent_historical row gets (see _check_generator_absent_historical
#   callers) -- this evidence proves the SCRIPT is clean, not that the RECEIPT's own text is.
GENERATOR_ABSENT_HISTORICAL_PATH_PREFIXES = [
    ("receipts/ember-mvp/", "external_tree_import",
     "evidence (a) external-tree import: this receipt lives under receipts/ember-mvp/, "
     "the historical import directory for the June 2026 ember-mvp consolidation; sibling "
     "receipts in this directory carry source_root/data_root/freeze_manifest_path/"
     "cycle_receipt_path fields pointing at an external founder-state working tree (path redacted) (a different "
     "founder's external working tree) or C:/tmp/ember-clean-post-473-lf-20260618/... (a "
     "disposable clean-room checkout); no script under this repo's scripts/ or tools/ "
     "constructs this filename (confirmed by exhaustive fixed-string search)."),
    # --- gh issue #586 (annex round-4, 2026-07-09) ---
    ("receipts/ember-cockpit-live-surface1/", "external_tree_import",
     "evidence (a) external-tree import: each receipt's own `exact_rerun_command` field "
     "(a field name distinct from every entry in CMD_FIELD_CANDIDATES, so the field-based "
     "resolver never sees it) names a local one-off capture helper "
     "(scripts/ember_cockpit_live_capture.cjs) that was never committed to this tree -- "
     "confirmed absent (no such file on disk anywhere under this repo, zero grep hits for "
     "its name in scripts/, tools/, or docs/). This whole directory was restored wholesale "
     "via the C-CUSTODY-23 import (receipts/custody-curation-20260708T235000Z.json, "
     "source_commit fa49af4, 'public: receipt hygiene banking (26 files)', landed at "
     "commit d3dff30): a live local UI-capture session against a local qwen model server, "
     "never a paid-API call -- same historical-import shape as receipts/ember-mvp/ above."),
]

# Exact-path evidence for current receipts that were intentionally assembled as
# review/landing records, not emitted by a production script.  The introducing
# commits pair each JSON record with the files it reviews/lands, and exhaustive
# fixed-string searches find no writer constructing the receipt filename.  An
# exact-path table avoids broad basename families that could classify future
# generated receipts by accident.
GENERATOR_ABSENT_HISTORICAL_PATHS = {
    "receipts/ember-c-scale/land210g-experiment-runners-receipt.json":
        ("manually_authored", "receipts/ember-c-scale/land210g-experiment-runners-receipt.json: "
         "manually-authored landing inventory introduced by commit 617f071e with the reviewed family; "
         "no committed writer constructs this filename"),
    "receipts/ember-c-scale/land210h-ops-tools-receipt.json":
        ("manually_authored", "receipts/ember-c-scale/land210h-ops-tools-receipt.json: "
         "manually-authored landing inventory introduced by commit ea39d694 with the reviewed family; "
         "no committed writer constructs this filename"),
    "receipts/ember-c-scale/land210i-harness-entry-receipt.json":
        ("manually_authored", "receipts/ember-c-scale/land210i-harness-entry-receipt.json: "
         "manually-authored landing inventory introduced by commit 93b5b726 with the reviewed family; "
         "no committed writer constructs this filename"),
    "receipts/ember-c-scale/land210j-family3-stragglers-receipt.json":
        ("manually_authored", "receipts/ember-c-scale/land210j-family3-stragglers-receipt.json: "
         "manually-authored landing inventory introduced by commit 70aefaa0 with the reviewed family; "
         "no committed writer constructs this filename"),
    "receipts/ember-c-scale/land210k-e2b-pair-receipt.json":
        ("manually_authored", "receipts/ember-c-scale/land210k-e2b-pair-receipt.json: "
         "manually-authored landing inventory introduced by commit 560f93c3 with the reviewed family; "
         "no committed writer constructs this filename"),
    "receipts/issue-580-pr-b-retro-audit-20260730.json":
        ("manually_authored", "receipts/issue-580-pr-b-retro-audit-20260730.json: "
         "manually-authored retrospective audit introduced by commit 7b75f758 alongside the corrected "
         "sources and tests; no committed writer constructs this filename"),
}

GENERATOR_ABSENT_HISTORICAL_BASENAMES = [
    (re.compile(r"^connected-cycle-field-level-audit-.*\.json$"), "external_tree_import",
     "evidence (a) external-tree import: 'commands' field points at "
     "an external founder-state tree observation driver (path redacted) run with "
     "cwd a disposable staging checkout (path redacted) -- generated in an external tree, copied in."),
    (re.compile(r"^deleted-method-connected-audit\.json$"), "external_tree_import",
     "evidence (a) external-tree import: identical next_executable_command text to "
     "connected-cycle-field-level-audit-*.json, same external-tree origin."),
    (re.compile(r"^scienceagentbench-admission-.*\.json$"), "external_tree_import",
     "evidence (a) external-tree import: next_executable_command references "
     "C:\\tmp\\ember-<other-founder>-stage1-clean\\receipts\\ember-post-resident-discovery\\... as the "
     "frozen-rows source -- generated in that external clean-room checkout."),
    (re.compile(r"^scienceagentbench-paid-eval-authorization-.*\.json$"), "external_tree_import",
     "evidence (a) external-tree import: same ember-post-resident-discovery/ batch as "
     "scienceagentbench-admission-*.json, same external clean-room origin."),
    (re.compile(r"^real-avir-uiux-ax-observation-.*\.json$"), "external_tree_import",
     "evidence (a) external-tree import: 'commands.actual_driver_used' runs "
     "an external founder-state tree observation driver (path redacted) with cwd "
     "a disposable staging checkout (path redacted) -- generated entirely outside this repo."),
    (re.compile(r"^resident-training-gate-.*\.json$"), None, None),  # placeholder, never matched (see CONVENTION_MAP)
    (re.compile(r"^cbase-grow-dryrun-.*\.json$"), "git_archaeology_gone",
     "evidence (b) git-archaeology confirmed gone: added by commit 2467958 "
     "(design-doc landing) containing ZERO .py files; the generator script "
     "named by the receipt's own content (cbase_grow_dryrun.py) was never "
     "added anywhere in this branch's HEAD-reachable history (git log HEAD "
     "--diff-filter=A on that path returns nothing) -- it lives on the "
     "execution-tree branch of the shared repository, unreachable from this "
     "contract branch's HEAD, same split as the import_provenance receipts."),
    (re.compile(r"^fp32-l6-compile-ab-.*\.json$"), "git_archaeology_gone",
     "evidence (b) git-archaeology confirmed gone: added by commit 9236963 "
     "('ceiling verdict HARDENED...') alongside only "
     "receipts/fp35-fused-muon-kernel-ab-20260612T215202Z.json and "
     "docs/domains/governance/archive/pre-restart/compute-ceiling-program-v1.md -- no .py file in that commit; "
     "`git log HEAD -S \"fp32-l6-compile-ab-\"` (source-file-scoped) and "
     "`--diff-filter=D` both find no script anywhere in HEAD-reachable history."),
    (re.compile(r"^fp35-fused-muon-ab-.*\.json$"), "git_archaeology_gone",
     "evidence (b) git-archaeology confirmed gone: added by commit a63974a "
     "('ceiling program: lever round-1 receipts gated...') alongside only "
     "receipts/fp32-step-econ-20260612T213856Z.json, "
     "receipts/fp35c-weight-cache-ab-20260612T214509Z.json and "
     "docs/domains/governance/archive/pre-restart/compute-ceiling-program-v1.md -- no .py file in that commit; distinct from the "
     "resolvable fp35-fused-muon-KERNEL-ab-*.json (src/ember/governance/scripts/fp35_fused_muon_kernel_ab.py)."),
    (re.compile(r"^assembly-sha-as-manifest-adjudication-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: schema=='adjudication/v1', kind=='field_semantics' -- "
     "a hand-typed disposition of a historical field-semantics question, not a script output."),
    (re.compile(r"^corpus-materiality-adjudication-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: schema=='adjudication/v1', kind=='corpus_materiality' -- "
     "hand-typed adjudication of a corpus-presence question, not a script output."),
    (re.compile(r"^c48-gate-stats-review-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: method=='<reviewer> gate consolidation — pointers grepped "
     "live + receipt contents read (not asserted)' -- a manual review consolidation, not a "
     "script output; caveats field self-describes as 'review consolidation, not a new experiment'."),
    (re.compile(r"^clicompare-leg3-d7-silencing\.json$"), "manually_authored",
     "evidence (c) manually-authored: prose claim/verdict/runtime_confirmation fields describing "
     "a manual investigation writeup (root-cause trace), not measured script output."),
    (re.compile(r"^cloud-reference-leg-disposition-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored, cross-confirmed by (b): git log --follow shows commit "
     "3b0559f adds ONLY this receipt JSON, no script; content is a per-axis prose disposition."),
    (re.compile(r"^pr1-review-verdict-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored, cross-confirmed by (b): git log --follow shows commit "
     "bcdca5f adds only this receipt + docs/domains/governance/authority/STATE.md, no script; a hand-written PR review verdict."),
    (re.compile(r"^succession-trial-\d+-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored, cross-confirmed by (b): git log --follow shows commit "
     "676fac9 adds only this receipt + docs/authority/CONTINUITY.md/README.md, no script; a hand-typed "
     "succession-trial grading record (prose verdict/score/frictions fields, no measured-data "
     "shape) -- the zero-context trial's examiner consolidation, not a script output."),
    (re.compile(r"^eng26-replay-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: a hand-run regression-replay audit receipt (producer-style "
     "engineering note); no script under scripts/ or tools/ constructs this filename."),
    (re.compile(r"^eng107-head-coverage-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: 'scope' field describes a manual checked_write-adoption "
     "coverage audit (post-rebase); no script constructs this filename."),
    (re.compile(r"^eng38-b-multi-1-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: producer==<engineer identity redacted>, build_method notes 'built inline per "
     "delegation rule' -- a hand-authored build-completion receipt; its own build_path_2 field "
     "names an existing script (src/ember/governance/scripts/corpus_patch_encode.py) as the THING BUILT, not as this "
     "receipt's generator (that script has no receipt-writing code of its own)."),
    (re.compile(r"^eng421-multimodal-config-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: producer==<engineer identity redacted>, ac_command is an inline "
     "`python -c \"...\"` assertion (no .py file token) verifying a hand-authored config file; "
     "no generating script exists because none was ever meant to."),
    (re.compile(r"^raw-corpus-materiality-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored, cross-confirmed by (b): git log --follow shows commit "
     "defcc56 adds only docs/domains/governance/authority/STATE.md + docs + this receipt, no script."),
    (re.compile(r"^heartbeat-runner-selftest-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored, cross-confirmed by (b): git log --follow shows commit "
     "9f038d7 adds ONLY this receipt JSON (13 lines), no script; commit message: 'Closes <reviewer> "
     "post-hoc audit condition: conditional signoff on #266 required the committed selftest "
     "receipt so the chain is portable' -- a hand-committed audit artifact."),
    (re.compile(r"^cold-read-reprobe-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored by design: content is prose per_dir observations from a "
     "fresh manual re-read of the repo tree (a C-LEGIB 'cold read' exercise); "
     "scripts/ember_totality/test_c_legib.py only READS receipts/cold-read-reprobe/, confirmed "
     "never writes it -- the exercise is meant to be authored freshly by whoever performs it, "
     "not scriptable (a scripted writer would defeat the point of a cold read)."),
    (re.compile(r"^v0-live-import-edition-.*\.json$"), "manually_authored",
     "evidence (c) likely manual rename: ticket=='TIMESHARE-V0-SEGMENT', same shape as "
     "scripts/timeshare_pretrain.py's run_v0_segment() output, but that script's write-site "
     "(line 2092) hardcodes f\"v0-live-{receipt['ts']}.json\" -- it never constructs the exact "
     "literal '-import-edition-' suffix; no in-tree code does. Most likely this file is a v0-live "
     "output copied/renamed post-hoc to flag the C-BASE import-edition milestone (commit 67a784e "
     "adds only this receipt + docs/domains/governance/authority/STATE.md, no script -- evidence (b) too)."),
    # --- Evidence (d) cross-branch unmerged (gh issue #431, 2026-07-08) -- restored via
    # the #415/#432 custody recovery; generating scripts confirmed real but off-branch.
    (re.compile(r"^ceff-composition-ab-20260703T111351Z\.json$"), "cross_branch_unmerged",
     "evidence (d) cross-branch unmerged: generating script src/ember/governance/scripts/ember_ceff_composition_ab.py "
     "confirmed at commit 85e6d7f (write-site line 706, `path = os.path.join(RECEIPTS, "
     "f\"ceff-composition-ab-{ts}.json\")`, exact match); `git merge-base --is-ancestor 85e6d7f HEAD` "
     "is false -- that commit is reachable only from lane/ceff-ab-run and sibling branches, never "
     "master. The real script's own source (read via `git show 85e6d7f:scripts/"
     "ember_ceff_composition_ab.py`) was re-scanned with this file's own paid-client/key-env "
     "detectors: zero hits (47943 bytes scanned)."),
    (re.compile(r"^proof-frontier-protocol-20260702T065351Z\.json$"), "cross_branch_unmerged",
     "evidence (d) cross-branch unmerged: generating script scripts/proofs/frontier_projection.py "
     "confirmed at commit e5603df (write-site line 463, `out_path = out_dir / "
     "f\"proof-frontier-protocol-{receipt['ts']}.json\"`, exact match; same script CONVENTION_MAP "
     "already names for this basename family, confirmed write-site line drifted 467->463 across "
     "intervening off-branch edits, not a mismatch). `git merge-base --is-ancestor e5603df HEAD` is "
     "false -- reachable only from goalforge/definitive-goal-20260701 and derived lane/* branches, "
     "never master. The real script's own source was re-scanned with this file's own paid-client/"
     "key-env detectors: zero hits (22941 bytes scanned)."),
    (re.compile(r"^proof-ocal-sweep-20260702T094209Z\.json$"), "cross_branch_unmerged",
     "evidence (d) cross-branch unmerged: generating script scripts/proofs/ocal_calibration_sweep.py "
     "confirmed at commit 9968c51 (write-site line 617, `out_path = out_dir / "
     "f\"proof-ocal-sweep-{receipt['ts']}.json\"`, exact match, identical line number CONVENTION_MAP "
     "already names for this basename family). `git merge-base --is-ancestor 9968c51 HEAD` is false -- "
     "reachable only from goalforge/definitive-goal-20260701 and derived lane/* branches, never "
     "master. The real script's own source was re-scanned with this file's own paid-client/key-env "
     "detectors: zero hits (32064 bytes scanned)."),
    # --- gh issue #586 (annex round-4, 2026-07-09): two more manually-authored analysis/curation
    # receipts, no cmd/script/generator field of any kind, same evidence (c) shape as
    # eng107-head-coverage-*/c48-gate-stats-review-*/eng38-b-multi-1-* above.
    (re.compile(r"^cbase-grow-rung2-stabilize-transplant-wall-diagnostic-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: a prose root-cause diagnostic (muon-routing-code citation + "
     "checkpoint-forensics reasoning, disposition per team-lead ruling), no measured-data shape and "
     "no cmd/script/generator field -- the `code_cited.file` field names "
     "scripts/timeshare_pretrain.py as the CODE BEING ANALYZED (an investigation subject), not this "
     "receipt's own generator; that script has no receipt-writing call anywhere in it constructing "
     "this filename (confirmed by exhaustive fixed-string search) -- same citation-vs-generator "
     "distinction already drawn for eng38-b-multi-1-* above."),
    (re.compile(r"^custody-curation-.*\.json$"), "manually_authored",
     "evidence (c) manually-authored: a hand-written custody-cure consolidation (8 restored "
     "artifacts + 15 cross-referenced dispositions, prose disposal_verdict) -- no measured-data "
     "shape, no cmd/script/generator field anywhere in it; same class as c48-gate-stats-review-* "
     "and eng107-head-coverage-* above."),
]

# resident-training-gate-*.json is resolved via CONVENTION_MAP (scripts/ember_resident_training_gate.py,
# confirmed --out-driven write site) -- the placeholder entry above is intentionally unreachable
# (CONVENTION_MAP is always checked first) and documents that this basename was investigated and
# is NOT an external-tree import despite one advisory field (next_command_if_blocked) mentioning a
# an external founder-state working tree (path redacted) path as a SUGGESTED fallback default, not this receipt's actual origin.
GENERATOR_ABSENT_HISTORICAL_BASENAMES = [
    (pat, subtype, note) for pat, subtype, note in GENERATOR_ABSENT_HISTORICAL_BASENAMES if note is not None
]

# Admissible values for the structural evidence_subtype field emitted on every
# generator_absent_historical / generator_absent_content_clean row -- fixed set,
# derived from which table/branch matched (never parsed back out of free-text
# notes; the tables above now carry the subtype as their own second element).
GENERATOR_ABSENT_EVIDENCE_SUBTYPES = (
    "external_tree_import", "git_archaeology_gone", "manually_authored", "cross_branch_unmerged",
)


def _check_generator_absent_historical(rel, d):
    """Returns (evidence_subtype, evidence_text) if this receipt matches the
    generator-absent-historical table, else None. Checked only after
    CONVENTION_MAP resolution has already failed. Path-prefix rules are
    checked before basename rules, then the generic import_provenance
    structural detector (2026-07-03, annex-round-3 change C)."""
    exact = GENERATOR_ABSENT_HISTORICAL_PATHS.get(rel)
    if exact is not None:
        return exact
    for prefix, subtype, evidence in GENERATOR_ABSENT_HISTORICAL_PATH_PREFIXES:
        if rel.startswith(prefix):
            return subtype, evidence
    base = os.path.basename(rel)
    for pattern, subtype, evidence in GENERATOR_ABSENT_HISTORICAL_BASENAMES:
        if pattern.match(base):
            return subtype, evidence
    # Generic structural detector (2026-07-03, annex-round-3 change C): a receipt
    # carrying a well-formed import_provenance block (source_tree AND source_commit
    # both present, non-empty strings) names its own generator's true origin as an
    # external-tree import -- evidence (a), the same evidentiary class as the
    # path-prefix/basename tables above, but derived generically from the receipt's
    # OWN JSON structure (the C4/C5/C-GROW "import-edition" convention) instead of a
    # fixed per-basename table entry. Never trusts a partial/malformed block: BOTH
    # fields must be present and non-empty, or this falls through to unresolvable.
    prov = d.get("import_provenance")
    if isinstance(prov, dict):
        source_tree = prov.get("source_tree")
        source_commit = prov.get("source_commit")
        if (isinstance(source_tree, str) and source_tree.strip()
                and isinstance(source_commit, str) and source_commit.strip()):
            return "external_tree_import", (
                "evidence (a) external-tree import: receipt carries a structural "
                f"import_provenance block naming source_tree={source_tree!r}, "
                f"source_commit={source_commit!r} (original_path="
                f"{prov.get('original_path')!r}) -- generated in that external tree "
                "and imported here with its own provenance block; the original "
                "receipt was never edited."
            )
    # Structural VOID-governance detector (2026-07-07, gh issue #353): a receipt
    # whose OWN shape is verdict=="VOID" plus a non-empty `supersedes` list is, by
    # definition, hand-authored disposition/governance text -- there is no script
    # in this tree (or any tree) that could generate a VOID verdict; a human wrote
    # the disposition. Evidence (c) manually-authored, derived generically from the
    # receipt's own structure rather than a fixed basename table entry (same
    # generic-detector pattern as the import_provenance block above). The content
    # re-scan every generator_absent_historical row gets still applies below --
    # a VOID receipt's own reason-text tripping a paid-client pattern is not waved
    # through just because its disposition is legitimate.
    if d.get("verdict") == "VOID" and isinstance(d.get("supersedes"), list) and d.get("supersedes"):
        return "manually_authored", (
            f"evidence (c) manually-authored: verdict=='VOID' with a non-empty "
            f"supersedes list ({len(d['supersedes'])} entry/entries) -- a VOID "
            "disposition is hand-authored governance/disposition text by definition; "
            "no generating script produces a VOID verdict."
        )
    return None


# --- External-live-generator table (2026-07-03, annex-round-3 change B). See the
# external_live_generator / external_generator_content_clean paragraph in the module
# docstring for the full evidentiary rationale. Each entry maps a receipt basename
# regex to an evidence-builder callable(receipt_dict) -> str; the builder quotes the
# receipt's OWN distinguishing field(s) rather than a fixed free-text string, so the
# emitted evidence is per-receipt-verifiable, not a copy-pasted template.
_EXTERNAL_LIVE_GENERATOR_FAMILY_NOTE = (
    "same train-daemon-exec family documented in cbase_v0_segment_bf16ns5_live.py's own "
    "docstring (\"This script is exec'd by the train-daemon (external live infra tree, "
    "path redacted) with NO CLI args\"); this tree's scripts/timeshare_pretrain.py "
    "defines no --conv/opt_variant flag at all (confirmed: zero matches for either "
    "string anywhere in that file), so the conv_c03_*_live.py wrappers' constructed "
    "sys.argv could never be processed by this tree's copy -- the receipt-assembly "
    "write-site for this family cannot resolve to any script this tree ships, a "
    "stronger and independently re-verified basis than the prior CONVENTION_MAP "
    "exclusion note above."
)


def _conv_segment_evidence(wrapper_script):
    def _build(d):
        return (
            f"receipt's own ticket={d.get('ticket')!r}, opt_variant={d.get('opt_variant')!r}; "
            f"dispatched via scripts/{wrapper_script} (own docstring: 'Dispatcher: "
            f"train_start with script={wrapper_script}'), " + _EXTERNAL_LIVE_GENERATOR_FAMILY_NOTE
        )
    return _build


def _ceff_derivative_evidence(cross_ref_field):
    def _build(d):
        # Quotes verdict/gate, never the receipt's own `ticket` field -- this
        # receipt family's ticket text is unrelated legacy naming from before this
        # scanner-side change and is deliberately not propagated into new output.
        return (
            f"receipt's own verdict={d.get('verdict')!r}; carries no script/cmd candidate "
            f"field of its own, and its {cross_ref_field!r} field points at "
            f"{d.get(cross_ref_field)!r}, itself one of the conv-*/ceff-* train-daemon-"
            "family receipts in this same bucket -- a derivative analysis computed from "
            "that externally-generated measurement, not an independent in-tree script "
            "output. " + _EXTERNAL_LIVE_GENERATOR_FAMILY_NOTE
        )
    return _build


EXTERNAL_LIVE_GENERATOR_BASENAMES = [
    (re.compile(r"^conv-full_fused_adamw-\d{8}T\d{6}Z\.json$"),
     _conv_segment_evidence("conv_c03_full_fused_adamw_live.py")),
    (re.compile(r"^conv-muon_ns3-\d{8}T\d{6}Z\.json$"),
     _conv_segment_evidence("conv_c03_muon_ns3_live.py")),
    (re.compile(r"^conv-muon_split-\d{8}T\d{6}Z\.json$"),
     _conv_segment_evidence("conv_c03_muon_split_live.py")),
    (re.compile(r"^conv-muon_split_bf16ns5-\d{8}T\d{6}Z\.json$"),
     _conv_segment_evidence("conv_c03_muon_split_bf16ns5_live.py")),
    (re.compile(r"^conv-muon_split_fast-\d{8}T\d{6}Z\.json$"),
     _conv_segment_evidence("conv_c03_muon_split_fast_live.py")),
    (re.compile(r"^ceff-closure-gate9-shatter-bf16ns5-\d{8}T\d{6}Z\.json$"),
     _ceff_derivative_evidence("throughput_receipt")),
    (re.compile(r"^ceff-shatter-REPUDIATED-\d{8}T\d{6}Z\.json$"),
     _ceff_derivative_evidence("repudiates_receipt")),
]


def _check_external_live_generator(rel, d):
    """Returns evidence text (structural, quoting the receipt's own field) if this
    receipt matches the external-live-generator table, else None. Checked only
    after CONVENTION_MAP and generator-absent-historical resolution have both
    already failed."""
    base = os.path.basename(rel)
    for pattern, evidence_fn in EXTERNAL_LIVE_GENERATOR_BASENAMES:
        if pattern.match(base):
            return evidence_fn(d)
    return None


# --- Attestation sidecars (2026-07-07, gh issue #353). See the ATTESTATION SIDECARS
# paragraph in the module docstring for the full mechanism and the incident it fixes.
ATTESTATION_DIR_REL = "receipts/spend-annex/attestations"

# Restricted on purpose: a sidecar may only claim one of the evidence_class values
# that ALREADY exist as annex-coverage-eligible buckets elsewhere in this scanner --
# it can never invent a brand-new class that skips classification review.
ATTESTATION_ADMISSIBLE_CLASSES = (
    "generator_absent_content_clean",
    "script_scanned_clean_via_convention",
    "external_generator_content_clean",
)

ATTESTATION_REQUIRED_FIELDS = ("target_path", "target_sha256", "evidence_class", "evidence", "cites")


def _load_attestation_sidecars(root):
    """Load every receipts/spend-annex/attestations/*.json sidecar under root.
    Returns (sidecars: dict[target_path -> sidecar_dict], skipped: list[dict]).
    A missing directory is not an error (zero sidecars, zero skipped) -- this
    mechanism is additive and optional. A malformed sidecar (parse failure,
    missing required field, or evidence_class outside the admissible set) is
    NEVER silently dropped -- it lands in `skipped` with a named reason, always
    disclosed in the run's `attestation_sidecar_skipped` output."""
    sidecars = {}
    skipped = []
    attestation_dir = os.path.join(root, *ATTESTATION_DIR_REL.split("/"))
    if not os.path.isdir(attestation_dir):
        return sidecars, skipped
    for p in sorted(glob.glob(os.path.join(attestation_dir, "*.json"))):
        rel_p = os.path.relpath(p, root).replace("\\", "/")
        try:
            with open(p, "r", encoding="utf-8-sig") as fh:
                sc = json.load(fh)
        except Exception as exc:
            skipped.append({"path": rel_p, "reason": f"parse error: {exc}"})
            continue
        if not isinstance(sc, dict) or any(k not in sc for k in ATTESTATION_REQUIRED_FIELDS):
            skipped.append({"path": rel_p, "reason": f"missing required field(s), need {ATTESTATION_REQUIRED_FIELDS}"})
            continue
        if sc["evidence_class"] not in ATTESTATION_ADMISSIBLE_CLASSES:
            skipped.append({
                "path": rel_p,
                "reason": f"evidence_class {sc['evidence_class']!r} not in admissible set "
                          f"{ATTESTATION_ADMISSIBLE_CLASSES}",
            })
            continue
        target = str(sc["target_path"]).replace("\\", "/")
        sc = dict(sc)
        sc["_sidecar_path"] = rel_p
        if target in sidecars:
            skipped.append({"path": rel_p, "reason": f"duplicate attestation for target_path {target!r} "
                                                       f"(first seen: {sidecars[target]['_sidecar_path']!r}) -- "
                                                       "first sidecar (sorted glob order) wins, this one skipped"})
            continue
        sidecars[target] = sc
    return sidecars, skipped


def _resolve_via_convention(rel):
    """Fallback for receipts with no resolvable cmd/script field: match the
    receipt's basename against CONVENTION_MAP (fixed order, first match wins)
    and confirm the mapped script still resolves in-tree. Returns the resolved
    absolute path or None -- never trusts the table without re-verifying the
    file exists right now (a mapping can go stale if a script moves)."""
    exact_script = CONVENTION_PATH_MAP.get(rel)
    if exact_script is not None:
        return resolve_in_tree(exact_script, ROOT)
    base = os.path.basename(rel)
    for pattern, script_rel in CONVENTION_MAP:
        if pattern.match(base):
            resolved = resolve_in_tree(script_rel, ROOT)
            if resolved is not None:
                return resolved
    return None


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def _scan_text_for_paid_surface(text):
    """Return (client_hits: list[str], key_env_hits: list[str]) -- sorted, deduped."""
    client_hits = sorted({name for name, pat in PAID_CLIENT_PATTERNS.items() if pat.search(text)})
    key_env_hits = sorted(set(API_KEY_ENV_NAME_RE.findall(text)))
    return client_hits, key_env_hits


def _collect_candidate_field_values(d, depth=0, max_depth=2):
    """Recursively walk a JSON-decoded structure (sorted key order at each level)
    collecting (field_name, value) pairs for every key matching (case-insensitive)
    one of CMD_FIELD_CANDIDATES. Depth-limited to avoid runaway recursion into
    unrelated large substructures; nested receipt shapes seen in this corpus
    (e.g. reproducibility.rerun_command) are one level deep."""
    out = []
    if depth > max_depth:
        return out
    if isinstance(d, dict):
        for k in sorted(d.keys()):
            v = d[k]
            lk = k.lower()
            if lk in CMD_FIELD_CANDIDATES:
                out.append((lk, v))
            if isinstance(v, (dict, list)):
                out.extend(_collect_candidate_field_values(v, depth + 1, max_depth))
    elif isinstance(d, list):
        for item in d:
            if isinstance(item, (dict, list)):
                out.extend(_collect_candidate_field_values(item, depth + 1, max_depth))
    return out


def _extract_script_tokens(value):
    """Extract script-path tokens from a candidate-field value. Handles the
    plain str/list[str] shapes plus one additional shape confirmed present in
    16+ generator scripts (e.g. scripts/econ_pass.py:387, src/ember/governance/scripts/joules.py:234,
    scripts/manifest_sha.py:169): `"generator": {"path": "scripts/x.py",
    "sha256": "..."}`. Without this, a receipt using that widely-shared shape
    parks its own real script path unread and falls through to unresolvable
    even though the generating script is named right there in the JSON --
    confirmed gh issue #17 second-pass finding, 2026-07-03."""
    tokens = []
    if isinstance(value, str):
        tokens.extend(_SCRIPT_TOKEN_RE.findall(value))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                tokens.extend(_SCRIPT_TOKEN_RE.findall(item))
            elif isinstance(item, dict):
                v = item.get("path")
                if isinstance(v, str):
                    tokens.extend(_SCRIPT_TOKEN_RE.findall(v))
    elif isinstance(value, dict):
        v = value.get("path")
        if isinstance(v, str):
            tokens.extend(_SCRIPT_TOKEN_RE.findall(v))
    return tokens


def _resolve_generating_script(receipt_dict):
    """Returns (resolved_path_or_None, fields_seen: list[str], fields_with_unresolved_token: list[str]).
    Iterates CMD_FIELD_CANDIDATES in fixed priority order; within a field, tokens
    are tried in the order extracted. First on-disk in-tree resolution wins."""
    pairs = _collect_candidate_field_values(receipt_dict)
    by_field = {}
    for name, value in pairs:
        by_field.setdefault(name, []).append(value)

    fields_seen = [f for f in CMD_FIELD_CANDIDATES if f in by_field]
    fields_with_unresolved_token = []

    for field in CMD_FIELD_CANDIDATES:
        if field not in by_field:
            continue
        any_token = False
        for value in by_field[field]:
            for token in _extract_script_tokens(value):
                any_token = True
                resolved = resolve_in_tree(token, ROOT)
                if resolved is not None:
                    return resolved, fields_seen, fields_with_unresolved_token
        if any_token:
            fields_with_unresolved_token.append(field)

    return None, fields_seen, fields_with_unresolved_token


def _tree_wide_scan():
    """One-time, receipt-independent sweep: (1) every script under scripts/ for
    paid-API-key env-var names; (2) every file under config/ or configs/ for an
    api_key-shaped line naming a paid provider. Sorted walks; deterministic."""
    flagged_scripts = []
    scripts_scanned = 0
    script_glob = sorted(glob.glob(os.path.join(ROOT, "scripts", "**", "*"), recursive=True))
    for p in script_glob:
        if not os.path.isfile(p) or not p.lower().endswith(SCRIPT_SCAN_EXTS):
            continue
        scripts_scanned += 1
        text = _read_text(p)
        if text is None:
            continue
        hits = sorted(set(API_KEY_ENV_NAME_RE.findall(text)))
        if hits:
            flagged_scripts.append({"path": os.path.relpath(p, ROOT).replace("\\", "/"), "env_names": hits})

    flagged_configs = []
    configs_scanned = 0
    for cfg_dir in ("config", "configs"):
        cfg_glob = sorted(glob.glob(os.path.join(ROOT, cfg_dir, "**", "*"), recursive=True))
        for p in cfg_glob:
            if not os.path.isfile(p):
                continue
            configs_scanned += 1
            text = _read_text(p)
            if text is None:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if "api_key" in line.lower() and PAID_PROVIDER_NAME_RE.search(line):
                    flagged_configs.append({
                        "path": os.path.relpath(p, ROOT).replace("\\", "/"),
                        "line": lineno,
                    })

    return {
        "scripts_scanned": scripts_scanned,
        "configs_scanned": configs_scanned,
        "flagged_scripts": sorted(flagged_scripts, key=lambda r: r["path"]),
        "flagged_configs": sorted(flagged_configs, key=lambda r: (r["path"], r["line"])),
        "clean": (not flagged_scripts) and (not flagged_configs),
    }


def _row_for_declared(rel, path, d):
    return {
        "path": rel,
        "sha256": sha256_file(path),
        "evidence_class": "declared",
        "scanned_surfaces": [],
        "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
        "declared_api_spend_usd": d.get(SPEND_KEY),
        "declared_paid_api_surface_used": d.get(PAID_FLAG_KEY),
        "notes": "receipt already declares both clear-packet fields; passed through unchanged",
    }


def main(out_path=None):
    if ROOT is None:
        result = {
            "spec": "gh issue #17 FROZEN SPEC v1",
            "root": None,
            "verdict": "UNEVALUABLE",
            "verdict_reason": "state root not found under any known layout "
                               f"({c_neg1.CANDIDATE_ROOTS})",
            "rows": [],
            "counts": {},
            "excluded_ledger": [],
            "excluded_superseded": [],
            "attestation_sidecar_skipped": [],
        }
        _emit(result, out_path)
        return result

    decisive = c_neg1._decisive_claim_files()
    tree_wide = _tree_wide_scan()
    flagged_script_relpaths = {f["path"] for f in tree_wide["flagged_scripts"]}
    attestation_sidecars, attestation_sidecar_skipped = _load_attestation_sidecars(ROOT)

    # VOID-supersession (2026-07-07, gh issue #353; factored into a shared
    # helper module consumed by BOTH this scanner and test_c_neg1.py's own
    # decisive-claim corpus per gh issue #358 -- see void_supersession.py's
    # module docstring for the full semantics and the cbase-checkpoint-sha
    # non-match case).
    decisive, excluded_superseded = void_supersession.partition_superseded(decisive, ROOT)

    rows = []
    excluded_ledger = []
    for path, d, raw in decisive:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")

        # CORPUS-MEMBERSHIP RULE (2026-07-03, annex-round-3 change A) -- see the
        # module docstring. This scanner's own output family never enters the
        # per-row classification loop at all: no evidence_class, never counted
        # toward unresolvable/uncovered, listed separately and honestly instead.
        if SPEND_ANNEX_SELF_ROW_RE.match(rel):
            excluded_ledger.append({
                "path": rel,
                "sha256": sha256_file(path),
                "reason": "annex's own output family (receipts/spend-annex/spend-annex-*.json) "
                          "-- the annex is the coverage LEDGER, not a decisive experimental "
                          "claim (its own verdict field describes annex-scan coverage, not a "
                          "training/eval result); excluded from the decisive-claim corpus by "
                          "the corpus-membership rule, never classified, never counted toward "
                          "unresolvable -- this also stops each regeneration from adding a new "
                          "unresolvable self-row.",
            })
            continue

        receipt_sha = sha256_file(path)

        has_both = (SPEND_KEY in d) and (PAID_FLAG_KEY in d)
        if has_both:
            rows.append(_row_for_declared(rel, path, d))
            continue

        resolved, fields_seen, fields_with_unresolved_token = _resolve_generating_script(d)

        via_convention = False
        if resolved is None:
            resolved = _resolve_via_convention(rel)
            via_convention = resolved is not None

        if resolved is None:
            historical = _check_generator_absent_historical(rel, d)
            if historical is not None:
                evidence_subtype, historical_evidence = historical
                # Narrowing (2026-07-03, session review): evidence (a)/(b) only prove
                # the SCRIPT is absent, not that SPEND is absent -- a hand-pasted paid-
                # model output would ride through with no script in the loop at all.
                # Scan the receipt's OWN raw text (already read by _decisive_claim_files,
                # not re-read from disk) with the identical paid-surface detectors used
                # for resolved scripts below.
                content_client_hits, content_key_env_hits = _scan_text_for_paid_surface(raw)
                if content_client_hits or content_key_env_hits:
                    reasons = []
                    if content_client_hits:
                        reasons.append(f"paid-client pattern(s) in receipt's own content: {content_client_hits}")
                    if content_key_env_hits:
                        reasons.append(f"paid-API-key env name(s) in receipt's own content: {content_key_env_hits}")
                    rows.append({
                        "path": rel,
                        "sha256": receipt_sha,
                        "evidence_class": "generator_absent_historical",
                        "evidence_subtype": evidence_subtype,
                        "scanned_surfaces": SCANNED_SURFACES,
                        "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                        "resolved_script": None,
                        "content_scan_hits": {
                            "client_patterns": content_client_hits,
                            "key_env_names": content_key_env_hits,
                        },
                        "notes": f"{historical_evidence} CONTENT-DIRTY on re-scan of the receipt's own "
                                 f"text: {'; '.join(reasons)} -- script-absence evidence still holds, "
                                 "but this does NOT count as spend-clean; does not itself flip verdict "
                                 "(see paid_surface_violation gap note in module docstring).",
                    })
                    continue
                rows.append({
                    "path": rel,
                    "sha256": receipt_sha,
                    "evidence_class": "generator_absent_content_clean",
                    "evidence_subtype": evidence_subtype,
                    "scanned_surfaces": SCANNED_SURFACES,
                    "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                    "resolved_script": None,
                    "notes": f"{historical_evidence} Receipt's own content scanned clean: zero "
                             "paid-client pattern or paid-API-key env name hits.",
                })
                continue

            external_live_evidence = _check_external_live_generator(rel, d)
            if external_live_evidence is not None:
                # Same narrowing as generator_absent_historical above: this evidence
                # proves the receipt-assembly step is external, not that spend is
                # absent -- scan the receipt's own raw text with the identical
                # paid-surface detectors before accepting it as clean.
                content_client_hits, content_key_env_hits = _scan_text_for_paid_surface(raw)
                if content_client_hits or content_key_env_hits:
                    reasons = []
                    if content_client_hits:
                        reasons.append(f"paid-client pattern(s) in receipt's own content: {content_client_hits}")
                    if content_key_env_hits:
                        reasons.append(f"paid-API-key env name(s) in receipt's own content: {content_key_env_hits}")
                    rows.append({
                        "path": rel,
                        "sha256": receipt_sha,
                        "evidence_class": "external_live_generator",
                        "scanned_surfaces": SCANNED_SURFACES,
                        "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                        "resolved_script": None,
                        "external_generator_evidence": external_live_evidence,
                        "content_scan_hits": {
                            "client_patterns": content_client_hits,
                            "key_env_names": content_key_env_hits,
                        },
                        "notes": f"{external_live_evidence} CONTENT-DIRTY on re-scan of the receipt's "
                                 f"own text: {'; '.join(reasons)} -- external-live-generator evidence "
                                 "still holds, but this does NOT count as spend-clean; does not itself "
                                 "flip verdict (see paid_surface_violation gap note in module docstring).",
                    })
                    continue
                rows.append({
                    "path": rel,
                    "sha256": receipt_sha,
                    "evidence_class": "external_generator_content_clean",
                    "scanned_surfaces": SCANNED_SURFACES,
                    "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                    "resolved_script": None,
                    "external_generator_evidence": external_live_evidence,
                    "notes": f"{external_live_evidence} Receipt's own content scanned clean: zero "
                             "paid-client pattern or paid-API-key env name hits.",
                })
                continue

            # Attestation-sidecar fallback (2026-07-07, gh issue #353) -- the LAST
            # resolution path before plain unresolvable. See ATTESTATION SIDECARS in
            # the module docstring: pin check, then content check (content-dirty
            # ALWAYS overrides a valid attestation), then and only then the sidecar's
            # declared evidence_class is honored.
            attestation = attestation_sidecars.get(rel)
            if attestation is not None:
                # Direct pin: sidecar's target_sha256 matches the receipt's CURRENT
                # on-disk hash. Redaction-chain pin (gh issue #428): the receipt
                # mutated legitimately AFTER attestation via a custody redaction
                # pass, which self-documents the pre-redaction hash on the receipt's
                # own `redaction.original_sha256` field -- see the REDACTION-CHAIN
                # PIN paragraph in the module docstring. Never trusts a redaction
                # block that doesn't itself match the sidecar's pin.
                pin_match = None
                if attestation["target_sha256"] == receipt_sha:
                    pin_match = "direct"
                else:
                    redaction = d.get("redaction")
                    if (isinstance(redaction, dict)
                            and isinstance(redaction.get("original_sha256"), str)
                            and redaction["original_sha256"] == attestation["target_sha256"]):
                        pin_match = "redaction_chain"

                if pin_match is None:
                    rows.append({
                        "path": rel,
                        "sha256": receipt_sha,
                        "evidence_class": "unresolvable",
                        "scanned_surfaces": [],
                        "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                        "resolved_script": None,
                        "notes": (
                            f"an attestation sidecar exists at {attestation['_sidecar_path']!r} but its "
                            f"pinned target_sha256={attestation['target_sha256']!r} does NOT match this "
                            f"receipt's current on-disk sha256={receipt_sha!r}, nor does it match a "
                            "self-documented redaction.original_sha256 on the receipt (redaction-chain "
                            "pin, issue #428) -- the target has been mutated since attestation for an "
                            "unexplained reason, the pin is invalid, and the attestation is REJECTED "
                            "(sha-pin invalidation, issue #353); treated as if no attestation existed. "
                            f"fields_present={fields_seen or 'none'}, "
                            f"fields_with_unresolved_token={fields_with_unresolved_token or 'none'}"
                        ),
                    })
                    continue
                content_client_hits, content_key_env_hits = _scan_text_for_paid_surface(raw)
                if content_client_hits or content_key_env_hits:
                    reasons = []
                    if content_client_hits:
                        reasons.append(f"paid-client pattern(s) in receipt's own content: {content_client_hits}")
                    if content_key_env_hits:
                        reasons.append(f"paid-API-key env name(s) in receipt's own content: {content_key_env_hits}")
                    rows.append({
                        "path": rel,
                        "sha256": receipt_sha,
                        "evidence_class": "unresolvable",
                        "scanned_surfaces": SCANNED_SURFACES,
                        "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                        "resolved_script": None,
                        "content_scan_hits": {
                            "client_patterns": content_client_hits,
                            "key_env_names": content_key_env_hits,
                        },
                        "notes": f"an attestation sidecar exists at {attestation['_sidecar_path']!r} "
                                 f"(sha-pin verified via {pin_match}) citing: {attestation['evidence']} -- but "
                                 "content-dirty ALWAYS overrides attestation (issue #353), re-scanned "
                                 f"against the receipt's CURRENT text: {'; '.join(reasons)}. "
                                 "Attestation REJECTED.",
                    })
                    continue
                notes = (f"sha-pin verified via {pin_match} against {attestation['_sidecar_path']!r}; "
                         f"receipt's own CURRENT content scanned clean. Evidence: {attestation['evidence']}")
                if pin_match == "redaction_chain":
                    redaction = d["redaction"]
                    notes += (
                        f" Redaction-chain pin (issue #428): this receipt was redacted at "
                        f"{redaction.get('redaction_ts')!r} (reason: {redaction.get('reason')!r}) AFTER "
                        f"the attestation was written -- the sidecar's pinned hash matches the receipt's "
                        f"own self-documented pre-redaction redaction.original_sha256, not its current hash."
                    )
                rows.append({
                    "path": rel,
                    "sha256": receipt_sha,
                    "evidence_class": attestation["evidence_class"],
                    "evidence_subtype": "attested_sidecar",
                    "attestation_pin_match": pin_match,
                    "scanned_surfaces": SCANNED_SURFACES,
                    "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                    "resolved_script": None,
                    "attestation_sidecar": attestation["_sidecar_path"],
                    "attestation_cites": attestation["cites"],
                    "notes": notes,
                })
                continue

            rows.append({
                "path": rel,
                "sha256": receipt_sha,
                "evidence_class": "unresolvable",
                "scanned_surfaces": [],
                "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                "resolved_script": None,
                "notes": (
                    f"no candidate field yielded an in-tree script path, and no "
                    f"CONVENTION_MAP entry matches this basename either; "
                    f"fields_present={fields_seen or 'none'}, "
                    f"fields_with_unresolved_token={fields_with_unresolved_token or 'none'}"
                ),
            })
            continue

        script_text = _read_text(resolved) or ""
        client_hits, key_env_hits = _scan_text_for_paid_surface(script_text)
        resolved_rel = os.path.relpath(resolved, ROOT).replace("\\", "/")
        tree_wide_hit = resolved_rel in flagged_script_relpaths

        if client_hits or key_env_hits or tree_wide_hit:
            reasons = []
            if client_hits:
                reasons.append(f"paid-client pattern(s): {client_hits}")
            if key_env_hits:
                reasons.append(f"paid-API-key env name(s): {key_env_hits}")
            if tree_wide_hit and not key_env_hits:
                reasons.append("flagged by tree-wide key-env sweep")
            if via_convention:
                reasons.append("resolved via CONVENTION_MAP (filename-pattern mapping), not a receipt field")
            rows.append({
                "path": rel,
                "sha256": receipt_sha,
                "evidence_class": "paid_surface_violation",
                "scanned_surfaces": SCANNED_SURFACES,
                "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                "resolved_script": resolved_rel,
                "resolved_script_sha256": sha256_file(resolved),
                "notes": "; ".join(reasons),
            })
            continue

        if via_convention:
            rows.append({
                "path": rel,
                "sha256": receipt_sha,
                "evidence_class": "script_scanned_clean_via_convention",
                "scanned_surfaces": SCANNED_SURFACES,
                "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
                "resolved_script": resolved_rel,
                "resolved_script_sha256": sha256_file(resolved),
                "notes": f"no cmd/script field present; generating script resolved via CONVENTION_MAP "
                         f"filename-pattern mapping (confirmed write-site, see CONVENTION_MAP comment); "
                         "no paid-client pattern or paid-API-key env name found in its source text",
            })
            continue

        rows.append({
            "path": rel,
            "sha256": receipt_sha,
            "evidence_class": "script_scanned_clean",
            "scanned_surfaces": SCANNED_SURFACES,
            "verdict_pass_class": bool(c_neg1._is_pass_class(d.get(c_neg1.VERDICT_KEY, ""))),
            "resolved_script": resolved_rel,
            "resolved_script_sha256": sha256_file(resolved),
            "notes": f"generating script resolved via field(s) {fields_seen}; "
                     "no paid-client pattern or paid-API-key env name found in its source text",
        })

    counts = {
        "decisive_total": len(decisive),
        "excluded_ledger": len(excluded_ledger),
        "excluded_superseded": len(excluded_superseded),
        "declared": sum(1 for r in rows if r["evidence_class"] == "declared"),
        "script_scanned_clean": sum(1 for r in rows if r["evidence_class"] == "script_scanned_clean"),
        "script_scanned_clean_via_convention": sum(
            1 for r in rows if r["evidence_class"] == "script_scanned_clean_via_convention"),
        "generator_absent_historical": sum(
            1 for r in rows if r["evidence_class"] == "generator_absent_historical"),
        "generator_absent_content_clean": sum(
            1 for r in rows if r["evidence_class"] == "generator_absent_content_clean"),
        "external_live_generator": sum(1 for r in rows if r["evidence_class"] == "external_live_generator"),
        "external_generator_content_clean": sum(
            1 for r in rows if r["evidence_class"] == "external_generator_content_clean"),
        "unresolvable": sum(1 for r in rows if r["evidence_class"] == "unresolvable"),
        "paid_surface_violation": sum(1 for r in rows if r["evidence_class"] == "paid_surface_violation"),
        "attested_via_sidecar": sum(1 for r in rows if r.get("evidence_subtype") == "attested_sidecar"),
        "attestation_sidecar_skipped": len(attestation_sidecar_skipped),
    }

    violation_rows = [r for r in rows if r["evidence_class"] == "paid_surface_violation"]
    if violation_rows:
        sample = [r["path"] for r in violation_rows[:5]]
        verdict = "FAIL"
        verdict_reason = (
            f"{len(violation_rows)} row(s) show a paid-surface dependency in their "
            f"generating script -> condition NOT proven zero-cost. sample={sample}"
        )
    else:
        verdict = "PASS"
        verdict_reason = (
            f"zero rows show a paid-surface dependency across {len(decisive)} decisive-claim "
            f"receipts ({counts['excluded_ledger']} excluded as this scanner's own coverage-ledger "
            f"output family, {counts['excluded_superseded']} excluded as VOID-superseded (issue #353), "
            f"neither classified/never counted toward uncovered; {len(rows)} "
            f"classified: {counts['declared']} "
            f"declared, {counts['script_scanned_clean']} "
            f"script-scanned-clean, {counts['script_scanned_clean_via_convention']} "
            f"script-scanned-clean-via-convention, {counts['generator_absent_content_clean']} "
            f"generator-absent-content-clean (evidenced external-import/git-archaeology/manual-authorship "
            f"gone AND the receipt's own content re-scanned clean; {counts['attested_via_sidecar']} of "
            "these via a sha-pinned, content-re-verified attestation sidecar, issue #353), "
            f"{counts['external_generator_content_clean']} "
            "external-generator-content-clean (evidenced train-daemon-family external-live generator AND "
            f"the receipt's own content re-scanned clean), {counts['generator_absent_historical']} "
            f"generator-absent-historical still CONTENT-DIRTY on re-scan (script-absence evidence holds "
            "but the receipt's own content trips a paid-client pattern or key-env name -- see "
            f"content_scan_hits per row; this does not itself flip verdict), {counts['external_live_generator']} "
            "external-live-generator still CONTENT-DIRTY on re-scan (same non-flipping treatment), "
            f"{counts['unresolvable']} "
            "unresolvable -- unresolvable rows are coverage gaps, listed honestly, and do not "
            "themselves block PASS)"
        )

    result = {
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "ticket": TICKET,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "spec": "gh issue #17 FROZEN SPEC v1",
        "root_id": "repository-root",
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "counts": counts,
        "tree_wide_scan": tree_wide,
        "excluded_ledger": sorted(excluded_ledger, key=lambda r: r["path"]),
        "excluded_superseded": sorted(excluded_superseded, key=lambda r: r["path"]),
        "attestation_sidecar_skipped": sorted(attestation_sidecar_skipped, key=lambda r: r["path"]),
        "rows": sorted(rows, key=lambda r: r["path"]),
    }
    _emit(result, out_path)
    return result


def _emit(result, out_path):
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=2, sort_keys=False)
            fh.write("\n")
    print(f"{result['verdict']} spend-annex: {result.get('verdict_reason', '')}")


if __name__ == "__main__":
    _out = sys.argv[1] if len(sys.argv) > 1 else None
    main(_out)
