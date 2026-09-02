# Probe-authoring contract (execution-binding checklist)

Refs #740. Motivated by #683 (C-EFF's original self-attestation false-GREEN, audit receipt
`receipts/ember-totality-audit/audit-20260710T145200Z.json`) and the C6/C12 hardening in PR #741.
This document is the binding checklist every NEW `scripts/ember_totality/test_*.py` status probe
must satisfy before it is trusted to gate a §4 condition, plus a full sweep of the 40 probes that
existed at the time of writing, classifying every GREEN-producing predicate as EXECUTION-BOUND or
SELF-ATTESTED.

## Why this exists

A status probe's job is to decide RED/GREEN by inspecting a receipt. The failure mode #683 named:
a probe that only checks a receipt's *own* self-reported fields (a JSON key exists, a boolean says
`true`, a string says `"verified"`) can be turned GREEN by a ~15-line hand-authored JSON with no
real execution behind it — the receipt author and the probe are trusting the same document. The
cure is never "add more fields to check" — it is **recomputation from material the receipt's
author did not also author**: real git objects, real file bytes, a live subprocess re-run, or a
different receipt's independently-timestamped claim.

## The checklist

A new probe (or a PR hardening an existing one) must satisfy all of the following for every
predicate that is **decisive** — i.e. any predicate whose truth is individually necessary or, via
an OR/early-return, individually *sufficient* for GREEN:

1. **Recompute, don't trust, the decisive number.** If a receipt asserts a quantity (ratio, count,
   duration, score, FLOPs, percentage) that determines RED/GREEN, the probe recomputes it from
   lower-level raw fields via a known formula and compares within an explicit tolerance — it never
   reads a pre-aggregated field as ground truth. Templates: `test_c_eff.py`'s FLOPs recompute
   (`6*params*batch*seq*total_steps` cross-checked against the parsed `g_budget.detail` text) and
   `effective_days` recompute; `test_c_scale.py`'s `_ratio_ok`; `test_c5.py`'s aggregate-delta
   recompute from raw per-row scores; `test_c_grow.py`'s FLOP-total recompute.

2. **Sha-pin every cited artifact to its provenance commit.** A claim that a file/commit/harness
   produced a result must resolve to a real git object (`git cat-file -t`), and the artifact's
   actual bytes must sha256-match the receipt's claimed hash — never an inert cosmetic hash field.
   Templates: `test_c_eff.py`'s `harness_sha` binding (issue #683 cure); `test_c12.py`'s
   `_verify_selector_sha_pin` (`git show <sha>:<path>` + sha256); `test_c15.py`'s C14-gate sha
   cross-check; `test_c_base.py`'s `model.pt` weight-hash check; `test_c_neg1.py`'s annex
   anti-staleness sha binding.

3. **Resolve and parse every cited file — never existence-only.** `os.path.isfile()` proves
   nothing; the probe must open, parse, and inspect the cited file's actual structured content
   before treating its claim as evidence. Templates: `test_c_auto.py`'s window-receipt
   resolve+parse+ts cross-check; `test_c1.py`'s `resolve_in_tree` + `sha256_file`.

4. **Cross-reference independently-authored artifacts — same-document self-consistency proves
   nothing.** A number is only meaningfully verified when checked against a *different* document
   or process the claim's author did not write in the same breath (a prior milestone's own
   receipt, a live `git log`, a re-executed subprocess, a second independently-dated receipt). Two
   fields inside the same JSON blob agreeing with each other is not verification — a fabricator
   writes both. Templates: `test_c11.py`'s cross-tier `inherited_active_seconds` chain (each
   tier's claim checked against the *prior tier's own* recorded value); `test_c0.py`'s disposition
   re-vetted against its authorizing receipt via the identical gate-vetting computation;
   `test_surface2.py`'s git-HEAD-vs-receipt-ts staleness check; `test_c_disc.py` /
   `test_c_enf.py`'s live subprocess re-execution with exit-code-vs-printed-verdict coherence.

5. **No self-attested field may be independently sufficient for GREEN.** Structural/schema/
   presence checks (a field exists, a string matches a pattern) may remain as auxiliary gates, but
   must be ANDed with — never substitutable for — the execution-bound checks above. A probe with
   an early-return/OR shortcut on a bare boolean or string is a bypass by construction, even when a
   stronger structured path exists elsewhere in the same function. **This sweep found the
   anti-pattern still live**: `test_c6.py:339-343`'s `find_rerun_verification()` returns as soon
   as any of `RERUN_VERIFICATION_KEYS` (e.g. `rerun_verified: true`) is truthy — *before* the
   structured `deterministic_mismatch` execution-bound path (the one PR #741 actually hardened) is
   ever reached. A receipt author can write `{"reproducibility": {"rerun_verified": true}}` with
   zero real rerun evidence and pass C6's CHK today. Treat this as the canonical negative example.

6. **Negative-token scans are a floor, never a substitute for positive execution-binding.**
   Scanning receipt text for a "does NOT count" marker only catches a fabricator who *admits* to
   fabricating; it does nothing against silent omission. A probe whose only positive-evidence
   check is invalid-token absence is self-attested regardless of how carefully the token list is
   curated or structurally scrubbed (compare `test_c11.py`'s `why_not_*`-aware scrubbing, still
   only a floor, against the plain substring scans in `test_c_fed.py` / `test_c_anat.py`, which
   are the *entire* probe).

7. **A missing/absent field is a REJECT, never a silent pass.** Every field the probe inspects for
   the decisive claim is checked for presence and type before use; `d.get(x, default)` that lets a
   missing critical field fall through to a truthy default repeats the failure of trusting a
   fabricated value. Template: `test_c_eff.py`'s explicit-`False`-not-absent pattern for
   `dry_run` / `no_gpu` / `confirmation_run.synthetic` (issue #683 cure point 1).

8. **Ship a negative fixture.** The PR that adds or hardens a probe demonstrates at least one
   deliberately-broken/fabricated fixture receipt that the probe correctly turns RED on — proving
   the execution-binding checks actually fire, not just that the happy path parses. (Generalizes
   the `ceff-shatter-REPUDIATED-*.json` precedent and #683's own audit-discovered false-GREEN as
   the motivating failure this checklist exists to prevent.)

9. **UNEVALUABLE vs RED is a real distinction — keep it, and don't let it leak.** Input-missing
   (the root/receipt-dir genuinely does not exist) is UNEVALUABLE, not RED. But once an artifact
   IS present, every check on it is binding: a present-but-defective artifact is RED, never
   silently downgraded back to UNEVALUABLE to avoid a hard failure.

## Severity triage for existing debt (how to read the appendix)

Not every SELF-ATTESTED row below is equally urgent. Two tiers:

- **Bypass (HIGH):** a single self-attested field is, by itself, sufficient for GREEN via an
  OR/early-return — an adversary needs to fabricate exactly one value. Confirmed instances found
  in this sweep: `test_c6.py:339-343` (`RERUN_VERIFICATION_KEYS` bare-truthy short-circuit, **live
  despite PR #741**), `test_c8.py:131-134` (incumbent exact-string shortcut bypasses all other
  ablation checks), `test_c_grow.py:256-257` (`measured_on_train_daemon==True` outright-pass
  shortcut bypassing the entire "instrumented execution" requirement).
- **Weak-AND (standing debt):** the self-attested field is one of several ANDed conditions, so a
  false GREEN requires fabricating multiple fields consistently — real debt (still no independent
  verification of any of them), but not a single-flag bypass. The large majority of rows below are
  this tier.

Recompute-cheap SELF-ATTESTED findings (a same-file recompute or an in-tree resolve+hash would
close them, following the `test_c1.py` / `test_c5.py` / `_lane14_common.py` pattern already used
elsewhere in this suite) are marked `[cheap]` inline; the rest are `[expensive]` (need a new
cross-file/live-subprocess mechanism, e.g. `test_c_fed.py`'s entirely-textual design-doc checks,
which cannot be recomputed without a different kind of evidence entirely). No probe is modified in
this PR — every SELF-ATTESTED row is standing debt for a follow-up lane.

## Sweep appendix — all 40 probes, every GREEN-producing predicate classified

Method: read every `scripts/ember_totality/test_*.py` in full; for each, enumerated every
meaningfully distinct positive-evidence (GREEN-producing) check and classified it EXECUTION-BOUND
or SELF-ATTESTED per the checklist above. `test_c_eff.py` and `test_c11.py` (cited above as
templates) are included for completeness — even they are majority self-attested BY PREDICATE
COUNT (structural/schema fields still trusted as written), which is expected and fine: their value
as templates is that their *decisive* claims (FLOPs, sha-provenance, cross-tier chain,
effective_days) are the ones that are execution-bound, per checklist item 5's AND-composition
principle, not that literally every field is recomputed.

Totals: **40 probes swept, 322 predicates classified, 245 SELF-ATTESTED (76%), 77 EXECUTION-BOUND.**

### test_c_eff.py (16 predicates, 11 self-attested) — cited template, hybrid

| predicate | class | evidence |
|---|---|---|
| `ceff-RESOLVED-*.json` exists | SELF-ATTESTED `[cheap]` | test_c_eff.py:172-184 — presence-only glob, content unread at this point |
| invalid-token absence in raw receipt text | SELF-ATTESTED | test_c_eff.py:198-202 — substring scan of self-authored text |
| `verdict` in `{SHATTER, PRICED_SCALEOUT_RESIDUAL}` | SELF-ATTESTED | test_c_eff.py:205-207 — self-reported string trust |
| `effective_days_basis` == fixed string | SELF-ATTESTED | test_c_eff.py:210-214 — self-reported string trust |
| `useful_base_tokens`/`sustained_tok_s`/`effective_days`/`compound_speedup_over_anchor` present+numeric | SELF-ATTESTED | test_c_eff.py:216-227 — presence/type only |
| `gate` field contains "gate-9"/"gate9" | SELF-ATTESTED | test_c_eff.py:230-232 — substring trust |
| `dry_run`/`no_gpu`/`confirmation_run.synthetic` explicitly `False` | SELF-ATTESTED | test_c_eff.py:237-249 — still a self-reported value (stronger than most: absence rejects) |
| `import_provenance.source_commit_sha` resolves to real git commit | EXECUTION-BOUND | test_c_eff.py:261-267 — `git cat-file -t` |
| commit's own diff touches claimed receipt path | EXECUTION-BOUND | test_c_eff.py:269-278 — `git show --stat` on real commit |
| `harness_sha` == real sha256 of harness file at that commit | EXECUTION-BOUND | test_c_eff.py:280-306 — `git show <sha>:<path>` + sha256 |
| governor free/total VRAM plausibility range | SELF-ATTESTED | test_c_eff.py:316-327 — bound-check on two self-reported numbers, no live query |
| FLOPs recompute `6*params*batch*seq*steps` vs parsed `g_budget.detail` cost | EXECUTION-BOUND | test_c_eff.py:329-369 — recompute from raw fields, cross-checked vs a text-embedded independent figure |
| `confirmation_run.sustained_tok_s` within band of `projected_tok_s` | SELF-ATTESTED | test_c_eff.py:373-383 — band-check between two self-reported numbers, no rerun |
| `effective_days` == `ubt/(tok_s*86400)` | EXECUTION-BOUND | test_c_eff.py:385-392 — internal arithmetic recompute |
| SHATTER magnitude (`compound>=3.3`, `eff_days<=1`) | SELF-ATTESTED | test_c_eff.py:394-402 — threshold-check on self-reported numbers |
| `c04_deciding_axes` map present, each axis APPLIED/KILLED/WAIVED | SELF-ATTESTED | test_c_eff.py:404-414 — self-reported map trust |

### test_c11.py (8 predicates, 5 self-attested) — cited template, hybrid

| predicate | class | evidence |
|---|---|---|
| invalid-token absence (structurally scrubbed of `why_not_*` negations) | SELF-ATTESTED | test_c11.py:138-185 — still a text scan of self-authored content, just a better floor than most |
| `earned` = `sleep_padding_seconds==0` AND `active_seconds>=target` | SELF-ATTESTED | test_c11.py:238-249 — both fields self-reported |
| `load_bearing` = all 5 capacity flags true | SELF-ATTESTED | test_c11.py:252-258 — self-reported boolean map |
| `deletion_sensitive` = degrades flag + next-action disallowed | SELF-ATTESTED | test_c11.py:260-274 — self-reported boolean fields |
| `wall_consistent` = `this_run_active_seconds <= wall_seconds` | SELF-ATTESTED `[cheap]` | test_c11.py:277-297 — bound-check between two fields in the SAME receipt, no independent measurement |
| cross-tier `inherited_active_seconds` matches prior tier's own recorded `active_seconds` | EXECUTION-BOUND | test_c11.py:358-375 — cross-references a DIFFERENT file's independently-authored value |
| cross-tier arithmetic `active_seconds == inherited + this_run` | EXECUTION-BOUND | test_c11.py:377-387 — internal + cross-file reconciliation |
| inter-tier `ts` separation >= incremental milestone target | EXECUTION-BOUND | test_c11.py:389-405 — real timestamp cross-check between two independently-dated receipts |

### Batch A — test_c0–test_c7 (65 predicates, 44 self-attested)

| probe | predicate | class | evidence |
|---|---|---|---|
| test_c0.py | vacuous GREEN when zero gate + zero loop receipts in window | EXECUTION-BOUND | test_c0.py:573-580 — real glob enumeration, nothing to disprove |
| test_c0.py | C14 gate receipt verdict/status self-report | SELF-ATTESTED | test_c0.py:314-315,351 |
| test_c0.py | component_status all PASS | SELF-ATTESTED | test_c0.py:361-364 |
| test_c0.py | invalid-token absence in verdict/status/interp/parity text | SELF-ATTESTED | test_c0.py:354-368 |
| test_c0.py | conflation-guard PASS revocation via second receipt's own verdict | SELF-ATTESTED | test_c0.py:331-349 |
| test_c0.py | BLOCKED-run supersession via effective ts ordering | EXECUTION-BOUND | test_c0.py:311-326,377-386 |
| test_c0.py | earliest C14 PASS predates earliest loop stamp | EXECUTION-BOUND | test_c0.py:615-632,639-643 |
| test_c0.py | disposition exact-set sha256 match vs live loop artifacts | EXECUTION-BOUND | test_c0.py:462-484 |
| test_c0.py | disposition same-epoch binding vs independently-derived epoch | EXECUTION-BOUND | test_c0.py:449-453 |
| test_c0.py | disposition `operator_visibility.surfaced_via` non-empty | SELF-ATTESTED `[cheap]` | test_c0.py:456-460 |
| test_c0.py | authorizing C14 receipt sha256 verified | EXECUTION-BOUND | test_c0.py:489-494 |
| test_c0.py | authorizing receipt re-vetted as real in-window PASS | EXECUTION-BOUND | test_c0.py:496-505 |
| test_c1.py | discovery receipt `candidates` non-empty | SELF-ATTESTED `[cheap]` | test_c1.py:113-116 |
| test_c1.py | candidate URLs http-prefixed | SELF-ATTESTED | test_c1.py:119-123 |
| test_c1.py | `license_or_access_basis` truthy | SELF-ATTESTED | test_c1.py:124 |
| test_c1.py | `task_evaluator_form` truthy | SELF-ATTESTED | test_c1.py:125 |
| test_c1.py | hash field shape (64-hex, `*sha256`) | SELF-ATTESTED `[cheap]` | test_c1.py:129-137 |
| test_c1.py | selection rationale truthy | SELF-ATTESTED | test_c1.py:140-141 |
| test_c1.py | sha256 recomputed from in-tree file, matches claim | EXECUTION-BOUND | test_c1.py:149-161 |
| test_c2.py | `source_url` http-prefixed + dataset-name shape | SELF-ATTESTED | test_c2.py:214-223 |
| test_c2.py | frozen-rows sha256 recomputed vs claim | EXECUTION-BOUND | test_c2.py:228-250 |
| test_c2.py | frozen-rows ts predates candidate ts | EXECUTION-BOUND | test_c2.py:252-270 |
| test_c2.py | self-labeled leak marker/policy scan | SELF-ATTESTED | test_c2.py:280-302 |
| test_c2.py | `split` field contains "heldout" | SELF-ATTESTED | test_c2.py:281-285 |
| test_c2.py | non-self-labeled leak: gold values substring-matched into arm-C output | EXECUTION-BOUND | test_c2.py:331-376 |
| test_c3.py | `invalid_unequal_budget` code literal absence | SELF-ATTESTED | test_c3.py:214-217 |
| test_c3.py | zero-attempt-arm numeric threshold | SELF-ATTESTED | test_c3.py:219-225 |
| test_c3.py | waived-governor keyword scan | SELF-ATTESTED | test_c3.py:228-232 |
| test_c3.py | unequal-resource-path per-arm string equality | SELF-ATTESTED | test_c3.py:239-247 |
| test_c3.py | `equal_within_tolerance` flag trusted (underlying seconds never recomputed) | SELF-ATTESTED | test_c3.py:139-149 |
| test_c3.py | plain declarative field presence fallback | SELF-ATTESTED | test_c3.py:150 |
| test_c3.py | arm_contract A/B/C keys present | SELF-ATTESTED `[cheap]` | test_c3.py:279-280 |
| test_c4.py | `invalid_missing_before` code literal absence | SELF-ATTESTED | test_c4.py:198-199,222-230 |
| test_c4.py | per-row `a_score` presence | SELF-ATTESTED | test_c4.py:203-210 |
| test_c4.py | pre/post hash fields both present | SELF-ATTESTED `[cheap]` | test_c4.py:215,263-268 |
| test_c4.py | pre_hash != post_hash | SELF-ATTESTED | test_c4.py:218,270-273 |
| test_c4.py | shared scoring command string present | SELF-ATTESTED | test_c4.py:130-138,244-248 |
| test_c4.py | per-row command uniqueness (internal) | SELF-ATTESTED | test_c4.py:253-257 |
| test_c4.py | artifact reachability: path/sha256 pairs resolve+match in-tree | EXECUTION-BOUND | test_c4.py:281 (_lane14_common.py:122-160) |
| test_c4.py | `policy_update_trace` hashes cross-validated vs manifest claim | EXECUTION-BOUND | test_c4.py:288-307 |
| test_c4.py | sample-recompute b/c scores vs `best_reward_table` | EXECUTION-BOUND | test_c4.py:313 (_lane14_common.py:163-204) |
| test_c5.py | `per_task_rows` non-empty | SELF-ATTESTED `[cheap]` | test_c5.py:178,197-198 |
| test_c5.py | `invalid_no_rows` code literal absence | SELF-ATTESTED | test_c5.py:181-189 |
| test_c5.py | aggregate delta recomputed from raw per-row scores | EXECUTION-BOUND | test_c5.py:200-224,230-237 |
| test_c5.py | artifact reachability: manifest path/sha256 pairs | EXECUTION-BOUND | test_c5.py:246 (_lane14_common.py:122-160) |
| test_c5.py | sample-recompute of >=1 row's score | EXECUTION-BOUND | test_c5.py:257 (_lane14_common.py:163-204) |
| test_c6.py | per-arm `command` presence | SELF-ATTESTED | test_c6.py:111-119 |
| test_c6.py | code-file hash fields presence (never resolved/hashed anywhere in C6) | SELF-ATTESTED `[cheap]` | test_c6.py:122-126 |
| test_c6.py | data-hash fields presence | SELF-ATTESTED `[cheap]` | test_c6.py:128-135 |
| test_c6.py | env fields presence | SELF-ATTESTED | test_c6.py:138-146 |
| test_c6.py | `equal_budget` non-empty | SELF-ATTESTED | test_c6.py:149-152 |
| test_c6.py | artifact path fields presence (never resolved on disk) | SELF-ATTESTED `[cheap]` | test_c6.py:155-156 |
| test_c6.py | `reproducibility.rerun_command` truthy | SELF-ATTESTED | test_c6.py:159-160 |
| test_c6.py | task-specific negative flags/token trust | SELF-ATTESTED | test_c6.py:205-217 |
| test_c6.py | verdict string contains PASS | SELF-ATTESTED | test_c6.py:200-202 |
| test_c6.py | **BYPASS**: `RERUN_VERIFICATION_KEYS` bare-truthy short-circuit (returns before the structured path is ever reached) | SELF-ATTESTED — HIGH (live bypass, survives PR #741) | test_c6.py:176-183,339-343 |
| test_c6.py | fallback structured path: rerun receipts resolve+parse, hashes agree pairwise, cause git-resolvable | EXECUTION-BOUND | test_c6.py:294-333,344-350 |
| test_c7.py | invalid-token absence (score_only_loop / manually_selected_rerun / etc.) | SELF-ATTESTED | test_c7.py:86-96,193-201 |
| test_c7.py | `verdict == "PASS"` | SELF-ATTESTED | test_c7.py:210 |
| test_c7.py | `proves_load_bearing is True` | SELF-ATTESTED | test_c7.py:213-214 |
| test_c7.py | `held_out_slices` non-empty, entries >=1 | SELF-ATTESTED | test_c7.py:217-219 |
| test_c7.py | `degenerate_slice` contains 0 | SELF-ATTESTED | test_c7.py:224-225 |
| test_c7.py | `operator_constants_hash` matches LIVE `canonical_hash()` | EXECUTION-BOUND | test_c7.py:105-131,227-237 |
| test_c7.py | operator source contains "prospective" phrasing (live file read, shallow keyword match) | EXECUTION-BOUND | test_c7.py:134-151,249-251 |
| test_c7.py | degradation = real_trained − real_deleted pass-rate, recomputed, required >0 | EXECUTION-BOUND | test_c7.py:257-282 |

### Batch B — test_c8–test_c15, test_c_anat (61 predicates, 55 self-attested)

| probe | predicate | class | evidence |
|---|---|---|---|
| test_c8.py | `receipt_ref` resolves via isfile only | SELF-ATTESTED `[cheap]` | test_c8.py:85-94 |
| test_c8.py | provenance = command truthy + isfile ref | SELF-ATTESTED | test_c8.py:97-110 |
| test_c8.py | **BYPASS**: incumbent exact-string shortcut bypasses all other ablation checks | SELF-ATTESTED — HIGH | test_c8.py:131-134 |
| test_c8.py | ablation verdict suffix pattern | SELF-ATTESTED | test_c8.py:137-142 |
| test_c8.py | `deleted_contribution`/`surviving_delegate_pipeline` named (truthy) | SELF-ATTESTED | test_c8.py:145-150 |
| test_c8.py | deletion/delegate provenance both "ok" (inherits weak isfile) | SELF-ATTESTED | test_c8.py:152-156 |
| test_c8.py | `verdict.endswith("_PASS")` | SELF-ATTESTED | test_c8.py:237 |
| test_c8.py | `len(blockers)==0` | SELF-ATTESTED | test_c8.py:238 |
| test_c8.py | `field_level_claim_proven is True` | SELF-ATTESTED | test_c8.py:239 |
| test_c8.py | required goal fields bool()-truthy (4 fields) | SELF-ATTESTED | test_c8.py:247-251 |
| test_c9.py | acceptance schema/scope self-report | SELF-ATTESTED | test_c9.py:94-99 |
| test_c9.py | `code_vs_docs` metric shape (keys only, never recomputed) | SELF-ATTESTED `[cheap]` | test_c9.py:118-134 |
| test_c9.py | docs-only/scaffold-violation string/verdict match | SELF-ATTESTED | test_c9.py:206-213 |
| test_c9.py | substrate-growth = verdict membership + self-reported code-line count | SELF-ATTESTED | test_c9.py:229-235 |
| test_c10.py | trigger "evaluable" shape regex (text only, never resolved) | SELF-ATTESTED | test_c10.py:184-187 |
| test_c10.py | `has_receipt` = substring "receipts/"/".json" in row text (weaker than isfile) | SELF-ATTESTED | test_c10.py:189 |
| test_c10.py | disposition token non-empty after colon | SELF-ATTESTED | test_c10.py:203-207 |
| test_c10.py | zero-offending-rows over ledger's own status column | SELF-ATTESTED | test_c10.py:150-172 |
| test_c12.py | ablation `degrades_truthy` flag (post-hardening, still bare boolean) | SELF-ATTESTED | test_c12.py:178-190 |
| test_c12.py | decision entries structural presence (>=3 of 6 fields + mode string) | SELF-ATTESTED `[cheap]` | test_c12.py:206-246 |
| test_c12.py | selector presence via isfile (superseded by sha-pin below) | SELF-ATTESTED `[cheap]` | test_c12.py:400-401,477-481 |
| test_c12.py | selector sha-pinned to git-committed content | EXECUTION-BOUND | test_c12.py:336-392 |
| test_c12.py | every decision's mode independently recomputed via live `select_mode()` | EXECUTION-BOUND | test_c12.py:276-307 |
| test_c12.py | `mode_agreement_rate` recomputed from raw divergence entries | EXECUTION-BOUND | test_c12.py:310-333,536-552 |
| test_c12.py | final degrade-flag confirmation before GREEN (still bare boolean trust) | SELF-ATTESTED | test_c12.py:493-504 |
| test_c13.py | `all_required_mechanisms_covered is True` | SELF-ATTESTED | test_c13.py:174-176 |
| test_c13.py | `codex_goal_mode_mechanisms` non-empty | SELF-ATTESTED `[cheap]` | test_c13.py:177-179 |
| test_c13.py | per-mechanism verb/ablation-requirement text present | SELF-ATTESTED | test_c13.py:188-201 |
| test_c13.py | probe controller string equality | SELF-ATTESTED | test_c13.py:230-234 |
| test_c13.py | parasite-controller substring absence | SELF-ATTESTED | test_c13.py:235-237 |
| test_c13.py | `codex_controller_required is False` | SELF-ATTESTED | test_c13.py:238-241 |
| test_c13.py | `organ.minimum_loop_covered is True` | SELF-ATTESTED | test_c13.py:244-246 |
| test_c13.py | `organ.minimum_loop` == canonical list | SELF-ATTESTED | test_c13.py:247-255 |
| test_c13.py | `deletion_ablation.degrades_decision is True` | SELF-ATTESTED | test_c13.py:258-261 |
| test_c13.py | `deleted_selected_next_action.id` string equality | SELF-ATTESTED | test_c13.py:262-266 |
| test_c13.py | standalone deleted-organ corroboration receipt | SELF-ATTESTED | test_c13.py:280-292 |
| test_c14.py | conflation-guard verdict not BLOCKED | SELF-ATTESTED | test_c14.py:223-231 |
| test_c14.py | resident receipt status/verdict/error-codes self-report (4 checks) | SELF-ATTESTED | test_c14.py:233-250 |
| test_c14.py | full-parity harness verdict self-report | SELF-ATTESTED | test_c14.py:268-282 |
| test_c14.py | real-avir observation verdict + 4 observed_* booleans | SELF-ATTESTED | test_c14.py:316-328 |
| test_c14.py | `clean_room_harness_identity` structural presence | SELF-ATTESTED `[cheap]` | test_c14.py:339-354 |
| test_c14.py | bound observation sha256 verified against actual latest observation file | EXECUTION-BOUND | test_c14.py:355-363 |
| test_c15.py | baseline/model identity non-empty strings | SELF-ATTESTED | test_c15.py:266-271 |
| test_c15.py | pre/post param hashes present+distinct (never recomputed from weight files) | SELF-ATTESTED `[cheap]` | test_c15.py:275-288 |
| test_c15.py | trainable param counts positive (never cross-checked vs real model) | SELF-ATTESTED | test_c15.py:291-294 |
| test_c15.py | precision scheme carries "bitnet" key | SELF-ATTESTED | test_c15.py:297-299 |
| test_c15.py | `bitnet_effective_weight_bits == 1.58` | SELF-ATTESTED | test_c15.py:302-304 |
| test_c15.py | quality/throughput/memory measurement blocks are dict-shaped | SELF-ATTESTED `[cheap]` | test_c15.py:307-312 |
| test_c15.py | transfer/deletion-revert lists non-empty | SELF-ATTESTED | test_c15.py:313-318 |
| test_c15.py | training command non-empty | SELF-ATTESTED | test_c15.py:320-323 |
| test_c15.py | bitnet receipt's own claim of C14 gate status | SELF-ATTESTED | test_c15.py:344-346 |
| test_c15.py | C14 gate path resolve+isfile (feeds hash check) | SELF-ATTESTED `[cheap]` | test_c15.py:347-362 |
| test_c15.py | C14 gate file sha256 recomputed, matches recorded gate sha | EXECUTION-BOUND | test_c15.py:364-372 |
| test_c15.py | neural-vs-symbolic status re-derived from the actual cited C14 gate file content | EXECUTION-BOUND | test_c15.py:373-400 |
| test_c_anat.py | anatomy doc presence via filename-prefix glob (zero-byte stub satisfies) | SELF-ATTESTED `[cheap]` | test_c_anat.py:114-130 |
| test_c_anat.py | "anatomy set" keyword substring in receipt | SELF-ATTESTED | test_c_anat.py:148-157 |
| test_c_anat.py | "consistent with receipts" keyword substring | SELF-ATTESTED | test_c_anat.py:158-159 |
| test_c_anat.py | "H4 addressed" keyword substring | SELF-ATTESTED | test_c_anat.py:160-162 |

### Batch C — test_c_auto–test_c_grow (65 predicates, 42 self-attested)

| probe | predicate | class | evidence |
|---|---|---|---|
| test_c_auto.py | `state.json` schema-completeness (key names only) | SELF-ATTESTED `[cheap]` | test_c_auto.py:82-85 |
| test_c_auto.py | contract path resolves (isfile only) | SELF-ATTESTED `[cheap]` | test_c_auto.py:88-91 |
| test_c_auto.py | `safety_floor` names three items (substring) | SELF-ATTESTED | test_c_auto.py:93-96 |
| test_c_auto.py | vacuous-GREEN "no rung claimed" shortcut | SELF-ATTESTED | test_c_auto.py:99,102-103 |
| test_c_auto.py | window count >=5 (self-declared list length) | SELF-ATTESTED `[cheap]` | test_c_auto.py:113-116 |
| test_c_auto.py | window receipt resolves+parses | EXECUTION-BOUND | test_c_auto.py:120-132 |
| test_c_auto.py | window timestamps strictly increasing (cross-file) | EXECUTION-BOUND | test_c_auto.py:134-141 |
| test_c_auto.py | per-window provenance field, real parsed content | EXECUTION-BOUND | test_c_auto.py:144-155 |
| test_c_auto.py | claim-receipt existence for claimed rung (filename match only) | SELF-ATTESTED `[cheap]` | test_c_auto.py:157-163 |
| test_c_auto.py | `current_rung` == highest claimed rung (same-doc fields) | SELF-ATTESTED | test_c_auto.py:165-173 |
| test_c_auto.py | reversion-log incident receipt resolves (isfile only) | SELF-ATTESTED `[cheap]` | test_c_auto.py:176-182 |
| test_c_auto.py | stale-claim-above-reversion-target ts cross-check | EXECUTION-BOUND | test_c_auto.py:187-217 |
| test_c_base.py | VOID-receipt supersession via real sha256 + declared supersedes cross-check | EXECUTION-BOUND | test_c_base.py:175-204 |
| test_c_base.py | `OWNED_PRETRAIN_MARKERS` keyword match | SELF-ATTESTED | test_c_base.py:364 |
| test_c_base.py | dead-lineage hash negative exclusion (text) | SELF-ATTESTED | test_c_base.py:371-372 |
| test_c_base.py | `BORROWED_MARKERS` negative exclusion | SELF-ATTESTED | test_c_base.py:374-375 |
| test_c_base.py | manifest weight-hash vs actual `model.pt` bytes | EXECUTION-BOUND | test_c_base.py:378-397 |
| test_c_base.py | candidate self-declared pass/verdict (hardened vs explicit False only) | SELF-ATTESTED | test_c_base.py:240-262,418-419 |
| test_c_base.py | GROW marker keyword match, boolean-gated by same-doc key | SELF-ATTESTED | test_c_base.py:280-298,427-430 |
| test_c_base.py | grow-operator evidence resolves to a self-reported PASS verdict | SELF-ATTESTED `[cheap]` | test_c_base.py:301-325,433-449 |
| test_c_base.py | degenerate loss-trace structural check on real numeric array | EXECUTION-BOUND | test_c_base.py:207-225,451-454 |
| test_c_base.py | invalid-token negative text scan | SELF-ATTESTED | test_c_base.py:461-468 |
| test_c_custody.py | `git ls-files` ground truth | EXECUTION-BOUND | test_c_custody.py:114-128 |
| test_c_custody.py | untracked-file detection vs real git tracked-set | EXECUTION-BOUND | test_c_custody.py:494-517 |
| test_c_custody.py | `__allowlist_untracked` self-exemption | SELF-ATTESTED | test_c_custody.py:404-409,500-506 |
| test_c_custody.py | JSON parseability of every receipt (real bytes) | EXECUTION-BOUND | test_c_custody.py:131-143,520-523 |
| test_c_custody.py | cited receipts/ path existence (real filesystem) | EXECUTION-BOUND | test_c_custody.py:544-548 |
| test_c_custody.py | redacted-edition twin resolution+tracked-set check | EXECUTION-BOUND | test_c_custody.py:349-374,556-559 |
| test_c_custody.py | hardcoded literal-path exemption table | SELF-ATTESTED | test_c_custody.py:277-287,570-572 |
| test_c_custody.py | `documented_absent` self-disclosure honored | SELF-ATTESTED | test_c_custody.py:173-186,576-578 |
| test_c_custody.py | unique-basename relocation vs real tracked set | EXECUTION-BOUND | test_c_custody.py:338-346,581-584 |
| test_c_custody.py | spend-annex historical sha256 (file gone, never recomputed) | SELF-ATTESTED `[expensive]` | test_c_custody.py:377-401,589-596 |
| test_c_custody.py | pending-landing age-window via real `git log` | EXECUTION-BOUND | test_c_custody.py:424-439,508-511 |
| test_c_disc.py | checker-name key presence | SELF-ATTESTED `[cheap]` | test_c_disc.py:76-77 |
| test_c_disc.py | `executed` flag reflects real subprocess re-execution | EXECUTION-BOUND | test_c_disc.py:82-84 |
| test_c_disc.py | verdict==PASS, dual-source exit-code/printed-line coherence | EXECUTION-BOUND | test_c_disc.py:86-88 |
| test_c_e2b.py | `legs.ember_work`/`legs.founder_likeness` presence | SELF-ATTESTED `[cheap]` | test_c_e2b.py:70-74 |
| test_c_e2b.py | score fields numeric-typed only | SELF-ATTESTED | test_c_e2b.py:77-80 |
| test_c_e2b.py | `owned_core_score > e2b_score` (same-doc fields) | SELF-ATTESTED | test_c_e2b.py:81-83 |
| test_c_e2b.py | matched-budget equality (same-doc fields) | SELF-ATTESTED | test_c_e2b.py:85-91 |
| test_c_e2b.py | owned-core-identity booleans | SELF-ATTESTED | test_c_e2b.py:93-100 |
| test_c_e2b.py | `protocol_frozen_ref` resolves in-tree | EXECUTION-BOUND | test_c_e2b.py:102-107 |
| test_c_e2b.py | freeze-ts strictly before receipt ts (real filename ts) | EXECUTION-BOUND | test_c_e2b.py:108-113 |
| test_c_e2b.py | synthetic-fixture flag / invalid-token scan | SELF-ATTESTED | test_c_e2b.py:141-148 |
| test_c_enf.py | expected checker names present (key existence) | SELF-ATTESTED `[cheap]` | test_c_enf.py:81-85 |
| test_c_enf.py | per-checker `executed` via real subprocess re-execution | EXECUTION-BOUND | test_c_enf.py:90-91 |
| test_c_enf.py | per-checker verdict PASS/FAIL, exit-code/printed-line coherence | EXECUTION-BOUND | test_c_enf.py:92-93 |
| test_c_enf.py | `check_energy_law_theory` selftest verdict PASS | EXECUTION-BOUND | test_c_enf.py:49,94-95 |
| test_c_enf.py | publication-gate coherence-only (either verdict acceptable) | EXECUTION-BOUND | test_c_enf.py:52,88-95 |
| test_c_fed.py | design-mechanism keyword presence | SELF-ATTESTED | test_c_fed.py:222 |
| test_c_fed.py | avenues keyword presence | SELF-ATTESTED | test_c_fed.py:224 |
| test_c_fed.py | egress-manifest phrase presence | SELF-ATTESTED | test_c_fed.py:226 |
| test_c_fed.py | transfer-gate/zero-outbound phrase presence | SELF-ATTESTED | test_c_fed.py:227-235 |
| test_c_fed.py | invalid-token negative text scan | SELF-ATTESTED | test_c_fed.py:200-209 |
| test_c_fed.py | **entire probe is text/regex-only** — zero recompute, zero hash, zero cross-file check anywhere | SELF-ATTESTED `[expensive]` | test_c_fed.py:60-83,220-249 |
| test_c_grow.py | `grow_method` field/text-keyword presence | SELF-ATTESTED | test_c_grow.py:88-91,459-463 |
| test_c_grow.py | param-count before/after comparison (same-doc, or text fallback) | SELF-ATTESTED | test_c_grow.py:93-101,465-470 |
| test_c_grow.py | `loss_continuity` boolean/text fallback | SELF-ATTESTED | test_c_grow.py:105-109,472-489 |
| test_c_grow.py | `flop_saving` keyword pre-filter | SELF-ATTESTED | test_c_grow.py:112-116,498 |
| test_c_grow.py | unmeasured-estimate negative guard (only catches honest disclosure) | SELF-ATTESTED | test_c_grow.py:178-219,424-434 |
| test_c_grow.py | **BYPASS**: `measured_on_train_daemon==True` outright-pass shortcut | SELF-ATTESTED — HIGH | test_c_grow.py:256-257 |
| test_c_grow.py | per-stage checkpoint sha256 "verification" is a hex-shape regex only, never opens the file | SELF-ATTESTED `[cheap]` | test_c_grow.py:222-223,288-292 |
| test_c_grow.py | grow-path/from-scratch FLOP-total recompute vs claimed totals | EXECUTION-BOUND | test_c_grow.py:306-347 |
| test_c_grow.py | ticket-based exclusion (self-declared string) | SELF-ATTESTED | test_c_grow.py:388-397 |
| test_c_grow.py | smoke-marker exclusion (self-declared fields/filename) | SELF-ATTESTED | test_c_grow.py:404-417 |
| test_c_grow.py | invalid-token negative text scan | SELF-ATTESTED | test_c_grow.py:376-379 |

### Batch D — test_c_ind, c_invariant, c_ladm, c_legib, c_manifest, c_mile, c_neg1, c_obs (44 predicates, 30 self-attested)

| probe | predicate | class | evidence |
|---|---|---|---|
| test_c_ind.py | IND provenance = path substring "ind" + fixed key-name presence | SELF-ATTESTED | test_c_ind.py:134-187 |
| test_c_ind.py | IND-1 interact/rendered-frame/matrix-complete self-report | SELF-ATTESTED | test_c_ind.py:200-229 |
| test_c_ind.py | cross-class `doc_pointer` real filesystem resolve | EXECUTION-BOUND | test_c_ind.py:378-384 |
| test_c_ind.py | IND-2 OBSERVE via real `test_c_obs.py` subprocess | EXECUTION-BOUND | test_c_ind.py:234-253 |
| test_c_ind.py | IND-3 teardown survivors/orphaned-gpu self-report (probe never queries OS itself) | SELF-ATTESTED | test_c_ind.py:262-276 |
| test_c_ind.py | IND-3 leg-name string match | SELF-ATTESTED | test_c_ind.py:277-284 |
| test_c_ind.py | IND-4 customize leg key-presence (never diffs real config) | SELF-ATTESTED `[cheap]` | test_c_ind.py:293-294 |
| test_c_ind.py | IND-4 experiment-reproduction `within_tolerance` self-report (refs never resolved) | SELF-ATTESTED `[expensive]` | test_c_ind.py:295-297 |
| test_c_ind.py | IND-5 comprehend_v2 leg-shape presence | SELF-ATTESTED `[cheap]` | test_c_ind.py:352-359 |
| test_c_ind.py | IND-5 dead-links/per-leg-passed self-report, never re-derived | SELF-ATTESTED | test_c_ind.py:360-366 |
| test_c_invariant.py | `INVARIANT.md` sha256 vs pinned constant | EXECUTION-BOUND | test_c_invariant.py:108-122 |
| test_c_invariant.py | `GOAL.md` pin presence (two independent substring checks, never bound to each other) | SELF-ATTESTED | test_c_invariant.py:125-144 |
| test_c_invariant.py | post-genesis receipt stamp scan over real glob population | EXECUTION-BOUND | test_c_invariant.py:357-443 |
| test_c_invariant.py | errata-annex coverage exemption via hand-authored jsonl row | SELF-ATTESTED | test_c_invariant.py:170-218,410-413 |
| test_c_invariant.py | supersession `new_path` existence+stamp on real resolved file | EXECUTION-BOUND | test_c_invariant.py:294-309 |
| test_c_invariant.py | supersession leg/class identity match (self-declared) | SELF-ATTESTED | test_c_invariant.py:310-317 |
| test_c_invariant.py | errata row schema validation (presence/type only) | SELF-ATTESTED `[cheap]` | test_c_invariant.py:494-538 |
| test_c_invariant.py | errata file append-only via real `git log -p` diff scan | EXECUTION-BOUND | test_c_invariant.py:446-484 |
| test_c_ladm.py | control-pool row `verified` self-report | SELF-ATTESTED | test_c_ladm.py:229-230 |
| test_c_ladm.py | episode+control-pool duplicate-key uniqueness (real set recompute) | EXECUTION-BOUND | test_c_ladm.py:226-228,241-243 |
| test_c_ladm.py | episode `verified` field type-only (never a real verifier run) | SELF-ATTESTED | test_c_ladm.py:246-247 |
| test_c_ladm.py | episode receipt pointer isfile only | SELF-ATTESTED `[cheap]` | test_c_ladm.py:150-155,258-261 |
| test_c_ladm.py | matched-control task-membership cross-check vs real control-pool set | EXECUTION-BOUND | test_c_ladm.py:267-269 |
| test_c_ladm.py | sampler/origin internal consistency | EXECUTION-BOUND | test_c_ladm.py:272-274 |
| test_c_ladm.py | control-pool byte-unchanged dual sha256 + live subprocess assertion | EXECUTION-BOUND | test_c_ladm.py:158-189,204-206,279-284 |
| test_c_ladm.py | verifier-instrument externality (isfile+extension only, content never parsed) | SELF-ATTESTED `[cheap]` | test_c_ladm.py:302-311 |
| test_c_legib.py | entry-map vs real `os.listdir` cross-check | EXECUTION-BOUND | test_c_legib.py:150-181 |
| test_c_legib.py | cold-read-reprobe verdict self-report (never re-run) | SELF-ATTESTED | test_c_legib.py:184-218 |
| test_c_legib.py | citation-gate real subprocess exit code | EXECUTION-BOUND | test_c_legib.py:221-249 |
| test_c_manifest.py | manifest row field-completeness (receipt cell non-emptiness only, never resolved) | SELF-ATTESTED `[cheap]` | test_c_manifest.py:146-164 |
| test_c_manifest.py | legacy-id rename table self-trust | SELF-ATTESTED | test_c_manifest.py:88-110 |
| test_c_manifest.py | every §4 condition manifested, denominator re-derived from real GOAL.md bullets | EXECUTION-BOUND | test_c_manifest.py:192-221,258-295 |
| test_c_mile.py | **entire probe** is a pass-through of an out-of-scope helper's self-reported `executed`/`verdict` — zero independent recompute IN THIS FILE | SELF-ATTESTED `[expensive]` | test_c_mile.py:73-92 |
| test_c_neg1.py | spend/paid-flag values self-reported, no billing cross-check | SELF-ATTESTED `[expensive]` | test_c_neg1.py:296-310 |
| test_c_neg1.py | verdict PASS-class text linkage | SELF-ATTESTED | test_c_neg1.py:150-156,313-314,332-342 |
| test_c_neg1.py | invalid-token text scan (trivially evaded by omission) | SELF-ATTESTED | test_c_neg1.py:97-111,288-293 |
| test_c_neg1.py | annex-cited receipts exist (isfile only at this step) | SELF-ATTESTED `[cheap]` | test_c_neg1.py:231-244,358-365 |
| test_c_neg1.py | annex `paid_surface_violation`/`evidence_class` flag trust | SELF-ATTESTED | test_c_neg1.py:367-372 |
| test_c_neg1.py | annex sha256 anti-staleness recompute | EXECUTION-BOUND | test_c_neg1.py:396-399 |
| test_c_neg1.py | annex evidence_class coverage accepted even after sha match (never re-derived from content) | SELF-ATTESTED | test_c_neg1.py:381-396 |
| test_c_obs.py | EmberWorldState binding adapter (pure keyword/prose scan) | SELF-ATTESTED | test_c_obs.py:167-185 |
| test_c_obs.py | click-to-evidence surface (phrase match) | SELF-ATTESTED | test_c_obs.py:188-189 |
| test_c_obs.py | confirm-only membrane (keyword match) | SELF-ATTESTED | test_c_obs.py:194-198 |
| test_c_obs.py | user-runnable proof-pack (keyword match; CHK requires commands actually run, never executed by this probe) | SELF-ATTESTED `[expensive]` | test_c_obs.py:200-204 |

### Batch E — test_c_organism, c_port, c_proc, c_scale, c_tally, surface2 (61 predicates, 53 self-attested)

| probe | predicate | class | evidence |
|---|---|---|---|
| test_c_organism.py | `SEED_GRAPH_MARKERS` keyword scan | SELF-ATTESTED | test_c_organism.py:183-187 |
| test_c_organism.py | per-machinery keyword co-occurrence | SELF-ATTESTED | test_c_organism.py:189-193 |
| test_c_organism.py | deletion-marker keyword scan | SELF-ATTESTED | test_c_organism.py:195-196 |
| test_c_organism.py | `machinery_callable is True` | SELF-ATTESTED | test_c_organism.py:148-150 |
| test_c_organism.py | `interface_callable` non-empty string (never actually called) | SELF-ATTESTED `[expensive]` | test_c_organism.py:151-153 |
| test_c_organism.py | `deleted_error_class` non-empty string | SELF-ATTESTED | test_c_organism.py:157-159 |
| test_c_organism.py | active/deleted degradation pair (same-doc fields, never independently logged) | SELF-ATTESTED | test_c_organism.py:121-135,160-161 |
| test_c_organism.py | invalid-token absence | SELF-ATTESTED | test_c_organism.py:211-216 |
| test_c_port.py | forward_pass/no_crash keyword co-occurrence | SELF-ATTESTED | test_c_port.py:142-148 |
| test_c_port.py | non-4090 marker keyword co-occurrence | SELF-ATTESTED | test_c_port.py:149-156 |
| test_c_port.py | invalid-token absence | SELF-ATTESTED | test_c_port.py:323-326 |
| test_c_port.py | `is_4090_only` regex negative | SELF-ATTESTED | test_c_port.py:170-185,329-331 |
| test_c_port.py | absolute-tps-gate regex negative | SELF-ATTESTED | test_c_port.py:188-199,334-337 |
| test_c_port.py | fp8-runtime-error-without-fallback regex negative | SELF-ATTESTED | test_c_port.py:340-343 |
| test_c_port.py | `forward_pass.no_crash` self-report | SELF-ATTESTED | test_c_port.py:352-361 |
| test_c_port.py | governor block VRAM-total key presence (never live-queried) | SELF-ATTESTED `[expensive]` | test_c_port.py:363-372 |
| test_c_port.py | `EMBER_VRAM_FRACTION` env-var reference text check (never confirms env was read) | SELF-ATTESTED | test_c_port.py:373-375 |
| test_c_port.py | device-identity non-4090 string check | SELF-ATTESTED | test_c_port.py:377-387 |
| test_c_port.py | device-relative roofline basis declared (never recomputed) | SELF-ATTESTED `[expensive]` | test_c_port.py:389-399 |
| test_c_port.py | fp8 sm>=89 gating text presence | SELF-ATTESTED | test_c_port.py:401-403 |
| test_c_port.py | fp8 bf16-fallback text presence | SELF-ATTESTED | test_c_port.py:404-405 |
| test_c_port.py | governor tighten-only phrase check | SELF-ATTESTED | test_c_port.py:407-412 |
| test_c_port.py | live subprocess re-run of generator (`--verify-only`), freshly-computed precision cross-checked | EXECUTION-BOUND | test_c_port.py:202-282,414-418 |
| test_c_proc.py | synthetic-control-fixture self-rejection | SELF-ATTESTED | test_c_proc.py:138-139 |
| test_c_proc.py | invalid-token absence | SELF-ATTESTED | test_c_proc.py:140-143 |
| test_c_proc.py | issue-URL format regex (deliberately offline, never resolved) | SELF-ATTESTED `[expensive]` | test_c_proc.py:145-149 |
| test_c_proc.py | open-PR schema type/enum check (never cross-checked vs real GitHub state) | SELF-ATTESTED `[expensive]` | test_c_proc.py:151-160 |
| test_c_proc.py | `pending_h > GRACE_HOURS` on self-reported field | SELF-ATTESTED | test_c_proc.py:161-164 |
| test_c_proc.py | publication-state schema (sha never git-verified against remote) | SELF-ATTESTED `[expensive]` | test_c_proc.py:176-185 |
| test_c_proc.py | justification receipt isfile+mtime-age only, content never parsed | SELF-ATTESTED `[cheap]` | test_c_proc.py:188-201 |
| test_c_proc.py | `covered_commits` non-empty dict (pre-git-check) | SELF-ATTESTED `[cheap]` | test_c_proc.py:203-205 |
| test_c_proc.py | covered commit sha exists via real `git cat-file -e` | EXECUTION-BOUND | test_c_proc.py:210-216 |
| test_c_proc.py | work-vs-coverage lag recomputed from real git commit times | EXECUTION-BOUND | test_c_proc.py:107-111,207-228 |
| test_c_proc.py | delegation built_by/verified_by non-empty strings | SELF-ATTESTED | test_c_proc.py:239-250 |
| test_c_scale.py | `operating_capability_point > 3e9` on self-reported field | SELF-ATTESTED | test_c_scale.py:92-94 |
| test_c_scale.py | W1 `token_bill_collapse_ratio` re-derivation with tolerance | EXECUTION-BOUND | test_c_scale.py:75-86,99-101 |
| test_c_scale.py | `growth_lineage_from_cbase_seed` truthy | SELF-ATTESTED | test_c_scale.py:104-105 |
| test_c_scale.py | `no_borrowed_weights_load_bearing is True` | SELF-ATTESTED | test_c_scale.py:106-107 |
| test_c_scale.py | `native_finetune_mechanism_id` non-empty | SELF-ATTESTED | test_c_scale.py:112-114 |
| test_c_scale.py | `per_update_cost_at_scale > 0` (never recomputed) | SELF-ATTESTED | test_c_scale.py:115-116 |
| test_c_scale.py | `free_cognitive_mode_transition_receipt` non-empty | SELF-ATTESTED | test_c_scale.py:117-119 |
| test_c_scale.py | mode-receipt resolves in-tree (isfile only, no parse) | SELF-ATTESTED `[cheap]` | test_c_scale.py:120-122 |
| test_c_scale.py | `no_borrowed_base is True` | SELF-ATTESTED | test_c_scale.py:123-124 |
| test_c_scale.py | `capability_per_compute_ratio` re-derivation with tolerance | EXECUTION-BOUND | test_c_scale.py:75-86,126-130 |
| test_c_scale.py | `contribution_deletion_collapses_excess is True` (C8 run never re-executed) | SELF-ATTESTED | test_c_scale.py:132-134 |
| test_c_scale.py | `active_working_set_bytes <= device_working_set_floor_bytes` (both self-reported) | SELF-ATTESTED | test_c_scale.py:136-140 |
| test_c_tally.py | board-filename timestamp format validation only | SELF-ATTESTED `[cheap]` | test_c_tally.py:89-99,108-109 |
| test_c_tally.py | `board.rows` non-empty | SELF-ATTESTED `[cheap]` | test_c_tally.py:135-137 |
| test_c_tally.py | `state_rows` non-empty | SELF-ATTESTED `[cheap]` | test_c_tally.py:144-146 |
| test_c_tally.py | GREEN-pct recomputed from raw row.status recount | EXECUTION-BOUND | test_c_tally.py:148-151,173-177 |
| test_c_tally.py | audit-incident count recomputed from raw row scan | EXECUTION-BOUND | test_c_tally.py:153-154,179-183 |
| test_c_tally.py | tally-*.json freshness (explicitly disclosure-only, never load-bearing) | SELF-ATTESTED | test_c_tally.py:156-170 |
| test_surface2.py | synthetic-fixture/event self-rejection (2 checks) | SELF-ATTESTED | test_surface2.py:349-355 |
| test_surface2.py | non-live-provenance marker string rejection | SELF-ATTESTED | test_surface2.py:367-371 |
| test_surface2.py | `live_process_touched is False` rejection | SELF-ATTESTED | test_surface2.py:372-375 |
| test_surface2.py | `telemetry_status_bar_rendered is False` hard-fail | SELF-ATTESTED | test_surface2.py:385-391 |
| test_surface2.py | render-evidence OR events-rendered>0 (no proof anything drawn to screen) | SELF-ATTESTED `[expensive]` | test_surface2.py:392-402 |
| test_surface2.py | receipt-ts staleness vs real git HEAD commit time | EXECUTION-BOUND | test_surface2.py:195-211,404-418 |
| test_surface2.py | steer/kill verb schema-check on sibling files (verb itself still author-controlled, no PID/log binding) | SELF-ATTESTED `[expensive]` | test_surface2.py:262-312,420-426 |
| test_surface2.py | `metrics_delta` > 0 (never cross-referenced vs real output log) | SELF-ATTESTED `[expensive]` | test_surface2.py:315-323,429-433 |

## Standing debt summary

- **322 predicates classified across 40 probes; 245 (76%) are SELF-ATTESTED.**
- **3 confirmed single-field BYPASSES** (an adversary needs to fabricate exactly one value):
  `test_c6.py:339-343`, `test_c8.py:131-134`, `test_c_grow.py:256-257`. Recommend these three as
  the highest-priority follow-up lane — `test_c6.py`'s is notable because PR #741 hardened C6's
  structured `deterministic_mismatch` path but left the pre-existing bare-key shortcut reachable
  first.
- **Fully/near-fully self-attested probes** (little to no execution-binding anywhere):
  `test_c_fed.py` (text/regex-only throughout), `test_c_mile.py` (pure pass-through of an
  out-of-scope helper's self-report), `test_c_obs.py` (entirely keyword/prose scans, despite its
  own CHK requiring commands to actually run).
- **`[cheap]`-tagged rows** are candidates for a fast follow-up PR using the already-proven
  `resolve_in_tree` + `sha256_file` / `check_path_sha_pairs` pattern from `_lane14_common.py`
  (used by `test_c1.py`, `test_c4.py`, `test_c5.py`).
- **`[expensive]`-tagged rows** need a new binding mechanism per-probe (live process/API query,
  screenshot-hash, GitHub API cross-check, real subprocess execution of the claimed proof-pack) and
  should be filed as individual follow-up issues rather than bundled.

No probe logic was modified in this PR — this document and its appendix are the sweep's FIND half;
CURE is separate follow-up work per issue #740's scope.
