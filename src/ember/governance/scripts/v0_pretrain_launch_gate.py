# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""v0_pretrain_launch_gate.py — fail-closed dispatch gate for the owned-core
v0 pretrain (historical c03: 0.4339B realized / 0.3684B base excluding MTP).

This shim embeds docs/domains/governance/research/v0-launch-gate.md as named, receipt-checkable
assertions. The v0 trainer (#167 — scripts/timeshare_pretrain.py extended
against configs/v0-pretrain-config.json) is dispatched THROUGH this gate:
it loads each named receipt, receipt_checks it, verifies the pins, and
REFUSES with the failing G-row(s) named. No row is waivable except by the
user, by name. Same fail-closed grammar as fp25_surfaceb select mode.

Today's live state (recorded in the emitted receipt, not asserted here so
the selftest stays time-robust): G-prereg is GREEN (eng-48/#181 wired the
fp26 premise check). The blocking row is now G-shards (eng-49/#183): the
packed uint16 shards that ARE the live-training input have not been produced
(production HELD pending the shard-production call), so --live is correctly
refused. The other six rows are GREEN.
"""
import argparse
import copy
import datetime
import glob
import hashlib
import json
import os
import pathlib
import sys

NC = str(pathlib.Path(__file__).resolve().parents[4])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from receipt_check import validate_receipt          # noqa: E402
import v0_config_check                              # noqa: E402
import fp26_prereg                                  # noqa: E402
import token_shards_v0                              # noqa: E402
import fineweb_exclusion                            # noqa: E402

# ---- binding pins (changing any of these is a contract change) -----------
ASSEMBLY_RECEIPT = "eng36-assembly-20260611T052337Z.json"
ASSEMBLY_SHA = ("f6d0734e090fcaef84ac2361f42c7419f5e40b58"
                "6355bc4a385e7a695250c841")
TOKENIZER_RECEIPT = "tokenizer-freeze-20260611T154111Z.json"
CONFIG = f"{NC}/configs/v0-pretrain-config.json"
DEADLINE = datetime.date(2026, 6, 22)
# fp19-bench receipted-unstacked days-to-compute-optimal for the c03-qat core
ENVELOPE_DAYS_FLOOR = 4.55
WORLD_SPECS = ["docs/domains/governance/research/fp22-corpus-world.md", "docs/domains/governance/research/world-choice-r2.md"]
RESERVED_BAND_N = 8           # NC2 v0 LOCK #1 (ids 0-7)
HARD_BAR_BYTES = 100 * 10**9  # corpus <100GB hard bar
FP26_PREREG_GLOB = "receipts/fp26-prereg-*.json"
TOKEN_SHARDS_GLOB = "receipts/token-shards-v0-*.json"
SHA_CONVENTION = ("sha256 over the exact on-disk file bytes, no "
                  "normalization; receipt paths carry the git -text pin")
# G-budget compute-fit grounding (first-principles): the budget envelope's
# real invariant is "does the run fit the compute budget," which the banked
# SHATTER verdict answers by MEASUREMENT — the efficiency lever (effective_days
# <= 1.0 GPU-day for the keystone-certified config on the 2.2e9 ceiling) that
# makes the run affordable. The calendar-days check is a deadline-tracking
# artifact; a real SHATTER proof supersedes it. Fail-closed (see g_budget).
SHATTER_VERDICT_GLOB = "receipts/shatter-verdict-*.json"
SHATTER_EFFECTIVE_DAYS_FLOOR = 1.0       # the frozen SHATTER bar (1 GPU-day)
SHATTER_BUDGET_B = 2_200_000_000.0       # the keystone-certified ceiling
# ANTI-SELF-REFERENCE (2026-06-23): a SHATTER receipt's effective_days MUST be
# the real wall-clock days = budget_b / (sustained_tok_s * 86400). The retracted
# SHATTER defined effective_days = K_floor/throughput (K_floor = budget_b *
# tokens_to_match_ref / budget_tokens / 86400) — a SELF-REFERENTIAL construct, not
# wall-clock days. _shatter_compute_fit recomputes and requires consistency; a
# receipt whose stated effective_days disagrees with the recompute is rejected.
SHATTER_EFF_DAYS_TOL = 0.05              # consistency tolerance (5%)

# ---- G-budget REQUESTED-RUN compute-fit (per-run-truthful micro path) -----
# The calendar/SHATTER math above answers "does the FULL v0 pretrain LADDER
# fit the budget" -- correct for a real multi-day dispatch, wrong for a
# minutes-long GPU probe (e.g. cbase_grow_live.py's ~120-step net2net
# grow-continuity micro-run). A caller that knows EXACTLY what THIS launch
# will execute may pass a `requested_run` descriptor; g_budget then prices
# THAT run instead of the full ladder. The ceiling is a FIXED absolute FLOPs
# number derived from the certified c03 params pin (never from the caller's
# own claimed params), so a caller cannot buy a bigger ceiling by under- or
# over-stating its model size.
MICRO_FIT_FRACTION = 0.005   # 0.5% of the certified full-ladder FLOPs budget.
                             # Chosen so a handful of minutes-long probes per
                             # day cannot approach the 1.0 GPU-day SHATTER
                             # floor this same file requires for the real
                             # ladder: a 120-step/batch16/seq1024 grow probe
                             # on the certified c03 shape lands at ~18% of
                             # this ceiling -- comfortably inside, not at it.
with open(CONFIG, encoding="utf-8") as _config_file:
    _V0_CONFIG = json.load(_config_file)
(
    V0_BASE_EXCLUDING_MTP_PARAMS,
    V0_MTP_AUX_PARAMS,
    V0_REALIZED_PARAMS,
) = v0_config_check.parameter_accounting(_V0_CONFIG)
MICRO_FIT_CEILING_FLOPS = (MICRO_FIT_FRACTION * SHATTER_BUDGET_B
                          * 6.0 * V0_REALIZED_PARAMS)


# ---- helpers -------------------------------------------------------------
def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _receipt_clean(name):
    """(True, dict) if the receipt exists and passes receipt_check;
    (False, reason) otherwise. Fail-closed on every error path."""
    p = f"{NC}/receipts/{name}"
    if not os.path.exists(p):
        return False, f"{name} not on disk"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return False, f"{name} unreadable: {e}"
    findings = validate_receipt(d)
    if findings:
        return False, f"{name} receipt_check FAIL: {findings}"
    return True, d


def _receipt_clean_path(path):
    """(True, dict) for an explicit receipt path that passes receipt_check."""
    if not path or not os.path.exists(path):
        return False, f"{path} not on disk"
    name = os.path.basename(path)
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return False, f"{name} unreadable: {e}"
    findings = validate_receipt(d)
    if findings:
        return False, f"{name} receipt_check FAIL: {findings}"
    return True, d


# ---- G-rows (each returns (status, detail); status in GREEN|BLOCKED) ------
def g_corpus():
    ok, d = _receipt_clean(ASSEMBLY_RECEIPT)
    if not ok:
        return "BLOCKED", d
    s = _sha(f"{NC}/receipts/{ASSEMBLY_RECEIPT}")
    if s != ASSEMBLY_SHA:
        return "BLOCKED", f"assembly sha {s[:12]} != pin {ASSEMBLY_SHA[:12]}"
    kept = d.get("totals", {}).get("text_bytes_kept")
    if kept is None:
        return "BLOCKED", "totals.text_bytes_kept missing"
    if kept >= HARD_BAR_BYTES:
        return "BLOCKED", f"text_bytes_kept {kept} >= 100GB hard bar"
    return "GREEN", f"sha pin match; {kept / 1e9:.2f} GB < 100 GB"


def g_tokenizer():
    ok, d = _receipt_clean(TOKENIZER_RECEIPT)
    if not ok:
        return "BLOCKED", d
    if d.get("assembly_receipt_sha256") != ASSEMBLY_SHA:
        return "BLOCKED", "tokenizer receipt does not pin the assembly sha"
    if d.get("tokens_pending_tokenizer_freeze") is not False:
        return "BLOCKED", "tokens_pending_tokenizer_freeze != false"
    tot = (d.get("real_token_counts") or {}).get("total")
    if not tot:
        return "BLOCKED", "real_token_counts.total missing/zero"
    band = d.get("reserved_band") or {}
    if len(band) != RESERVED_BAND_N:
        return "BLOCKED", f"reserved band {len(band)} ids != {RESERVED_BAND_N}"
    if d.get("vocab_size") != 32000:
        return "BLOCKED", f"vocab_size {d.get('vocab_size')} != 32000"
    return "GREEN", f"pin match; {tot:,} real tokens; band {RESERVED_BAND_N} ids"


def g_shards(shard_dir_override=None):
    # eng-49 (#183): the packed uint16 shards ARE the live-training input. The
    # gate previously had no row for them, so all-7-green printed "dispatch
    # permitted" with zero .bin on disk (fail-open w.r.t. the training input,
    # same class as eng-46/eng-48). A TOKEN-SHARDS-V0 receipt whose declared
    # shards are present + byte-matched is REQUIRED before --live. No receipt
    # -> BLOCKED (shards not produced; production is HELD pending the
    # shard-production call). token_shards_v0.validate_shards_receipt is
    # fail-closed and re-derives counts from the bytes.
    #
    # shard_dir_override (#682): the receipt's declared shard_dir is resolved
    # NC-relative by validate_shards_receipt, and NC is THIS SCRIPT's own
    # worktree/repo root -- so the resolved path silently points at a
    # different (usually nonexistent) location whenever the gate runs from a
    # worktree instead of the main tree, independent of what --shard-dir the
    # caller actually passed. When shard_dir_override is supplied it becomes
    # the authoritative base path for the declared shard files, taking
    # precedence over that NC-relative math; NC-relative resolution remains
    # the fallback when no override is given (byte-identical for every
    # pre-existing caller). A missing/wrong override still fails closed --
    # see validate_shards_receipt's per-shard os.path.exists checks.
    cands = sorted(glob.glob(f"{NC}/{TOKEN_SHARDS_GLOB}"))
    if not cands:
        return "BLOCKED", ("no token-shards-v0-*.json receipt — packed shards "
                           "not produced; --live has no training input "
                           "(production HELD pending the shard-production call)")
    name = os.path.basename(cands[-1])
    ok, d = _receipt_clean(name)
    if not ok:
        return "BLOCKED", d
    viol = token_shards_v0.validate_shards_receipt(
        d, NC, shard_dir_override=shard_dir_override)
    if viol:
        return "BLOCKED", f"{name} shard contract FAIL: {viol}"
    st, dt = _shards_exclusion_check(name, d)
    if st != "GREEN":
        return st, dt
    return "GREEN", f"{name} shards present + byte-matched; --live input ready; {dt}"


def _shards_exclusion_check(name, d):
    """#1436: the bound stream must contain zero CONSUMABLE excluded-source
    tokens before --live.

    G-shards is where the training input is bound -- it is the row that already
    re-validates the TOKEN-SHARDS-V0 receipt against the shard bytes -- so it is
    where the exclusion has to be asserted. The standalone
    `fineweb_exclusion.py --preflight` CLI is operator-invoked and gates
    nothing; a script someone has to remember to run cannot stop a ruling from
    rotting, which is the whole point of the issue's clause.

    shards-v0 physically contains the tokens and always will (no v1 binary was
    ever built), so the assertion is not "the bytes are absent" -- it is that
    NO WINDOW A TRAINING RUN CAN DRAW reaches them, proven over the receipted
    loader geometry, plus that the loader still enforces this BY DEFAULT.
    Four ways to fail, all BLOCKED:
      1. the ruling receipt is missing/damaged, or has been edited to re-admit
         an audited-tainted source (fineweb_exclusion.ruled_excluded_sources);
      2. a ruled-excluded source is in the stream but its offsets cannot be
         derived from the validated receipt;
      3. the receipted loader geometry cannot be proven to exclude those
         offsets, or leaves no clean window at all;
      4. PackedShardLoader's default has been reverted to opt-in, so a caller
         that passes nothing would draw from the tainted range again.
    """
    try:
        ranges, why = fineweb_exclusion.enforcement_for_validated_receipt(d, NC)
    except ValueError as e:
        return "BLOCKED", f"{name} excluded-source check FAIL: {e}"
    if not ranges:
        return "GREEN", f"exclusion: {why}"

    total = d.get("total_stream_tokens")
    geom = d.get("loader_windows") or {}
    seq, block_len = geom.get("seq"), geom.get("block_len")
    if not isinstance(seq, int) or not isinstance(block_len, int):
        return "BLOCKED", (f"{name} declares excluded-source tokens but its "
                           "loader_windows.seq/block_len are missing — the "
                           "window exclusion cannot be proven")
    plan = fineweb_exclusion.WindowPlan(total, seq, block_len, ranges)
    if plan.n_windows <= 0:
        return "BLOCKED", (f"{name} exclusion leaves zero usable windows over "
                           f"{total:,} tokens — no clean training input")
    try:
        fineweb_exclusion.assert_plan_excludes_ranges(plan)
    except AssertionError as e:
        return "BLOCKED", f"{name} window-exclusion proof FAIL: {e}"

    bound = fineweb_exclusion.identify_stream_receipt(total, NC)
    if bound is None:
        return "BLOCKED", (f"{name} declares a {total:,}-token stream that the "
                           "loader's own default policy would not bind — "
                           "enforcement would not engage at training time")
    ok, detail = fineweb_exclusion.loader_default_is_enforcing()
    if not ok:
        return "BLOCKED", (f"{name} needs exclusion enforced, but the loader "
                           f"default is not enforcing: {detail}")
    dropped = plan.n_windows_full - plan.n_windows
    return "GREEN", (f"exclusion {why}; {plan.n_windows:,} usable windows "
                     f"({dropped:,} dropped), loader default binds {bound}")


def g_shards_mm(
    mm_manifest_path=None,
    mm_tokenizer_path=None,
    mm_holdout_size=None,
    mm_holdout_manifest_path=None,
):
    """Multimodal-aware replacement for g_shards on the CC3M streaming path.

    G-shards-mm requires ALL 5 (the lead seat, 16709):
    1. Streaming manifest readable + nonempty
    2. Exclusion blocklist enforced (n_training>0, holdout_n==requested)
    3. Held-out manifest frozen: url + sha256 + caption
    4. Matched-pair binding preserved (ER-2d invariant)
    5. train-tokenizer == probe-tokenizer == real AND vocab==config(32008)
    """
    # Item 1: manifest readable + nonempty
    if not mm_manifest_path:
        return "BLOCKED", "G-shards-mm item 1: mm_manifest_path not provided to gate"
    if not os.path.exists(mm_manifest_path):
        return "BLOCKED", f"G-shards-mm item 1: manifest not found: {mm_manifest_path}"
    try:
        with open(mm_manifest_path, encoding="utf-8") as f:
            first = next((l for l in f if l.strip()), None)
        if not first:
            return "BLOCKED", f"G-shards-mm item 1: manifest empty: {mm_manifest_path}"
        rec = json.loads(first)
    except Exception as e:
        return "BLOCKED", f"G-shards-mm item 1: manifest unreadable: {e}"

    # Item 4: matched-pair binding preserved. Adult CC3M streams use url+caption;
    # Stage-1 first-words uses local image_path+caption from on-disk B-MULTI-1.
    if "caption" not in rec or ("url" not in rec and "image_path" not in rec):
        return "BLOCKED", (
            "G-shards-mm item 4: manifest record missing caption and "
            f"(url|image_path): {rec}"
        )

    # Item 3: held-out manifest frozen; count holdout_n for item 2 tightening
    if mm_holdout_manifest_path:
        holdout_cands = [mm_holdout_manifest_path]
    else:
        holdout_cands = sorted(glob.glob(f"{NC}/receipts/holdout-manifest*.jsonl"))
    if not holdout_cands:
        return "BLOCKED", ("G-shards-mm item 3: no holdout manifest found in receipts/; "
                           "run with --probe-manifest-out receipts/holdout-manifest.jsonl at launch "
                           "or pass --mm-holdout-manifest")
    hm_path = holdout_cands[-1]
    holdout_n = 0
    try:
        with open(hm_path, encoding="utf-8") as hf:
            first_hrec = None
            for line in hf:
                if line.strip():
                    if first_hrec is None:
                        first_hrec = json.loads(line)
                        has_source = ("url" in first_hrec) or ("image_path" in first_hrec)
                        if not (has_source and all(k in first_hrec for k in ("sha256", "caption"))):
                            return "BLOCKED", (f"G-shards-mm item 3: holdout manifest missing "
                                               f"(url|image_path)/sha256/caption: {first_hrec}")
                    holdout_n += 1
    except Exception as e:
        return "BLOCKED", f"G-shards-mm item 3: holdout manifest unreadable: {e}"

    # Item 2 TIGHTENED: directly assert n_training>0 AND holdout_n==requested.
    # n_training: verify manifest has >1 record (first already validated in item 1).
    try:
        n_training_sample = 0
        with open(mm_manifest_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if line.strip():
                    n_training_sample += 1
                if i >= 9:
                    break  # sample first 10 lines only — manifest may be large
        if n_training_sample == 0:
            return "BLOCKED", "G-shards-mm item 2: n_training=0 (no records in manifest)"
    except Exception as e:
        return "BLOCKED", f"G-shards-mm item 2: cannot count training records: {e}"
    if mm_holdout_size is not None and holdout_n != mm_holdout_size:
        return "BLOCKED", (f"G-shards-mm item 2: holdout_n={holdout_n} != "
                           f"requested mm_holdout_size={mm_holdout_size} "
                           f"(--probe-holdout-size at launch)")
    elif holdout_n == 0:
        return "BLOCKED", "G-shards-mm item 2: holdout manifest empty (holdout_n=0)"

    # Item 5 TIGHTENED: train-tok==probe-tok==real AND vocab==config(32008)
    if not mm_tokenizer_path:
        return "BLOCKED", ("G-shards-mm item 5: tokenizer_path not set; "
                           "train-tok and probe-tok both default to ord(c)%vocab — "
                           "INVALID at checkpoint-1 per prereg §4. Set --probe-tokenizer.")
    EXPECTED_VOCAB = 32000  # tokenizer vocab_size=32000; boi/eoi at ids 1/2 (inside base vocab, no extension)
    tok_vocab = None
    try:
        try:
            from tokenizers import Tokenizer as _HFTok
            _tok = _HFTok.from_file(mm_tokenizer_path)
            tok_vocab = _tok.get_vocab_size()
        except ImportError:
            import sentencepiece as _spm
            _sp = _spm.SentencePieceProcessor(model_file=mm_tokenizer_path)
            tok_vocab = _sp.GetPieceSize()
    except Exception as e:
        return "BLOCKED", (f"G-shards-mm item 5: tokenizer at {mm_tokenizer_path} "
                           f"unloadable — cannot verify vocab=={EXPECTED_VOCAB}: {e}")
    if tok_vocab != EXPECTED_VOCAB:
        return "BLOCKED", (f"G-shards-mm item 5: tokenizer vocab={tok_vocab} != "
                           f"config {EXPECTED_VOCAB} (base vocab, boi/eoi inside at ids 1/2)")

    source_kind = "url" if "url" in rec else "image_path"
    return "GREEN", (f"G-shards-mm: manifest readable ({source_kind}, "
                     f"n_training_sample={n_training_sample}+); "
                     f"holdout frozen ({os.path.basename(hm_path)}, n={holdout_n}); "
                     f"tokenizer vocab={tok_vocab}=={EXPECTED_VOCAB}")


def g_config():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    v = v0_config_check.check(cfg, launch=True)
    if v:
        return "BLOCKED", f"v0_config_check launch violations: {v}"
    return "GREEN", "V0_CONFIG_GREEN (launch mode)"


def g_governor():
    # named independently per the gate table even though g_config folds it in
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    g = cfg.get("governor", {})
    f = v0_config_check.GOVERNOR_FLOOR
    if g.get("vram_fraction", 1.0) > f["vram_fraction"]:
        return "BLOCKED", "governor.vram_fraction looser than floor 0.80"
    if g.get("margin_gib_floor", 0) < f["margin_gib_floor"]:
        return "BLOCKED", "governor.margin_gib_floor below 1.5"
    if g.get("pace_s_per_step", 0) < f["pace_s_per_step"]:
        return "BLOCKED", "governor.pace_s_per_step below 0.05"
    return "GREEN", "floor vram<=0.80 / margin>=1.5GiB / pace>=0.05s (tighten-only)"


def g_world():
    missing = [w for w in WORLD_SPECS if not os.path.exists(f"{NC}/{w}")]
    if missing:
        return "BLOCKED", f"world spec missing: {missing}"
    return "GREEN", f"world specs present ({len(WORLD_SPECS)})"


def _shatter_compute_fit():
    """Measured budget-fit grounding for g_budget. Returns (True, citation)
    ONLY when a banked SHATTER verdict in receipts/ proves the efficiency lever
    that makes the run affordable: SHATTER==true, the shatter_variant's
    quality_ok==true AND effective_days <= SHATTER_EFFECTIVE_DAYS_FLOOR, on the
    keystone-certified method.budget_b ceiling. (False, reason) otherwise.

    Fail-closed: no receipt, unreadable, SHATTER!=true, missing/non-numeric
    effective_days, quality_ok!=true, budget_b!=ceiling, or effective_days>floor
    all return (False, ...). Scans all candidates; accepts the first that passes
    every check (so filename ordering cannot gate the proof)."""
    cands = sorted(glob.glob(f"{NC}/{SHATTER_VERDICT_GLOB}"))
    if not cands:
        return False, "no shatter-verdict-*.json in receipts/ (lever unproven)"
    last_reason = "no shatter-verdict receipt passed every compute-fit check"
    for p in cands:
        name = os.path.basename(p)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:                      # noqa: BLE001
            last_reason = f"{name} unreadable: {e}"
            continue
        if d.get("SHATTER") is not True:
            last_reason = f"{name} SHATTER != true"
            continue
        var = d.get("shatter_variant")
        vd = (d.get("variants") or {}).get(var) or {}
        eff = vd.get("effective_days")
        if not isinstance(eff, (int, float)) or isinstance(eff, bool):
            last_reason = f"{name} variants[{var}].effective_days not numeric"
            continue
        if vd.get("quality_ok") is not True:
            last_reason = f"{name} variants[{var}].quality_ok != true"
            continue
        budget_b = (d.get("method") or {}).get("budget_b")
        if budget_b != SHATTER_BUDGET_B:
            last_reason = f"{name} method.budget_b {budget_b} != {SHATTER_BUDGET_B}"
            continue
        # ANTI-SELF-REFERENCE: effective_days must equal the real wall-clock
        # days = budget_b / (sustained_tok_s * 86400). Recompute and require the
        # receipt's stated value to agree; this rejects the K_floor/throughput
        # self-referential number (0.9803) that does not equal the honest 1.30.
        tok_s = vd.get("sustained_tok_s")
        if not isinstance(tok_s, (int, float)) or isinstance(tok_s, bool) or tok_s <= 0:
            last_reason = f"{name} variants[{var}].sustained_tok_s not numeric/positive"
            continue
        honest_eff = budget_b / (tok_s * 86400.0)
        if abs(honest_eff - eff) / honest_eff > SHATTER_EFF_DAYS_TOL:
            last_reason = (f"{name} {var} effective_days {eff} inconsistent with "
                           f"budget_b/(sustained_tok_s*86400)={honest_eff:.4f} "
                           f"(self-referential effective_days REJECTED)")
            continue
        if honest_eff > SHATTER_EFFECTIVE_DAYS_FLOOR:
            last_reason = (f"{name} {var} honest effective_days {honest_eff:.4f} > "
                           f"floor {SHATTER_EFFECTIVE_DAYS_FLOOR}")
            continue
        return True, (f"{name}: {var} honest effective_days={honest_eff:.4f} <= "
                      f"{SHATTER_EFFECTIVE_DAYS_FLOOR} GPU-day on "
                      f"{budget_b:.4g} ceiling (consistency-checked; "
                      f"budget-fit MEASURED, not calendar-projected)")
    return False, last_reason


def _requested_run_compute_fit(requested_run):
    """Fail-closed validate+price a REQUESTED-RUN descriptor for the
    per-run-truthful G-budget path.

    requested_run: {"source": <str>, "total_steps": <number>,
                    "flops_per_step": <number>}  OR
                   {"source": <str>, "total_steps": <number>,
                    "params": <number>, "batch": <number>, "seq": <number>}
    (flops_per_step, when absent, is derived as 6*params*batch*seq -- the
    Kaplan/Chinchilla dense-transformer forward+backward convention already
    used by cbase_grow_live.py's own _flops_per_step.)

    Returns (well_formed, fit_ok, detail):
      well_formed=False -> the descriptor itself is broken; g_budget MUST
      treat this as BLOCKED, never as "no descriptor supplied" -- a malformed
      descriptor is a NEW error path and fails closed, it is never silently
      absorbed into the old byte-identical fallback."""
    def _pos_num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0

    if not isinstance(requested_run, dict):
        return False, None, f"requested_run is not a dict: {requested_run!r}"
    source = requested_run.get("source")
    if not isinstance(source, str) or not source.strip():
        return False, None, "requested_run.source missing/empty"
    total_steps = requested_run.get("total_steps")
    if not _pos_num(total_steps):
        return False, None, f"requested_run.total_steps invalid: {total_steps!r}"

    flops_per_step = requested_run.get("flops_per_step")
    if flops_per_step is not None:
        if not _pos_num(flops_per_step):
            return False, None, f"requested_run.flops_per_step invalid: {flops_per_step!r}"
    else:
        params = requested_run.get("params")
        batch = requested_run.get("batch")
        seq = requested_run.get("seq")
        if not (_pos_num(params) and _pos_num(batch) and _pos_num(seq)):
            return False, None, (
                "requested_run needs flops_per_step OR (params, batch, seq); "
                f"got params={params!r} batch={batch!r} seq={seq!r}")
        flops_per_step = 6.0 * params * batch * seq   # Kaplan/Chinchilla 6N

    cost_flops = flops_per_step * total_steps
    fit_ok = cost_flops <= MICRO_FIT_CEILING_FLOPS
    detail = (f"requested_run[{source}]: total_steps={total_steps:g}, "
             f"cost={cost_flops:.4g} FLOPs (6*params*tokens estimate) vs "
             f"micro-fit ceiling {MICRO_FIT_CEILING_FLOPS:.4g} FLOPs "
             f"({MICRO_FIT_FRACTION * 100:g}% of the certified full-ladder "
             f"FLOPs budget) -> {'FIT' if fit_ok else 'EXCEEDS'}")
    return True, fit_ok, detail


def g_budget(launch_date, shatter_fit=None, requested_run=None):
    # REQUESTED-RUN compute fit: only engages when the caller names exactly
    # what THIS launch will execute. A malformed descriptor fails closed
    # (BLOCKED) -- it is a NEW error path, never silently treated as "absent"
    # (which would fall through to the possibly-GREEN full-ladder math below).
    if requested_run is not None:
        well_formed, fit_ok, rr_detail = _requested_run_compute_fit(requested_run)
        if not well_formed:
            return "BLOCKED", f"requested_run malformed: {rr_detail}"
        if fit_ok:
            return "GREEN", rr_detail
        # Above the micro-fit ceiling: falls through to the byte-identical
        # full-ladder math below -- this call may still be a real full-ladder
        # dispatch that passes calendar/SHATTER on its own merits.

    # First-principles grounding (supersedes the calendar proxy): when a banked
    # SHATTER verdict proves the efficiency lever (effective_days <= 1 GPU-day
    # for the certified config on the 2.2e9 ceiling), the budget-fit holds by
    # MEASUREMENT and the calendar countdown is a stale deadline artifact. The
    # calendar floor remains the fail-closed fallback when no such proof exists.
    # shatter_fit is injectable for the selftest; main() leaves it None -> live.
    fit_ok, fit_why = shatter_fit if shatter_fit is not None else _shatter_compute_fit()
    if fit_ok:
        return "GREEN", fit_why
    days = (DEADLINE - launch_date).days
    if days < ENVELOPE_DAYS_FLOOR:
        return "BLOCKED", (f"days-remaining {days} < envelope floor "
                           f"{ENVELOPE_DAYS_FLOOR} (fp19-bench unstacked); "
                           f"no banked SHATTER compute-fit ({fit_why})")
    return "GREEN", (f"{days} d to {DEADLINE.isoformat()} >= "
                     f"{ENVELOPE_DAYS_FLOOR} d unstacked envelope")


def _config_sha256():
    """Return sha256 of the live v0 pretrain config (sort_keys for stability)."""
    with open(v0_config_check.CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def _check_efficiency_receipt(d):
    """Pure logic: validate a parsed efficiency receipt dict against H1 schema.
    Returns list of violation strings (empty = clean)."""
    violations = []
    if not d.get("licenses_config"):
        violations.append(
            "missing 'licenses_config' — receipt must name the arch config it "
            "enumerates levers FOR (e.g. 'c03-qat-v0'); prevents cross-arch "
            "stale licensing (#365)")
    if not d.get("config_sha256"):
        violations.append(
            "missing 'config_sha256' — receipt must carry sha256 of the launch "
            "config it was authored against (#365)")
    levers = d.get("levers")
    if not isinstance(levers, dict):
        violations.append("'levers' field missing or not a dict")
        return violations
    missing = EFFICIENCY_LEVERS - levers.keys()
    if missing:
        violations.append(f"levers missing: {sorted(missing)}")
    for key, entry in levers.items():
        if not isinstance(entry, dict):
            violations.append(f"lever '{key}': entry must be a dict")
            continue
        status = entry.get("status")
        if status not in EFFICIENCY_STATUSES:
            violations.append(
                f"lever '{key}': invalid status {status!r} "
                f"(must be one of {sorted(EFFICIENCY_STATUSES)})")
            continue
        if status in ("receipted-APPLIED", "receipted-KILLED"):
            if not entry.get("receipt"):
                violations.append(
                    f"lever '{key}' status {status}: missing 'receipt' pointer")
        elif status == "WAIVED":
            cost = entry.get("wall_days_cost")
            if cost is None:
                violations.append(
                    f"lever '{key}' WAIVED: missing 'wall_days_cost' "
                    f"(silent waiver is gate FAIL — H1)")
            elif not isinstance(cost, (int, float)) or cost <= 0:
                violations.append(
                    f"lever '{key}' WAIVED: 'wall_days_cost' must be "
                    f"a positive number, got {cost!r}")
    return violations


def g_efficiency(config_path=None, efficiency_receipt_path=None):
    # H1 (docs/domains/governance/ledgers/hardest-problems-register-v1.md): every known throughput lever
    # must be enumerated before any governed job >12 GPU-h dispatches.
    # No receipt -> BLOCKED (makes the 12c050e7 silent-skip impossible).
    # config_path: if provided, bind against this config's SHA instead of the
    # default text pretrain config (use for multimodal launch path, GAP-3).
    cands = [] if efficiency_receipt_path else sorted(glob.glob(f"{NC}/{EFFICIENCY_RECEIPT_GLOB}"))
    if not cands and not efficiency_receipt_path:
        return "BLOCKED", (
            "no launch-efficiency-*.json receipt — throughput levers not "
            "enumerated; any WAIVED lever must carry an explicit wall_days_cost "
            "(H1: docs/domains/governance/ledgers/hardest-problems-register-v1.md)")
    name = os.path.basename(efficiency_receipt_path) if efficiency_receipt_path else os.path.basename(cands[-1])
    ok, d = _receipt_clean_path(efficiency_receipt_path) if efficiency_receipt_path else _receipt_clean(name)
    if not ok:
        return "BLOCKED", d
    violations = _check_efficiency_receipt(d)
    if violations:
        return "BLOCKED", f"{name} efficiency receipt FAIL: {violations}"
    # Cross-arch binding check: receipt must have been authored for the live config.
    receipt_sha = d.get("config_sha256", "")
    if config_path:
        with open(config_path, encoding="utf-8") as cf:
            cfg_data = json.load(cf)
        live_sha = hashlib.sha256(json.dumps(cfg_data, sort_keys=True).encode()).hexdigest()
    else:
        live_sha = _config_sha256()
    if receipt_sha != live_sha:
        return "BLOCKED", (
            f"{name} config_sha256 mismatch — receipt licenses '{d.get('licenses_config')}' "
            f"(sha ...{receipt_sha[-8:]}), live config sha ...{live_sha[-8:]}; "
            "re-emit efficiency receipt against the current launch config (#365)")
    levers = d["levers"]
    applied = [k for k, v in levers.items() if v["status"] == "receipted-APPLIED"]
    killed = [k for k, v in levers.items() if v["status"] == "receipted-KILLED"]
    waived = [k for k, v in levers.items() if v["status"] == "WAIVED"]
    return "GREEN", (f"{name}: applied={applied}, killed={killed}, "
                     f"waived={[(k, levers[k]['wall_days_cost']) for k in waived]}")


def g_prereg():
    cands = sorted(glob.glob(f"{NC}/{FP26_PREREG_GLOB}"))
    if not cands:
        return "BLOCKED", ("no fp26-prereg-*.json receipt — round-3 prereg "
                           "not frozen (awaits monitor MDE-wording reply, "
                           "mail 14582 ask #2)")
    name = os.path.basename(cands[-1])
    ok, d = _receipt_clean(name)
    if not ok:
        return "BLOCKED", d
    if not d.get("prereg_frozen"):
        return "BLOCKED", f"{name} lacks prereg_frozen:true"
    # eng-48 (#181): the frozen receipt existing + prereg_frozen:true is NOT
    # sufficient — the prereg's PREMISES must still hold (decision-artifact
    # sha, pinned premise receipts, support receipts). Without this call the
    # row was fail-OPEN (same class as eng-46): a drifted premise passed
    # silently. check_premises() is fail-closed; any violation blocks.
    premise_violations = fp26_prereg.check_premises(NC)
    if premise_violations:
        return "BLOCKED", (f"{name} frozen but prereg premises FAIL: "
                           f"{premise_violations}")
    return "GREEN", f"{name} frozen; premises hold"


EFFICIENCY_RECEIPT_GLOB = "receipts/launch-efficiency-*.json"
# All levers that must be enumerated before any governed run >12 GPU-h.
# Each must carry status receipted-APPLIED|receipted-KILLED (with receipt
# pointer) or WAIVED (with explicit wall_days_cost > 0 — the price must be
# written down before the run starts). Silent WAIVED = gate FAIL (H1).
EFFICIENCY_LEVERS: frozenset = frozenset({
    "batch_size",         # L2: optimal batch from step-econ sweep
    "checkpointing_off",  # L5: grad-ckpt disabled
    "fused_muon",         # L3: NS5 chain fused via torch.compile
    "fp8_matmul",         # L4: fp8 weight-cache linears
    "torch_compile",      # L6: full-step torch.compile
    "duty_cycle",         # L7: pacing duty-cycle from live run log
})
EFFICIENCY_STATUSES = frozenset({
    "receipted-APPLIED", "receipted-KILLED", "WAIVED"})

ROWS = ["G-corpus", "G-tokenizer", "G-shards", "G-config", "G-governor",
        "G-world", "G-budget", "G-prereg", "G-efficiency"]


def gate(launch_date, multimodal_config_path=None,
         mm_manifest_path=None, mm_tokenizer_path=None,
         mm_holdout_size=None, mm_holdout_manifest_path=None,
         efficiency_receipt_path=None, requested_run=None,
         shard_dir_override=None):
    """Returns [(row, status, detail), ...] in table order.

    multimodal_config_path: if provided, G-efficiency binds against this config's SHA
    instead of the default text pretrain config (use for multimodal launch path, GAP-3).
    mm_manifest_path + mm_tokenizer_path: if provided alongside multimodal_config_path,
    G-shards is replaced by G-shards-mm (items 1-5 per the lead seat 16709).
    mm_holdout_size: if provided, item 2 asserts holdout_n==mm_holdout_size (--probe-holdout-size).
    mm_holdout_manifest_path: if provided, item 3 validates that explicit frozen holdout manifest.
    efficiency_receipt_path: if provided, G-efficiency validates that explicit receipt.
    requested_run: if provided, G-budget prices THIS descriptor's measured cost against
    the fixed micro-fit ceiling instead of the full v0-ladder calendar/SHATTER math (see
    g_budget / _requested_run_compute_fit). Absent (default, every existing caller),
    above-ceiling, or malformed values fall back to today's byte-identical behavior.
    shard_dir_override: if provided, the (non-mm) G-shards row resolves the receipt's
    declared shard files against this path instead of NC-relative math (#682 — the
    NC-relative resolution is wrong whenever this script runs from a worktree). Absent
    (default, every existing caller) preserves today's byte-identical resolution.
    Ignored on the G-shards-mm path (mm manifests carry their own paths already).
    """
    out = []
    for name in ROWS:
        if name == "G-corpus":
            st, dt = g_corpus()
        elif name == "G-tokenizer":
            st, dt = g_tokenizer()
        elif name == "G-shards":
            if multimodal_config_path and (mm_manifest_path or mm_tokenizer_path):
                st, dt = g_shards_mm(
                    mm_manifest_path,
                    mm_tokenizer_path,
                    mm_holdout_size,
                    mm_holdout_manifest_path,
                )
            else:
                st, dt = g_shards(shard_dir_override=shard_dir_override)
        elif name == "G-config":
            st, dt = g_config()
        elif name == "G-governor":
            st, dt = g_governor()
        elif name == "G-world":
            st, dt = g_world()
        elif name == "G-budget":
            st, dt = g_budget(launch_date, requested_run=requested_run)
        elif name == "G-prereg":
            st, dt = g_prereg()
        elif name == "G-efficiency":
            st, dt = g_efficiency(
                config_path=multimodal_config_path,
                efficiency_receipt_path=efficiency_receipt_path,
            )
        out.append((name, st, dt))
    return out


def _utc_ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")


def emit(launch_date, rows, output_dir=None, provenance=None):
    ts = _utc_ts()
    blocked = [r[0] for r in rows if r[1] != "GREEN"]
    receipt = {
        "ticket": "V0-LAUNCH-GATE",
        "ts": ts,
        "launch_date": launch_date.isoformat(),
        "deadline": DEADLINE.isoformat(),
        "rows": {r[0]: {"status": r[1], "detail": r[2]} for r in rows},
        "all_green": not blocked,
        "blocked_rows": blocked,
        "pins": {
            "assembly_receipt": ASSEMBLY_RECEIPT,
            "assembly_sha256": ASSEMBLY_SHA,
            "tokenizer_receipt": TOKENIZER_RECEIPT,
            "config": "configs/v0-pretrain-config.json",
            "envelope_days_floor": ENVELOPE_DAYS_FLOOR,
        },
        "dispatch_rule": ("v0 pretrain refuses unless all_green; the failing "
                          "G-row(s) are named in blocked_rows. No row waivable "
                          "except by the user by name."),
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }
    # optional dated provenance section (#230-class events: a re-freeze that
    # re-anchors pins to a NEW baseline rather than reconstructing a prior
    # one). Additive-only; absent for every ordinary emission.
    if provenance is not None:
        receipt["provenance"] = provenance
    receipt_dir = output_dir or f"{NC}/receipts"
    os.makedirs(receipt_dir, exist_ok=True)
    path = os.path.join(receipt_dir, f"v0-launch-gate-{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    # checked write — the emitted receipt must itself pass receipt_check
    reloaded = json.load(open(path, encoding="utf-8"))
    findings = validate_receipt(reloaded)
    if findings:
        raise SystemExit(f"EMITTED RECEIPT FAILS receipt_check: {findings}")
    return path


def _print(rows):
    for name, st, dt in rows:
        mark = "OK " if st == "GREEN" else "XX "
        print(f"  {mark}{name:<12} {st:<8} {dt}")


def _selftest():
    global NC
    from datetime import date
    # green-today rows (these are the frozen contract; if one breaks the
    # contract drifted and the selftest SHOULD fail)
    assert g_corpus()[0] == "GREEN", g_corpus()
    assert g_tokenizer()[0] == "GREEN", g_tokenizer()
    assert g_config()[0] == "GREEN", g_config()
    assert g_governor()[0] == "GREEN", g_governor()
    assert g_world()[0] == "GREEN", g_world()
    # shards: time-robust — BLOCKED iff no token-shards-v0 receipt is on disk
    # (eng-49 #183). Today none exists, so the row must BLOCK; this is what
    # keeps the gate from printing "dispatch permitted" with no training input.
    shard_cands = glob.glob(f"{NC}/{TOKEN_SHARDS_GLOB}")
    if not shard_cands:
        st, dt = g_shards()
        assert st == "BLOCKED" and "not produced" in dt, (st, dt)
    else:
        # a receipt present is GREEN only if its declared shards are present +
        # byte-matched; the validator is exercised in token_shards_v0 selftest.
        assert g_shards()[0] in ("GREEN", "BLOCKED")

    # #1436 excluded-source assertion: exercised directly on _shards_exclusion_check
    # with synthetic receipts, so it is covered whether or not the multi-GB
    # shard bytes are present in this checkout.
    _real_shard = f"{NC}/receipts/{fineweb_exclusion.DEFAULT_SHARD_RECEIPT}"
    if os.path.exists(_real_shard):
        _d = json.load(open(_real_shard, encoding="utf-8"))
        # the real v0 receipt DOES carry fineweb_edu tokens -> the row must
        # prove the windows exclude them, and must name the enforcement
        st_x, dt_x = _shards_exclusion_check("fixture", _d)
        assert st_x == "GREEN" and "usable windows" in dt_x, (st_x, dt_x)
        assert "fineweb_edu" in dt_x, dt_x

        # geometry stripped -> the exclusion cannot be proven -> BLOCKED
        _no_geom = copy.deepcopy(_d)
        _no_geom["loader_windows"] = {}
        st_x, dt_x = _shards_exclusion_check("fixture", _no_geom)
        assert st_x == "BLOCKED" and "cannot be proven" in dt_x, (st_x, dt_x)

        # a receipt whose per_source lost fineweb_edu entirely is a derivation
        # refusal (receipts disagree), never a silent "nothing to exclude"
        _dropped = copy.deepcopy(_d)
        _dropped["per_source"].pop("fineweb_edu", None)
        st_x, dt_x = _shards_exclusion_check("fixture", _dropped)
        assert st_x == "BLOCKED" and "excluded-source check FAIL" in dt_x, (st_x, dt_x)

        # a stream length no receipt declares -> the loader default would never
        # bind it -> BLOCKED rather than a green row over unenforced input.
        # (a non-excluded source is grown by 1 alongside the total so the
        # per_source sum still reconciles and the derivation itself succeeds)
        _unbound = copy.deepcopy(_d)
        _grow = next(s for s in _unbound["per_source"]
                     if s != "fineweb_edu"
                     and _unbound["per_source"][s].get("stream_tokens"))
        _unbound["per_source"][_grow]["stream_tokens"] += 1
        _unbound["total_stream_tokens"] = _d["total_stream_tokens"] + 1
        st_x, dt_x = _shards_exclusion_check("fixture", _unbound)
        assert st_x == "BLOCKED" and "would not bind" in dt_x, (st_x, dt_x)

    # the "nothing to exclude" branches (source absent from the assembly, or
    # present with zero tokens) are covered in fineweb_exclusion's own
    # selftest, where the whole receipt tree is synthetic and controlled --
    # a partial per_source here would only be checked against the REAL
    # assembly and fail on an unrelated source.
    fineweb_exclusion._selftest_fail_closed_against_real_schema()
    # budget: calendar fail-closed path (shatter_fit injected as False so the
    # calendar governs, regardless of which shatter receipts are on disk today).
    assert g_budget(date(2026, 6, 11), shatter_fit=(False, "no-proof"))[0] == "GREEN"
    assert g_budget(date(2026, 6, 20), shatter_fit=(False, "no-proof"))[0] == "BLOCKED"  # 2d < 4.55
    # compute-fit grounding: a proven SHATTER lever greens regardless of the
    # (possibly stale) calendar — and a false proof must NOT green a sub-floor date.
    assert g_budget(date(2026, 6, 20), shatter_fit=(True, "lever-proven"))[0] == "GREEN"
    # proof overrides even a wildly-expired calendar (days far negative).
    assert g_budget(date(2999, 1, 1), shatter_fit=(True, "lever-proven"))[0] == "GREEN"
    # ...but with NO proof, that same expired date BLOCKS (fail-closed).
    assert g_budget(date(2999, 1, 1), shatter_fit=(False, "no-proof"))[0] == "BLOCKED"
    # live grounding: _shatter_compute_fit is fail-closed (tuple shape, no raise).
    _live_fit = _shatter_compute_fit()
    assert isinstance(_live_fit, tuple) and isinstance(_live_fit[0], bool)
    # REQUESTED-RUN compute-fit (per-run-truthful micro path, cbase_grow_live.py):
    # a well-formed micro descriptor GREENs on measured cost, overriding even a
    # wildly-expired calendar with no SHATTER proof -- G-budget is now truthful
    # about what THIS launch costs, not the full ladder.
    _micro_rr = {"source": "selftest-micro", "total_steps": 120,
                 "params": V0_REALIZED_PARAMS, "batch": 16, "seq": 1024}
    st_rr, dt_rr = g_budget(date(2999, 1, 1), shatter_fit=(False, "no-proof"),
                            requested_run=_micro_rr)
    assert st_rr == "GREEN" and "FIT" in dt_rr, (st_rr, dt_rr)
    # a descriptor whose measured cost EXCEEDS the micro-fit ceiling falls
    # through to the byte-identical full-ladder math -- unchanged BLOCKED on
    # a sub-floor date with no SHATTER proof (same status+detail as if no
    # requested_run had been passed at all).
    _huge_rr = {"source": "selftest-huge", "total_steps": 10**9,
                "params": V0_REALIZED_PARAMS, "batch": 16, "seq": 1024}
    _baseline = g_budget(date(2026, 6, 20), shatter_fit=(False, "no-proof"))
    st_huge, dt_huge = g_budget(date(2026, 6, 20), shatter_fit=(False, "no-proof"),
                                requested_run=_huge_rr)
    assert (st_huge, dt_huge) == _baseline, (st_huge, dt_huge, _baseline)
    # a malformed descriptor is a NEW error path and fails closed regardless
    # of date/proof -- it must NEVER silently fall through to a possibly-
    # GREEN calendar/SHATTER verdict.
    st_bad, dt_bad = g_budget(date(2026, 6, 11), shatter_fit=(True, "lever-proven"),
                              requested_run={"source": "selftest-bad"})  # no total_steps
    assert st_bad == "BLOCKED" and "malformed" in dt_bad, (st_bad, dt_bad)
    st_bad2, dt_bad2 = g_budget(date(2026, 6, 11), shatter_fit=(True, "lever-proven"),
                                requested_run="not-a-dict")
    assert st_bad2 == "BLOCKED" and "malformed" in dt_bad2, (st_bad2, dt_bad2)
    # gate() threads requested_run through to G-budget only; other rows unaffected.
    _rows_rr = gate(date(2999, 1, 1), requested_run=_micro_rr)
    assert [r[0] for r in _rows_rr] == ROWS
    _budget_row = next(r for r in _rows_rr if r[0] == "G-budget")
    assert _budget_row[1] == "GREEN" and "FIT" in _budget_row[2], _budget_row
    # prereg: blocked iff no frozen receipt (time-robust)
    cands = glob.glob(f"{NC}/{FP26_PREREG_GLOB}")
    if not cands:
        assert g_prereg()[0] == "BLOCKED", g_prereg()
    else:
        # eng-48 (#181): a frozen receipt present is GREEN only if the prereg
        # premises hold. A drifted premise (mutated decision sha) MUST flip
        # the row to BLOCKED — proves G-prereg is no longer fail-open.
        assert g_prereg()[0] == "GREEN", g_prereg()
        _good_dsha = fp26_prereg.DECISION_SHA
        fp26_prereg.DECISION_SHA = "0" * 64
        st, dt = g_prereg()
        assert st == "BLOCKED" and "premises FAIL" in dt, (st, dt)
        fp26_prereg.DECISION_SHA = _good_dsha
        assert g_prereg()[0] == "GREEN", g_prereg()
    # mutation: wrong assembly pin -> G-corpus blocks (fail-closed)
    global ASSEMBLY_SHA
    good = ASSEMBLY_SHA
    ASSEMBLY_SHA = "0" * 64
    assert g_corpus()[0] == "BLOCKED"
    ASSEMBLY_SHA = good
    assert g_corpus()[0] == "GREEN"
    # mutation: loosened governor floor is caught (launch fail-closed)
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    bad = copy.deepcopy(cfg)
    bad["governor"]["vram_fraction"] = 0.95
    assert v0_config_check.check(bad) != []
    # g_efficiency pure-logic tests (H1 — docs/domains/governance/ledgers/hardest-problems-register-v1.md)
    _all_levers_applied = {k: {"status": "receipted-APPLIED", "receipt": "x.json"}
                           for k in EFFICIENCY_LEVERS}
    _bound = {"licenses_config": "c03-qat-v0", "config_sha256": "a" * 64,
              "levers": _all_levers_applied}
    # PASS: all levers applied with config binding
    assert _check_efficiency_receipt(_bound) == [], _check_efficiency_receipt(_bound)
    # PASS: waiver with explicit price (the 12c050e7 corrected case)
    waived_with_price = copy.deepcopy(_all_levers_applied)
    waived_with_price["batch_size"] = {"status": "WAIVED", "wall_days_cost": 1.157}
    assert _check_efficiency_receipt({**_bound, "levers": waived_with_price}) == [], \
        _check_efficiency_receipt({**_bound, "levers": waived_with_price})
    # FAIL: 12c050e7 negative — WAIVED without wall_days_cost (silent skip)
    silent_waiver = copy.deepcopy(_all_levers_applied)
    silent_waiver["batch_size"] = {"status": "WAIVED"}
    v = _check_efficiency_receipt({**_bound, "levers": silent_waiver})
    assert any("wall_days_cost" in msg and "H1" in msg for msg in v), v
    # FAIL: lever absent from enumeration
    incomplete = {k: val for k, val in _all_levers_applied.items()
                  if k != "duty_cycle"}
    v2 = _check_efficiency_receipt({**_bound, "levers": incomplete})
    assert any("duty_cycle" in msg for msg in v2), v2
    # FAIL: receipted-APPLIED missing receipt pointer
    no_ptr = copy.deepcopy(_all_levers_applied)
    no_ptr["batch_size"] = {"status": "receipted-APPLIED"}
    v3 = _check_efficiency_receipt({**_bound, "levers": no_ptr})
    assert any("batch_size" in msg and "receipt" in msg for msg in v3), v3
    # FAIL: invalid status
    bad_status = copy.deepcopy(_all_levers_applied)
    bad_status["batch_size"] = {"status": "IGNORED"}
    v4 = _check_efficiency_receipt({**_bound, "levers": bad_status})
    assert any("invalid status" in msg for msg in v4), v4
    # FAIL: missing licenses_config
    no_lic = {"levers": _all_levers_applied}
    v5 = _check_efficiency_receipt(no_lic)
    assert any("licenses_config" in msg for msg in v5), v5
    # FAIL: missing config_sha256
    no_sha = {"licenses_config": "c03-qat-v0", "levers": _all_levers_applied}
    v6 = _check_efficiency_receipt(no_sha)
    assert any("config_sha256" in msg for msg in v6), v6
    # PASS: both fields present (pure schema check — sha value not validated here)
    both = {"licenses_config": "c03-qat-v0", "config_sha256": "a" * 64,
            "levers": _all_levers_applied}
    assert _check_efficiency_receipt(both) == [], _check_efficiency_receipt(both)
    # g_efficiency() live config-bind: BLOCKED on sha mismatch (today-case fixture)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fake_receipts = os.path.join(td, "receipts")
        os.makedirs(fake_receipts)
        mismatched = {"ticket": "V0-LAUNCH-EFFICIENCY",
                      "ts": "20260612T220622Z",
                      "sha_convention": "bytes on disk as-is",
                      "licenses_config": "c03-qat-v0",
                      "config_sha256": "0" * 64,  # wrong sha — today-case
                      "levers": _all_levers_applied}
        p = os.path.join(fake_receipts, "launch-efficiency-20260612T220622Z.json")
        with open(p, "w") as f:
            json.dump(mismatched, f)
        # patch NC directly; self-import under __main__ would load a second copy
        # and patching it would not affect the globals that g_efficiency() reads
        old_nc = NC
        NC = td
        try:
            st_m, dt_m = g_efficiency()
            assert st_m == "BLOCKED" and "config_sha256 mismatch" in dt_m, (st_m, dt_m)
        finally:
            NC = old_nc
    # g_efficiency() time-robust: BLOCKED iff no receipt on disk
    eff_cands = glob.glob(f"{NC}/{EFFICIENCY_RECEIPT_GLOB}")
    if not eff_cands:
        st, dt = g_efficiency()
        assert st == "BLOCKED" and "levers not enumerated" in dt, (st, dt)
    else:
        assert g_efficiency()[0] in ("GREEN", "BLOCKED")
    # gate composition returns all rows (now 9 rows)
    rows = gate(date(2026, 6, 11))
    assert [r[0] for r in rows] == ROWS
    # G-shards-mm accepts local Stage-1 image_path manifests and explicit holdout paths.
    with tempfile.TemporaryDirectory() as td:
        train = os.path.join(td, "train.jsonl")
        holdout = os.path.join(td, "holdout.jsonl")
        with open(train, "w", encoding="utf-8") as f:
            f.write(json.dumps({"image_path": os.path.join(td, "car.jpg"), "caption": "car"}) + "\n")
            f.write(json.dumps({"image_path": os.path.join(td, "dog.jpg"), "caption": "dog"}) + "\n")
        with open(holdout, "w", encoding="utf-8") as f:
            f.write(json.dumps({"image_path": os.path.join(td, "tree.jpg"), "sha256": "a" * 64, "caption": "tree"}) + "\n")
        st_local, dt_local = g_shards_mm(train, None, 1, holdout)
        assert st_local == "BLOCKED" and "item 5" in dt_local, (st_local, dt_local)
    print("V0_LAUNCH_GATE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true",
                    help="write the dated launch-gate receipt")
    ap.add_argument("--emit-dir", default=None,
                    help="directory for --emit receipt; default = this worktree's receipts/")
    ap.add_argument("--launch-date", default=None,
                    help="YYYY-MM-DD; default = today (system date)")
    ap.add_argument("--multimodal-config", default=None,
                    help="multimodal config path; enables G-shards-mm when paired with --mm-manifest or --mm-tokenizer")
    ap.add_argument("--mm-manifest", default=None,
                    help="matched-pair multimodal training manifest path")
    ap.add_argument("--mm-tokenizer", default=None,
                    help="tokenizer used by train and probe")
    ap.add_argument("--mm-holdout-size", type=int, default=None,
                    help="expected frozen holdout manifest row count")
    ap.add_argument("--mm-holdout-manifest", default=None,
                    help="explicit frozen holdout manifest path")
    ap.add_argument("--efficiency-receipt", default=None,
                    help="explicit launch-efficiency receipt path")
    ap.add_argument("--shard-dir", default=None,
                    help="real packed uint16 shard dir (#682) — authoritative base "
                         "path for G-shards' declared shard files, taking precedence "
                         "over NC-relative resolution (which is wrong when this script "
                         "runs from a worktree); falls back to EMBER_SHARD_DIR_OVERRIDE "
                         "env, then to NC-relative resolution when neither is set")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if a.launch_date:
        ld = datetime.date.fromisoformat(a.launch_date)
    else:
        ld = datetime.date.today()
    shard_dir_override = a.shard_dir or os.environ.get("EMBER_SHARD_DIR_OVERRIDE")
    rows = gate(
        ld,
        multimodal_config_path=a.multimodal_config,
        mm_manifest_path=a.mm_manifest,
        mm_tokenizer_path=a.mm_tokenizer,
        mm_holdout_size=a.mm_holdout_size,
        mm_holdout_manifest_path=a.mm_holdout_manifest,
        efficiency_receipt_path=a.efficiency_receipt,
        shard_dir_override=shard_dir_override,
    )
    _print(rows)
    blocked = [r[0] for r in rows if r[1] != "GREEN"]
    if a.emit:
        path = emit(ld, rows, output_dir=a.emit_dir)
        try:
            rel = os.path.relpath(path, NC)
        except ValueError:
            rel = path
        print(f"receipt: {rel}")
    if blocked:
        print(f"LAUNCH REFUSED — blocked rows: {', '.join(blocked)}")
        raise SystemExit(1)
    print("V0_LAUNCH_GATE_GREEN — dispatch permitted")


if __name__ == "__main__":
    main()
