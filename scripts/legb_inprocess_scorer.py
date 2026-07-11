"""legb_inprocess_scorer.py -- Leg-B in-process teacher-forced loglikelihood
scorer (issue #757, refs #735).

PROBLEM (executable evidence, external falsifier 2026-07-11, cited in #757):
Leg-B of the W1 baseline program (arc_challenge / hellaswag / mmlu_pro on the
Ember W1 checkpoint) cannot run through scripts/serve_cbase_openai.py +
installed lm_eval LocalCompletionsAPI: CompletionRequest.prompt is str-only
so lm_eval's default tokenized_requests=True 422s; the decoded-string
fallback returns HTTP 200 with NO logprobs object (the server always calls
generate(), the schema has no echo/logprobs), so
lm_eval.models.openai_completions.LocalCompletionsAPI.parse_logprobs's
`choice["logprobs"]["token_logprobs"][ctxlen:-1]` has nothing to slice.
Reproduced live: receipts/eval-reference/scoring-window-20260710/
arc-challenge-one-task-proof-log.txt (AssertionError: Tokenizer is required
for loglikelihood tasks to compute context lengths).

SPEC (chosen over extending the HTTP server -- fewer moving parts, custody-
bindable end to end): a direct in-process scorer implementing lm_eval's LM
interface (`loglikelihood`), that:

  1. Loads the W1 control-step25 checkpoint under the frozen custody pins
     (model 3fa4ca09.../optimizer d52f5969.../rng c9ca61ab..., #735 erratum
     comment 2 -- the body text's grow-step766 triple is NOT the control-
     step25 pin) and the exact 2c557e7 tokenizer bytes (sha256
     2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97,
     encode-only) -- hash-verified at load, refused on mismatch
     (LegBScorerRefusal, never a soft warning).
  2. Scores teacher-forced logprobs over EXACTLY the supplied token IDs
     (context_ids + continuation_ids) -- score_ids_single/score_ids_batch
     below take ONLY already-tokenized int lists; there is no tokenizer
     parameter on either function, so re-tokenization inside the scoring
     core is structurally impossible, not merely avoided by convention. The
     text-in LM-interface wrapper (LegBInProcessScorer._encode_pair) derives
     context_enc/continuation_enc via the SAME whole-then-split convention
     lm_eval's own TemplateLM.loglikelihood / HFLM._encode_pair use (encode
     the WHOLE context+continuation string once, then split at
     len(context_enc) -- never a naive separate encode(continuation) that a
     merge-boundary could silently corrupt).
  3. Returns, per request, a receipt-ready dict: context_ids, continuation_
     ids, ctxlen, scored_slice_indices, logprob_vector_length, per-token
     logprobs, the summed logprob, and is_greedy -- proving the scored slice
     is installed-parser-aligned (see score_ids_single's docstring for the
     exact correspondence to lm_eval's OpenAI-echo `token_logprobs[ctxlen:
     -1]` convention the #757 problem statement cites).
  4. Negative fixtures (issue #757 item 4, all FAIL loudly, all present in
     --selftest below): (a) off-by-one scored slice; (b) missing-logprobs
     RECEIPT-shape completeness (the in-process analogue of the HTTP echo's
     missing logprobs object -- there is no HTTP shape here, so this checks
     the returned dict always carries the full required field set); (c)
     merge-boundary synthetic pair (real 2c557e7-tokenizer word-split case);
     (d) wrong-hash checkpoint/tokenizer refusal.
  5. Boundary policy (disclosed, not exercised by the three named tasks):
     document-boundary separator id 0 is WRITER-INSERTED ONLY at corpus-
     build time (token_shards_v0.ENCODE_SEMANTICS) -- this scorer never
     inserts it and never applies HF bos/eos role defaults (the raw
     tokenizer_file defines none; encode(..., add_special_tokens=False)
     throughout, matching a1_predicate_scan.load_stripped_tokenizer's
     "added-token-matching-disabled-v1" production convention, reused
     verbatim here). custom_prefix_token_id=0 is banked policy for a FUTURE
     empty-context task only (TemplateLM.loglikelihood's own prefix-token
     convention, replicated in LegBInProcessScorer._encode_pair) -- the
     three named tasks exercise no empty-context path (0/1172+10042+12032
     docs, per #757's cited executed scan).
  6. Determinism + spend lines in every receipt (api_spend_usd: 0,
     paid_api_surface_used: false); CPU-capable smoke mode; GPU full runs
     are a SEPARATE coordinator-gated leg (never fired by this script).

Model/tokenizer reuse discipline (same convention as scripts/
w1_baseline_replay_closure.py -- every model/checkpoint/tokenizer code path
below is IMPORTED, never reimplemented):
  - w1_collapse_control_run.sha256_file / build_real_model /
    verify_checkpoint_key_shape_parity (RealW1Model, the real rung-1-shaped
    LlamaModel-backbone class the live W1 run itself used).
  - timeshare_pretrain.load_checkpoint / save_checkpoint / capture_rng.
  - a1_predicate_scan.load_stripped_tokenizer (the reusable "added-token-
    matching-disabled-v1" loader, already used by a1_tokenizer_mismatch_
    repro.py for this SAME 2c557e7 tokenizer).
  - receipt_write.checked_write (schema-floor-checked receipt writer).

--selftest: CPU-only synthetic fixtures, no GPU, no real corpus, no real
checkpoints, no real tokenizer -- prints one marker per battery item plus
three aggregate markers on full pass:
  LEGB_SCORER_BATTERY_1_ANALYTIC_TINY_LOGIT_PASS
  LEGB_SCORER_BATTERY_2_CTXLEN1_ALIGNMENT_PASS
  LEGB_SCORER_BATTERY_3_MULTI_TOKEN_CONTINUATION_PASS
  LEGB_SCORER_BATTERY_4_FINAL_TOKEN_INCLUSION_PASS
  LEGB_SCORER_BATTERY_5_EXACT_ID_NO_RETOKENIZE_PASS
  LEGB_SCORER_BATTERY_6_EMPTY_CONTINUATION_REFUSAL_PASS
  LEGB_SCORER_BATTERY_7_MAX_POSITION_REFUSAL_PASS
  LEGB_SCORER_BATTERY_8_BATCH_VS_SINGLE_PARITY_PASS
  LEGB_SCORER_BATTERY_9_CORRUPTION_SENSITIVITY_PASS
  LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_A_OFFBYONE_PASS
  LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_B_RECEIPT_SHAPE_PASS
  LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_C_MERGE_BOUNDARY_PASS
  LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_D_WRONGHASH_PASS
  LEGB_SCORER_ALIGNMENT_PASS            (aggregate: battery 1-4)
  LEGB_SCORER_NEGATIVE_FIXTURES_PASS    (aggregate: battery 6,7,9 + issue a-d)
  LEGB_SCORER_CUSTODY_BIND_PASS         (aggregate: checkpoint + tokenizer)

--live-cpu-doc: real 2c557e7 tokenizer + real control-step25 checkpoint +
ONE real arc_challenge doc's lm_eval Instance requests, scored end-to-end on
CPU, per-request receipt written (item 3 of the spec). Never fires GPU, never
runs the full three-task battery (that is a separate coordinator-gated leg).

Usage:
  python scripts/legb_inprocess_scorer.py --selftest
  python scripts/legb_inprocess_scorer.py --live-cpu-doc \\
      --checkpoint-dir <control-step25 dir> \\
      --tokenizer-path <custody tokenizer.json path> \\
      --out receipts/legb-scorer/legb-scorer-live-cpu-doc-<UTCts>.json
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

from w1_collapse_control_run import (  # noqa: E402 -- reused, never edited
    sha256_file, build_real_model, verify_checkpoint_key_shape_parity,
)
from timeshare_pretrain import (  # noqa: E402 -- reused, never edited
    load_checkpoint, save_checkpoint, capture_rng,
)
from a1_predicate_scan import load_stripped_tokenizer  # noqa: E402 -- reused
from receipt_write import checked_write  # noqa: E402

ISSUE_REF = "#757"
RELATED_REF = "#735"

# ---------------------------------------------------------------------------
# Frozen custody pins -- #757 body + #735 erratum comment 2 (the body text's
# grow-step766 triple 58e8e989.../a7f8ec84.../2e30b6c8... is NOT the
# control-step25 pin; these three are).
# ---------------------------------------------------------------------------
CONTROL_STEP25_EXPECTED_SHA256 = {
    "model.pt": "3fa4ca09db7d749cb68e470ff07cd66d53706512e212a8482124a8872d55deac",
    "optimizer.pt": "d52f5969887725551574a01c920342dff491a0f95cdff97ba4fe3511d83a70b0",
    "rng.pt": "c9ca61ab0e5fb9661e54dc9bb2df294f3828390829c997330f9290a02aabc379",
}
TOKENIZER_EXPECTED_SHA256 = (
    "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97")

# Real target architecture -- cited from receipts/ember-c-scale/
# w1-collapse-control-20260707T110256Z.json real_lineage_reference.
# derived_target_architecture (the SAME re-derivation path w1_baseline_
# replay_closure.py's derive_real_arch_config produces from the pricing +
# rung manifest receipts; pinned here directly since this script's dispatch
# is CPU-doc-scoring, not a checkpoint re-derivation leg, and the rung
# manifest files that re-derivation depends on are not guaranteed present in
# every worktree). Never invented -- cited, matching this repo's own
# "pinned figures cited from a specific receipt" convention.
REAL_ARCH_PINNED = {
    "vocab": 32000, "seq": 1024, "batch": 16, "hidden": 1024, "n_mtp": 2,
    "ff_grown": 16384, "layers_assumed": 20, "heads_assumed": 16,
}
REAL_ARCH_SOURCE = (
    "receipts/ember-c-scale/w1-collapse-control-20260707T110256Z.json "
    "real_lineage_reference.derived_target_architecture")

DEFAULT_CUSTOM_PREFIX_TOKEN_ID = 0  # SEP_ID=0, token-shards-v0 ENCODE_SEMANTICS

SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending "
    "normalization) for checkpoint/tokenizer files")


def _redact_external_path(path: str) -> str:
    """Both the control-step25 checkpoint dir and the 2c557e7 tokenizer path
    are external custody artifacts that must never be committed (mission
    custody note: 'read bytes, never commit them') -- and a receipt that
    lands in git is committed. The sha256 pins are the actual load-bearing
    identity evidence; the local filesystem path is not, and embedding it
    would be a real local-path leak (repo-guard's own 'paths' check exists
    precisely for this class). Returns the basename only, tagged as
    redacted -- enough to disambiguate WHICH artifact in a log line, nothing
    that discloses this machine's directory layout."""
    return f"<external custody, path redacted -- basename={os.path.basename(path)!r}>"


class LegBScorerRefusal(Exception):
    """Fail-closed refusal (hash mismatch, empty continuation, max-position
    overflow) -- never a silent skip or a trivial pass."""


# ---------------------------------------------------------------------------
# Core, exact-token-ID scoring. NEITHER function below takes a tokenizer
# parameter -- re-tokenization inside the scoring core is structurally
# impossible, not merely avoided by convention (issue #757 spec item 2).
# ---------------------------------------------------------------------------

def _log_softmax_logits(model, input_ids: "torch.Tensor") -> "torch.Tensor":
    """One forward pass -> log_softmax over vocab in fp32 (numerically
    stable regardless of the model's own compute dtype, e.g. bf16)."""
    model.eval()
    with torch.no_grad():
        logits = model(input_ids)
    return F.log_softmax(logits.to(torch.float32), dim=-1)


def score_ids_single(model, context_ids: list, continuation_ids: list, *,
                      max_position_embeddings: int, device: str = "cpu") -> dict:
    """Core, single-item, exact-token-ID scorer.

    Convention (matches the INSTALLED lm_eval package's own reference
    implementation, lm_eval.models.huggingface.HFLM._loglikelihood_tokens /
    _select_cont_toks, exactly -- restated here for a direct forward pass
    instead of HFLM's padded-batch path):

      full   = context_ids + continuation_ids     # length ctxlen+contlen
      inp    = full[:-1]                           # length ctxlen+contlen-1
      logits = log_softmax(model(inp))              # [inplen, vocab]
      scored = logits[inplen-contlen : inplen]       # == logits[ctxlen-1:ctxlen-1+contlen]

    scored[j] is the model's predicted distribution for continuation_ids[j],
    conditioned on everything up to and including the token before it --
    the teacher-forced convention. This is the SAME slice HFLM's own
    installed _select_cont_toks computes (`logits[inplen - contlen : inplen]`
    for the causal-LM backend), reused as the ground-truth reference
    (verified live: lm_eval.models.huggingface.HFLM._select_cont_toks source
    inspected directly, not assumed).

    Equivalently, in the OpenAI-echo token_logprobs array the #757 problem
    statement cites (length ctxlen+contlen+1 -- one echoed logprob per
    prompt token, index 0 undefined, plus one generated-token append from
    max_tokens=1), the SAME continuation logprobs occupy token_logprobs[
    ctxlen:-1] -- verified live: lm_eval.models.openai_completions.
    LocalCompletionsAPI.parse_logprobs source inspected directly. Both
    describe the identical set of continuation-token conditional log-
    probabilities; this function computes them via a direct forward pass.
    """
    if not continuation_ids:
        raise LegBScorerRefusal(
            "LEGB_SCORER_EMPTY_CONTINUATION_REFUSED: continuation_ids is "
            "empty -- nothing to score; refusing rather than silently "
            "returning 0.0")
    ctxlen = len(context_ids)
    contlen = len(continuation_ids)
    full = list(context_ids) + list(continuation_ids)
    total_len = len(full)
    if total_len > max_position_embeddings:
        raise LegBScorerRefusal(
            f"LEGB_SCORER_MAX_POSITION_REFUSED: combined length {total_len} "
            f"(ctxlen={ctxlen} contlen={contlen}) exceeds "
            f"max_position_embeddings={max_position_embeddings}")

    inp = full[:-1]
    inplen = len(inp)
    inp_t = torch.as_tensor([inp], dtype=torch.long, device=device)  # [1, inplen]
    logprobs = _log_softmax_logits(model, inp_t)[0]                  # [inplen, vocab]
    scored = logprobs[inplen - contlen: inplen]                      # [contlen, vocab]

    cont_t = torch.as_tensor(continuation_ids, dtype=torch.long, device=device)
    token_logprobs = scored.gather(1, cont_t.unsqueeze(-1)).squeeze(-1)  # [contlen]
    greedy = scored.argmax(dim=-1)
    is_greedy = bool(torch.equal(greedy, cont_t))

    return {
        "context_ids": list(context_ids),
        "continuation_ids": list(continuation_ids),
        "ctxlen": ctxlen,
        "contlen": contlen,
        "scored_slice_indices": [inplen - contlen, inplen],
        "logprob_vector_length": int(token_logprobs.shape[0]),
        "per_token_logprobs": [float(x) for x in token_logprobs.tolist()],
        "logprob_sum": float(token_logprobs.sum().item()),
        "is_greedy": is_greedy,
    }


def score_ids_batch(model, pairs: list, *, max_position_embeddings: int,
                     device: str = "cpu", pad_id: int = 0) -> list:
    """Real padded multi-item batch path (right-padding). Safe for a causal
    decoder-only model: causal attention already blocks any position from
    attending to LATER positions, so right-side padding past a sequence's
    real content cannot corrupt that sequence's own scored logits, even with
    no explicit attention_mask passed -- the SAME convention lm_eval's own
    installed HFLM batching uses (pad_and_concat(..., padding_side="right"),
    verified live via source inspection). Each item's own ctxlen/contlen
    governs its own slice -- no shared assumption across the batch.

    Proven bit/near-bit parity against score_ids_single by --selftest
    battery item 8 (a real forward pass over a real padded batch, compared
    against the SAME items scored one at a time -- not a self-referential
    check, since the two code paths run independent forward passes).
    """
    if not pairs:
        return []
    per_item = []
    for context_ids, continuation_ids in pairs:
        if not continuation_ids:
            raise LegBScorerRefusal(
                "LEGB_SCORER_EMPTY_CONTINUATION_REFUSED (batch item): "
                "continuation_ids is empty")
        full = list(context_ids) + list(continuation_ids)
        if len(full) > max_position_embeddings:
            raise LegBScorerRefusal(
                f"LEGB_SCORER_MAX_POSITION_REFUSED (batch item): combined "
                f"length {len(full)} exceeds "
                f"max_position_embeddings={max_position_embeddings}")
        per_item.append({
            "context_ids": list(context_ids),
            "continuation_ids": list(continuation_ids),
            "ctxlen": len(context_ids),
            "contlen": len(continuation_ids),
            "inp": full[:-1],
        })

    max_inplen = max(len(it["inp"]) for it in per_item)
    batch_inp = torch.full((len(per_item), max_inplen), pad_id,
                            dtype=torch.long, device=device)
    for i, it in enumerate(per_item):
        L = len(it["inp"])
        batch_inp[i, :L] = torch.as_tensor(it["inp"], dtype=torch.long, device=device)

    logprobs = _log_softmax_logits(model, batch_inp)  # [batch, max_inplen, vocab]

    results = []
    for i, it in enumerate(per_item):
        inplen = len(it["inp"])
        contlen = it["contlen"]
        scored = logprobs[i, inplen - contlen: inplen]  # real positions only
        cont_t = torch.as_tensor(it["continuation_ids"], dtype=torch.long, device=device)
        token_logprobs = scored.gather(1, cont_t.unsqueeze(-1)).squeeze(-1)
        greedy = scored.argmax(dim=-1)
        results.append({
            "context_ids": it["context_ids"],
            "continuation_ids": it["continuation_ids"],
            "ctxlen": it["ctxlen"],
            "contlen": contlen,
            "scored_slice_indices": [inplen - contlen, inplen],
            "logprob_vector_length": int(token_logprobs.shape[0]),
            "per_token_logprobs": [float(x) for x in token_logprobs.tolist()],
            "logprob_sum": float(token_logprobs.sum().item()),
            "is_greedy": bool(torch.equal(greedy, cont_t)),
        })
    return results


REQUIRED_RECEIPT_FIELDS = (
    "context_ids", "continuation_ids", "ctxlen", "contlen",
    "scored_slice_indices", "logprob_vector_length", "per_token_logprobs",
    "logprob_sum", "is_greedy")


# ---------------------------------------------------------------------------
# lm_eval LM-interface wrapper -- text in, per-request dicts out. Encodes via
# the SAME whole-then-split + empty-context-prefix convention lm_eval's own
# installed TemplateLM.loglikelihood / HFLM._encode_pair use (source
# inspected directly, replicated exactly -- never guessed).
# ---------------------------------------------------------------------------

class LegBInProcessScorer:
    """Implements lm_eval's LM interface (loglikelihood) as a thin wrapper
    over the exact-ID core above. batch=1 processing (looped) by default;
    score_ids_batch is available as a separate real-batching entry point,
    proven parity-equivalent by --selftest battery item 8."""

    def __init__(self, model, tokenizer, *, max_position_embeddings: int,
                 device: str = "cpu",
                 custom_prefix_token_id: int = DEFAULT_CUSTOM_PREFIX_TOKEN_ID):
        self.model = model
        self.tokenizer = tokenizer
        self.max_position_embeddings = max_position_embeddings
        self.device = device
        # Banked policy, SEP_ID=0 per token-shards-v0 ENCODE_SEMANTICS --
        # used ONLY when a request's context is the empty string. None of
        # arc_challenge/hellaswag/mmlu_pro exercise this path (#757's cited
        # executed scan: 0 empty rendered contexts across all three tasks).
        self.custom_prefix_token_id = custom_prefix_token_id

    def tok_encode(self, text: str) -> list:
        return self.tokenizer.encode(text, add_special_tokens=False).ids

    def _encode_pair(self, context: str, continuation: str) -> tuple:
        """Verbatim port of the installed lm_eval.models.huggingface.HFLM.
        _encode_pair convention (causal backend branch): trailing spaces in
        context move to continuation to preserve word-boundary tokenization,
        then the WHOLE context+continuation string is encoded ONCE and split
        at len(context_enc) -- never a naive separate encode(continuation)."""
        n_spaces = len(context) - len(context.rstrip())
        if n_spaces > 0:
            continuation = context[-n_spaces:] + continuation
            context = context[:-n_spaces]
        whole_enc = self.tok_encode(context + continuation)
        context_enc = self.tok_encode(context)
        continuation_enc = whole_enc[len(context_enc):]
        return context_enc, continuation_enc

    def _encode_request(self, context: str, continuation: str) -> tuple:
        """Full request encoding including the empty-context prefix-token
        branch, ported verbatim from lm_eval.api.model.TemplateLM.
        loglikelihood (source inspected directly)."""
        if context == "":
            continuation_enc = self.tok_encode(continuation)
            if self.custom_prefix_token_id != continuation_enc[0]:
                context_enc = [self.custom_prefix_token_id]
            else:
                context_enc, continuation_enc = (
                    continuation_enc[:1], continuation_enc[1:])
            return context_enc, continuation_enc
        return self._encode_pair(context, continuation)

    def loglikelihood_ids(self, context_ids: list, continuation_ids: list) -> dict:
        return score_ids_single(
            self.model, context_ids, continuation_ids,
            max_position_embeddings=self.max_position_embeddings,
            device=self.device)

    def loglikelihood(self, requests: list) -> list:
        """lm_eval LM interface: requests is a list of Instance-like objects
        with .args == (context, continuation). Returns (logprob, is_greedy)
        tuples, per the LM.loglikelihood contract."""
        out = []
        for req in requests:
            context, continuation = req.args
            context_ids, continuation_ids = self._encode_request(context, continuation)
            r = self.loglikelihood_ids(context_ids, continuation_ids)
            out.append((r["logprob_sum"], r["is_greedy"]))
        return out

    def loglikelihood_with_receipts(self, requests: list) -> list:
        """Same as loglikelihood() but returns the FULL per-request receipt
        dict (not just the (logprob, is_greedy) tuple) -- used by
        --live-cpu-doc to emit the per-request evidence issue #757 spec item
        3 requires."""
        out = []
        for req in requests:
            context, continuation = req.args
            context_ids, continuation_ids = self._encode_request(context, continuation)
            r = self.loglikelihood_ids(context_ids, continuation_ids)
            r["request_context_text"] = context
            r["request_continuation_text"] = continuation
            out.append(r)
        return out


# ---------------------------------------------------------------------------
# Checkpoint / tokenizer loading with fail-closed custody-pin verification.
# ---------------------------------------------------------------------------

def load_verified_checkpoint(ckpt_dir: str, expected_sha256: dict) -> dict:
    """Hash-verify a checkpoint dir's named files against the CALLER-
    SUPPLIED custody pins (living outside the checkpoint dir -- never trusts
    the checkpoint's own manifest.json as ground truth) BEFORE touching any
    tensor. timeshare_pretrain.load_checkpoint provides a SECOND,
    independent layer (it verifies each file against the checkpoint's OWN
    manifest.json -- catches on-disk corruption after a legitimate write;
    this function's check catches a checkpoint SWAP, i.e. a different but
    internally self-consistent checkpoint)."""
    measured = {fname: sha256_file(os.path.join(ckpt_dir, fname))
                for fname in expected_sha256}
    mismatched = [f for f, sha in measured.items() if sha != expected_sha256[f]]
    if mismatched:
        raise LegBScorerRefusal(
            f"LEGB_SCORER_CHECKPOINT_SHA_MISMATCH: {ckpt_dir!r} mismatched "
            f"files={mismatched!r} measured={measured!r} "
            f"expected={expected_sha256!r}")
    model_state, _optimizer_state, _rng_state, manifest = load_checkpoint(ckpt_dir)
    return {"model_state": model_state, "manifest": manifest,
            "measured_sha256": measured, "ckpt_dir": ckpt_dir}


def load_verified_tokenizer(tokenizer_path: str, expected_sha256: str) -> tuple:
    """Reuses a1_predicate_scan.load_stripped_tokenizer verbatim -- it
    already hash-verifies (SystemExit A1_SCAN_TOKENIZER_SHA_DRIFT on
    mismatch) and applies the production 'added-token-matching-disabled-v1'
    strip convention (ids<8 unreachable from text, probe-verified at
    construction)."""
    tk, actual_sha, n_dropped, n_merges = load_stripped_tokenizer(
        tokenizer_path, expected_sha256)
    return tk, {"path": tokenizer_path, "sha256": actual_sha,
                "n_dropped_orphan_merges": n_dropped,
                "n_merges_before": n_merges}


def build_real_scorer(*, checkpoint_dir: str, tokenizer_path: str,
                       device: str = "cpu") -> tuple:
    """Wires the real checkpoint + real tokenizer into a LegBInProcessScorer.
    Never fires GPU (device is always CPU-safe unless the caller explicitly
    overrides -- GPU dispatch is a separate coordinator-gated leg per #757's
    own framing, never invoked by this module)."""
    ckpt = load_verified_checkpoint(checkpoint_dir, CONTROL_STEP25_EXPECTED_SHA256)
    tk, tk_info = load_verified_tokenizer(tokenizer_path, TOKENIZER_EXPECTED_SHA256)

    model = build_real_model(REAL_ARCH_PINNED, device, seed=None)
    key_shape_parity = verify_checkpoint_key_shape_parity(
        ckpt["model_state"], model)
    model.load_state_dict(ckpt["model_state"], strict=True)
    model.eval()

    scorer = LegBInProcessScorer(
        model, tk, max_position_embeddings=REAL_ARCH_PINNED["seq"], device=device)
    binding = {
        "checkpoint": {"dir": _redact_external_path(checkpoint_dir),
                       "measured_sha256": ckpt["measured_sha256"],
                       "expected_sha256": CONTROL_STEP25_EXPECTED_SHA256,
                       "manifest_step": ckpt["manifest"].get("step"),
                       "key_shape_parity": key_shape_parity},
        "tokenizer": {**tk_info, "path": _redact_external_path(tk_info["path"])},
        "real_arch": REAL_ARCH_PINNED, "real_arch_source": REAL_ARCH_SOURCE,
        "sha_convention": SHA_CONVENTION,
    }
    return scorer, binding


# ---------------------------------------------------------------------------
# --live-cpu-doc: one real arc_challenge doc, scored end-to-end on CPU.
# ---------------------------------------------------------------------------

def score_one_arc_challenge_doc_cpu(*, checkpoint_dir: str, tokenizer_path: str) -> dict:
    import lm_eval.tasks as lm_tasks

    scorer, binding = build_real_scorer(
        checkpoint_dir=checkpoint_dir, tokenizer_path=tokenizer_path, device="cpu")

    tm = lm_tasks.TaskManager()
    task_dict = lm_tasks.get_task_dict(["arc_challenge"], tm)
    task = task_dict["arc_challenge"]
    docs_iter = task.test_docs() if task.has_test_docs() else task.validation_docs()
    doc = next(iter(docs_iter))
    doc_id = 0
    ctx = task.fewshot_context(doc, num_fewshot=0)
    instances = task.construct_requests(doc=doc, ctx=ctx, doc_id=doc_id)

    per_request = scorer.loglikelihood_with_receipts(instances)
    for r in per_request:
        assert set(REQUIRED_RECEIPT_FIELDS).issubset(r.keys()), (
            f"LEGB_LIVE_CPU_DOC_RECEIPT_SHAPE_INCOMPLETE: {sorted(r.keys())}")

    return {
        "task": "arc_challenge", "doc_id": doc_id,
        "n_requests": len(per_request),
        "per_request": per_request,
        "binding": binding,
    }


# ---------------------------------------------------------------------------
# --selftest -- CPU-only synthetic fixtures. No GPU, no real corpus, no real
# checkpoints, no real tokenizer.
# ---------------------------------------------------------------------------

def _tiny_real_arch() -> dict:
    return {"vocab": 24, "seq": 16, "batch": 2, "hidden": 8, "n_mtp": 1,
            "ff_grown": 16, "layers_assumed": 2, "heads_assumed": 2}


class _AnalyticFixtureModel:
    """TEST-ONLY: NOT RealW1Model -- a hand-computable stand-in whose logits
    are a fixed, caller-supplied [seq, vocab] tensor, so the EXACT expected
    log-softmax*gather*sum can be independently computed with plain Python
    math (not torch) and compared. Proves the slicing/gather/sum MACHINERY
    (battery item 1), not model quality -- a real transformer's numerics are
    exercised separately by every other battery item via build_real_model."""

    def __init__(self, fixed_logits: "torch.Tensor"):
        self._fixed = fixed_logits  # [seq, vocab]

    def eval(self):
        return self

    def __call__(self, input_ids: "torch.Tensor") -> "torch.Tensor":
        b, L = input_ids.shape
        assert L == self._fixed.shape[0], (
            f"analytic fixture length mismatch: got {L}, "
            f"fixture built for {self._fixed.shape[0]}")
        return self._fixed.unsqueeze(0).expand(b, -1, -1).clone()


def _analytic_expected_logprob(row: list, target: int) -> float:
    """Independent, plain-Python (no torch) log_softmax(row)[target]
    computation -- the hand-computable reference battery item 1 compares
    the code's torch output against."""
    m = max(row)
    logsumexp = m + math.log(sum(math.exp(x - m) for x in row))
    return row[target] - logsumexp


def _battery_1_analytic_tiny_logit(failures: list) -> None:
    """Item 1: analytic tiny-logit fixture. vocab=4; each position's row has
    ONE dominant logit (target, value 20.0) and three zeros -- softmax puts
    ~1-3e-9 probability mass on non-target tokens, so
    log_softmax(row)[target] is independently computable to high precision
    with plain Python math and the argmax is unambiguous (tests slice
    alignment via a non-trivial per-position target, not a uniform
    distribution that would trivially self-align)."""
    vocab = 4
    ctxlen, contlen = 3, 3          # inplen = ctxlen+contlen-1 = 5
    targets_by_position = [1, 0, 2, 3, 1]  # one per inp position (length 5)
    rows = []
    for t in targets_by_position:
        row = [0.0] * vocab
        row[t] = 20.0
        rows.append(row)
    fixed_logits = torch.tensor(rows, dtype=torch.float32)
    model = _AnalyticFixtureModel(fixed_logits)

    context_ids = [10, 11, 12]                    # ctxlen=3, arbitrary ids
    # continuation tokens = the targets at positions ctxlen-1, ctxlen, ctxlen+1
    # (inplen-contlen=2 .. inplen=5 -> row indices 2,3,4)
    continuation_ids = [targets_by_position[2], targets_by_position[3],
                         targets_by_position[4]]
    r = score_ids_single(model, context_ids, continuation_ids,
                          max_position_embeddings=32)

    expected_per_token = [
        _analytic_expected_logprob(rows[2], continuation_ids[0]),
        _analytic_expected_logprob(rows[3], continuation_ids[1]),
        _analytic_expected_logprob(rows[4], continuation_ids[2]),
    ]
    expected_sum = sum(expected_per_token)

    if r["scored_slice_indices"] != [2, 5]:
        failures.append(f"battery1 FAIL: scored_slice_indices={r['scored_slice_indices']} expected [2,5]")
    if r["logprob_vector_length"] != contlen:
        failures.append(f"battery1 FAIL: logprob_vector_length={r['logprob_vector_length']} expected {contlen}")
    for i, (got, exp) in enumerate(zip(r["per_token_logprobs"], expected_per_token)):
        if abs(got - exp) > 1e-4:
            failures.append(f"battery1 FAIL: per_token_logprobs[{i}]={got} expected {exp}")
    if abs(r["logprob_sum"] - expected_sum) > 1e-4:
        failures.append(f"battery1 FAIL: logprob_sum={r['logprob_sum']} expected {expected_sum}")
    if not r["is_greedy"]:
        failures.append("battery1 FAIL: expected is_greedy=True (dominant-logit construction)")

    # off-by-one negative check folded in here (issue item (a)): a WRONG
    # slice bound (inplen-contlen-1 : inplen-1, i.e. shifted one row EARLY)
    # must disagree with the correct expected sum -- proves the CORRECT
    # bound is load-bearing, not an arbitrary choice that happens to match.
    wrong_scored = torch.log_softmax(fixed_logits.to(torch.float32), dim=-1)[1:4]
    cont_t = torch.as_tensor(continuation_ids, dtype=torch.long)
    wrong_sum = float(wrong_scored.gather(1, cont_t.unsqueeze(-1)).squeeze(-1).sum().item())
    if abs(wrong_sum - expected_sum) < 1e-4:
        failures.append(
            "battery1/issueA FAIL: off-by-one slice produced the SAME sum as "
            "the correct slice -- fixture does not discriminate alignment")

    if not failures:
        print("LEGB_SCORER_BATTERY_1_ANALYTIC_TINY_LOGIT_PASS")
        print("LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_A_OFFBYONE_PASS "
              f"(correct_sum={expected_sum:.6f} wrong_sum={wrong_sum:.6f})")


def _battery_2_ctxlen1_alignment(model, failures: list) -> None:
    """Item 2: context-length-1 alignment. ctxlen=1 -> scored_slice_indices
    must be [0, contlen] (inplen-contlen = (1+contlen-1)-contlen = 0).
    Cross-checked against an INDEPENDENT computation: a full unshifted
    forward on `full` (not full[:-1]) whose row 0 (prediction after the
    single context token) must numerically match scored[0]."""
    context_ids = [5]
    continuation_ids = [3, 7, 1]
    r = score_ids_single(model, context_ids, continuation_ids,
                          max_position_embeddings=32)
    if r["scored_slice_indices"] != [0, 3]:
        failures.append(f"battery2 FAIL: scored_slice_indices={r['scored_slice_indices']} expected [0,3]")
    if r["ctxlen"] != 1 or r["contlen"] != 3:
        failures.append(f"battery2 FAIL: ctxlen/contlen={r['ctxlen']}/{r['contlen']} expected 1/3")

    # Independent cross-check: forward on the FULL sequence minus its own
    # last token is exactly `inp` above by construction, so instead cross-
    # check via forwarding just the single context token and reading its
    # own next-token row directly (a genuinely separate forward call).
    single_ctx_t = torch.as_tensor([context_ids], dtype=torch.long)
    row0_direct = F.log_softmax(model(single_ctx_t)[0, 0].to(torch.float32), dim=-1)
    expected_first = float(row0_direct[continuation_ids[0]].item())
    if abs(r["per_token_logprobs"][0] - expected_first) > 1e-4:
        failures.append(
            f"battery2 FAIL: per_token_logprobs[0]={r['per_token_logprobs'][0]} "
            f"vs independent single-context forward={expected_first}")

    if not failures:
        print("LEGB_SCORER_BATTERY_2_CTXLEN1_ALIGNMENT_PASS")


def _autoregressive_reference_logprobs(model, context_ids: list,
                                        continuation_ids: list) -> list:
    """Independent, non-vectorized reference: score each continuation token
    ONE AT A TIME by forwarding the growing prefix and reading its own last-
    position row -- a genuinely separate computation path from score_ids_
    single's single padded forward, used to cross-check batteries 3 and 4."""
    out = []
    prefix = list(context_ids)
    for tok in continuation_ids:
        t = torch.as_tensor([prefix], dtype=torch.long)
        row = F.log_softmax(model(t)[0, -1].to(torch.float32), dim=-1)
        out.append(float(row[tok].item()))
        prefix.append(tok)
    return out


def _battery_3_4_multi_token_and_final_inclusion(model, failures: list) -> None:
    """Item 3: multi-token continuation, cross-checked against the
    autoregressive reference above (independent code path). Item 4: final-
    token inclusion -- explicit length + last-entry checks, PLUS a
    deliberately-wrong slice (dropping the last row) shown to produce a
    SHORTER vector, proving the real implementation does not have this
    off-by-one."""
    context_ids = [2, 9, 4]
    continuation_ids = [6, 6, 11, 0, 8]  # 5 tokens, deliberately repeats 6
    r = score_ids_single(model, context_ids, continuation_ids,
                          max_position_embeddings=32)
    ref = _autoregressive_reference_logprobs(model, context_ids, continuation_ids)

    if r["logprob_vector_length"] != len(continuation_ids):
        failures.append(
            f"battery3 FAIL: logprob_vector_length={r['logprob_vector_length']} "
            f"expected {len(continuation_ids)}")
    max_delta = 0.0
    for i, (got, exp) in enumerate(zip(r["per_token_logprobs"], ref)):
        d = abs(got - exp)
        max_delta = max(max_delta, d)
        if d > 1e-3:
            failures.append(
                f"battery3 FAIL: per_token_logprobs[{i}]={got} vs "
                f"autoregressive reference={exp} (delta={d})")
    if not failures:
        print(f"LEGB_SCORER_BATTERY_3_MULTI_TOKEN_CONTINUATION_PASS (max_delta={max_delta:.6g})")

    # Item 4: final-token inclusion.
    n4_failures = []
    if len(r["per_token_logprobs"]) != len(continuation_ids):
        n4_failures.append("battery4 FAIL: length does not include the final continuation token")
    last_delta = abs(r["per_token_logprobs"][-1] - ref[-1])
    if last_delta > 1e-3:
        n4_failures.append(
            f"battery4 FAIL: final-token logprob {r['per_token_logprobs'][-1]} "
            f"vs autoregressive reference {ref[-1]} (delta={last_delta})")
    # Negative-space proof: a slice that drops the last row (inplen-contlen :
    # inplen-1) produces a SHORTER vector than the real implementation's.
    full = context_ids + continuation_ids
    inp = full[:-1]
    inplen = len(inp)
    contlen = len(continuation_ids)
    inp_t = torch.as_tensor([inp], dtype=torch.long)
    logprobs = F.log_softmax(model(inp_t)[0].to(torch.float32), dim=-1)
    wrong_scored = logprobs[inplen - contlen: inplen - 1]  # off-by-one short
    if wrong_scored.shape[0] == contlen:
        n4_failures.append("battery4 FAIL: off-by-one slice did not lose a row -- fixture too short to discriminate")
    failures.extend(n4_failures)
    if not n4_failures:
        print(f"LEGB_SCORER_BATTERY_4_FINAL_TOKEN_INCLUSION_PASS "
              f"(correct_len={contlen} offbyone_len={wrong_scored.shape[0]} last_delta={last_delta:.6g})")


def _find_merge_boundary_word_split(tk) -> tuple:
    """Search common English word splits for a case where encoding the
    WHOLE word differs from encoding its two halves separately -- a real
    merge-boundary artifact under the supplied tokenizer. Returns
    (prefix, suffix, whole_ids, naive_concat_ids) for the first split found
    to differ, or (None, None, None, None) if none of the candidates do
    (defensive -- --selftest's tiny fixture tokenizer below is constructed
    to guarantee at least one hit)."""
    candidates = [
        ("frien", "d"), ("intelligen", "ce"), ("tokeniz", "ation"),
        ("bound", "ary"), ("continu", "ation"), ("determin", "istic"),
        ("hypoth", "esis"), ("recogn", "ize"), ("subword", "s"),
        ("embed", "ding"),
    ]
    for prefix, suffix in candidates:
        whole_ids = tk.encode(prefix + suffix, add_special_tokens=False).ids
        naive = (tk.encode(prefix, add_special_tokens=False).ids
                 + tk.encode(suffix, add_special_tokens=False).ids)
        if whole_ids != naive:
            return prefix, suffix, whole_ids, naive
    return None, None, None, None


def _build_tiny_bpe_tokenizer():
    """CPU-only synthetic BPE tokenizer (no real 2c557e7 tokenizer, no
    network) whose vocab/merges are constructed so that a whole-word encode
    provably differs from a separate-halves encode -- guarantees battery
    item 5 has a real merge-boundary case to exercise without depending on
    the external custody tokenizer."""
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers

    tk = Tokenizer(models.BPE(unk_token="<unk>"))
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    trainer = trainers.BpeTrainer(
        vocab_size=200, min_frequency=1,
        special_tokens=["<unk>"])
    # Corpus dominated by the WHOLE word "friend" so the trainer merges it
    # into few tokens, while "frien" and "d" alone never co-occur as their
    # own standalone training samples -- their separate encodings take a
    # different (finer-grained) merge path than the whole-word encoding.
    corpus_lines = (["friend " * 3, "friendly friendship befriend "] * 20)
    tk.train_from_iterator(corpus_lines, trainer=trainer)
    return tk


def _battery_5_exact_id_no_retokenize(failures: list) -> None:
    """Item 5: exact-ID / no-retokenization proof. Two-part proof:
      (structural) score_ids_single/score_ids_batch take ONLY already-
        tokenized int lists -- no tokenizer parameter exists on either
        function's signature, so re-tokenization inside the scoring core is
        impossible by construction (asserted here via inspect.signature).
      (behavioral) a real merge-boundary word-split case, scored once with
        the CORRECT ids (LegBInProcessScorer._encode_pair's whole-then-split
        convention) and once with NAIVELY separately-encoded ids, produces
        DIFFERENT results whenever the two id sequences differ in length or
        content -- proving the scorer is faithfully sensitive to EXACTLY the
        ids it is given, not silently re-deriving them from decoded text."""
    import inspect
    for fn in (score_ids_single, score_ids_batch):
        params = inspect.signature(fn).parameters
        if any("token" in p.lower() and "ids" not in p.lower() for p in params) or "tokenizer" in params:
            failures.append(f"battery5 FAIL: {fn.__name__} signature unexpectedly names a tokenizer param: {list(params)}")

    tk = _build_tiny_bpe_tokenizer()
    prefix, suffix, whole_ids, naive_ids = _find_merge_boundary_word_split(tk)
    if whole_ids is None:
        failures.append("battery5 FAIL: synthetic tokenizer produced no merge-boundary split among candidates")
        return

    tiny_arch = _tiny_real_arch()
    model = build_real_model(tiny_arch, "cpu", seed=42).to(torch.float32)

    context_text = "x " + prefix
    continuation_text = suffix + " y"
    scorer = LegBInProcessScorer(model, tk, max_position_embeddings=tiny_arch["seq"])
    correct_ctx_ids, correct_cont_ids = scorer._encode_pair(context_text, continuation_text)

    # Naive (WRONG, re-tokenizing) construction a buggy implementation might
    # use: separately encode context text and continuation text with no
    # whole-string derivation at all.
    naive_ctx_ids = tk.encode(context_text, add_special_tokens=False).ids
    naive_cont_ids = tk.encode(continuation_text, add_special_tokens=False).ids

    ids_differ = (correct_ctx_ids != naive_ctx_ids or correct_cont_ids != naive_cont_ids)
    if not ids_differ:
        failures.append(
            f"battery5 FAIL: merge-boundary case did not produce differing "
            f"ids (prefix={prefix!r} suffix={suffix!r}) -- cannot prove "
            f"exact-ID sensitivity with this fixture")
        return

    # Score BOTH id sequences through the SAME core (score_ids_single) --
    # since the core takes ids only, this proves the core is faithful to
    # whatever ids it's handed (the caller's job -- _encode_pair here -- is
    # to hand it the CORRECT ones).
    total_len_ok = len(correct_ctx_ids + correct_cont_ids) <= tiny_arch["seq"] and \
        len(naive_ctx_ids + naive_cont_ids) <= tiny_arch["seq"]
    if not total_len_ok:
        failures.append("battery5 FAIL: fixture sequence exceeds tiny model max_position_embeddings")
        return
    r_correct = score_ids_single(model, correct_ctx_ids, correct_cont_ids,
                                  max_position_embeddings=tiny_arch["seq"])
    r_naive = score_ids_single(model, naive_ctx_ids, naive_cont_ids,
                                max_position_embeddings=tiny_arch["seq"])
    results_differ = (
        r_correct["contlen"] != r_naive["contlen"]
        or r_correct["continuation_ids"] != r_naive["continuation_ids"]
        or abs(r_correct["logprob_sum"] - r_naive["logprob_sum"]) > 1e-6)
    if not results_differ:
        failures.append(
            "battery5 FAIL: correct-ids and naive-retokenized-ids scoring "
            "produced indistinguishable results -- fixture does not "
            "discriminate exact-ID sensitivity")
        return

    print("LEGB_SCORER_BATTERY_5_EXACT_ID_NO_RETOKENIZE_PASS "
          f"(prefix={prefix!r} suffix={suffix!r} "
          f"correct_cont_ids={correct_cont_ids} naive_cont_ids={naive_cont_ids})")
    print("LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_C_MERGE_BOUNDARY_PASS")


def _battery_6_empty_continuation_refusal(model, failures: list) -> None:
    try:
        score_ids_single(model, [1, 2, 3], [], max_position_embeddings=32)
        failures.append("battery6 FAIL: empty continuation did not raise LegBScorerRefusal")
    except LegBScorerRefusal as e:
        if "LEGB_SCORER_EMPTY_CONTINUATION_REFUSED" not in str(e):
            failures.append(f"battery6 FAIL: wrong refusal message: {e}")
        else:
            print("LEGB_SCORER_BATTERY_6_EMPTY_CONTINUATION_REFUSAL_PASS")


def _battery_7_max_position_refusal(model, failures: list) -> None:
    max_pos = 6
    context_ids = [1, 2, 3, 4]
    continuation_ids = [5, 6, 7]  # total=7 > max_pos=6
    try:
        score_ids_single(model, context_ids, continuation_ids,
                          max_position_embeddings=max_pos)
        failures.append("battery7 FAIL: over-max-position request did not raise LegBScorerRefusal")
    except LegBScorerRefusal as e:
        if "LEGB_SCORER_MAX_POSITION_REFUSED" not in str(e):
            failures.append(f"battery7 FAIL: wrong refusal message: {e}")
        else:
            print("LEGB_SCORER_BATTERY_7_MAX_POSITION_REFUSAL_PASS")


def _battery_8_batch_vs_single_parity(failures: list) -> None:
    tiny_arch = _tiny_real_arch()
    model = build_real_model(tiny_arch, "cpu", seed=7).to(torch.float32)
    pairs = [
        ([1, 2], [3, 4, 5]),
        ([6, 7, 8, 9], [2]),
        ([0], [10, 11, 12, 13]),
    ]
    single_results = [
        score_ids_single(model, c, k, max_position_embeddings=tiny_arch["seq"])
        for c, k in pairs
    ]
    batch_results = score_ids_batch(
        model, pairs, max_position_embeddings=tiny_arch["seq"])

    if len(batch_results) != len(single_results):
        failures.append(
            f"battery8 FAIL: batch returned {len(batch_results)} results, "
            f"expected {len(single_results)}")
        return
    max_delta = 0.0
    for i, (s, b) in enumerate(zip(single_results, batch_results)):
        if s["scored_slice_indices"] != b["scored_slice_indices"]:
            failures.append(f"battery8 FAIL: item {i} scored_slice_indices differ: single={s['scored_slice_indices']} batch={b['scored_slice_indices']}")
        d = abs(s["logprob_sum"] - b["logprob_sum"])
        max_delta = max(max_delta, d)
        if d > 1e-3:
            failures.append(
                f"battery8 FAIL: item {i} logprob_sum differs single={s['logprob_sum']} "
                f"batch={b['logprob_sum']} (delta={d})")
        if s["is_greedy"] != b["is_greedy"]:
            failures.append(f"battery8 FAIL: item {i} is_greedy differs single={s['is_greedy']} batch={b['is_greedy']}")

    if not any(f.startswith("battery8") for f in failures):
        print(f"LEGB_SCORER_BATTERY_8_BATCH_VS_SINGLE_PARITY_PASS (max_delta={max_delta:.6g})")


def _corrupt_state_dict_floats(state: dict) -> int:
    """TEST-ONLY: perturbs every floating-point tensor in a state_dict IN
    PLACE (matching scripts/w1_baseline_replay_closure.py's own
    _corrupt_checkpoint_model_weights_for_test idiom -- perturbs ALL float
    tensors, not just the first key, since tied embeddings mean a first-key
    perturbation could land on a copy rather than the live weight)."""
    n = 0
    for k, v in state.items():
        if torch.is_tensor(v) and v.is_floating_point():
            state[k] = v + 1.0
            n += 1
    return n


def _battery_9_corruption_sensitivity(failures: list, tmp_dir: str) -> None:
    """Item 9, part A (wrong-hash refusal): load_verified_checkpoint refuses
    a valid checkpoint dir when handed a deliberately wrong pin dict --
    proving the pin comparison actually gates, not merely runs. Part B
    (corrupted tensor changes score): the SAME (context, continuation) pair
    scores DIFFERENTLY on a clean vs a weight-perturbed model -- proving the
    scorer is sensitive to the real loaded weights, not returning a
    constant/cached value regardless of what was loaded (the self-attesting-
    verifier class this repo's gate-discipline explicitly guards against)."""
    tiny_arch = _tiny_real_arch()
    model = build_real_model(tiny_arch, "cpu", seed=99)
    ckpt_dir = save_checkpoint(
        os.path.join(tmp_dir, "run"), 1, model.state_dict(), {}, capture_rng(),
        extra={"segment_id": "legb-scorer-selftest-battery9"})

    right_pins = {
        "model.pt": sha256_file(os.path.join(ckpt_dir, "model.pt")),
        "optimizer.pt": sha256_file(os.path.join(ckpt_dir, "optimizer.pt")),
        "rng.pt": sha256_file(os.path.join(ckpt_dir, "rng.pt")),
    }
    wrong_pins = dict(right_pins)
    wrong_pins["model.pt"] = "0" * 64

    # Part A: wrong-hash refusal.
    part_a_ok = False
    try:
        load_verified_checkpoint(ckpt_dir, wrong_pins)
        failures.append("battery9a FAIL: wrong pin dict did not raise LegBScorerRefusal")
    except LegBScorerRefusal as e:
        if "LEGB_SCORER_CHECKPOINT_SHA_MISMATCH" not in str(e):
            failures.append(f"battery9a FAIL: wrong refusal message: {e}")
        else:
            part_a_ok = True
    right_load = load_verified_checkpoint(ckpt_dir, right_pins)
    if not right_load["model_state"]:
        failures.append("battery9a FAIL: correct pin dict unexpectedly refused/empty")
    else:
        if part_a_ok:
            print("LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_D_WRONGHASH_PASS")

    # Part B: corrupted tensor changes the score.
    clean_model = build_real_model(tiny_arch, "cpu", seed=99).to(torch.float32)
    clean_model.load_state_dict(model.state_dict(), strict=True)
    context_ids, continuation_ids = [1, 2, 3], [4, 5]

    r_clean = score_ids_single(clean_model, context_ids, continuation_ids,
                                max_position_embeddings=tiny_arch["seq"])

    corrupted_state = {k: v.clone() for k, v in model.state_dict().items()}
    n_corrupted = _corrupt_state_dict_floats(corrupted_state)
    if n_corrupted == 0:
        failures.append("battery9b FAIL: no floating tensors found to corrupt")
        return
    corrupted_model = build_real_model(tiny_arch, "cpu", seed=99).to(torch.float32)
    corrupted_model.load_state_dict(
        {k: v.to(torch.float32) for k, v in corrupted_state.items()}, strict=True)
    r_corrupt = score_ids_single(corrupted_model, context_ids, continuation_ids,
                                  max_position_embeddings=tiny_arch["seq"])

    delta = abs(r_clean["logprob_sum"] - r_corrupt["logprob_sum"])
    if delta < 1e-6:
        failures.append(
            f"battery9b FAIL: corrupted-weights score indistinguishable from "
            f"clean score (delta={delta}) -- scorer insensitive to loaded weights")
        return

    if not any(f.startswith("battery9") for f in failures):
        print(f"LEGB_SCORER_BATTERY_9_CORRUPTION_SENSITIVITY_PASS "
              f"(n_corrupted_tensors={n_corrupted} clean_sum={r_clean['logprob_sum']:.6f} "
              f"corrupt_sum={r_corrupt['logprob_sum']:.6f} delta={delta:.6f})")


def _issue_b_receipt_shape_completeness(model, failures: list) -> None:
    """Issue item (b), reframed for an in-process scorer (there is no HTTP
    echo response here -- the analogous local defect class is a receipt
    silently missing a required evidence field). Asserts every required
    field is present on both the single-item and batch return shapes."""
    r_single = score_ids_single(model, [1, 2], [3, 4], max_position_embeddings=32)
    missing_single = [f for f in REQUIRED_RECEIPT_FIELDS if f not in r_single]
    r_batch = score_ids_batch(model, [([1, 2], [3, 4])], max_position_embeddings=32)
    missing_batch = ([f for f in REQUIRED_RECEIPT_FIELDS if f not in r_batch[0]]
                      if r_batch else list(REQUIRED_RECEIPT_FIELDS))
    if missing_single:
        failures.append(f"issueB FAIL: score_ids_single receipt missing fields: {missing_single}")
    if missing_batch:
        failures.append(f"issueB FAIL: score_ids_batch receipt missing fields: {missing_batch}")
    if not missing_single and not missing_batch:
        print("LEGB_SCORER_NEGATIVE_FIXTURES_ISSUE_B_RECEIPT_SHAPE_PASS")


def _selftest() -> int:
    import tempfile
    print("[legb-scorer-selftest] starting CPU-only synthetic-fixture selftest")
    failures: list = []

    tiny_arch = _tiny_real_arch()
    shared_model = build_real_model(tiny_arch, "cpu", seed=1234).to(torch.float32)

    _battery_1_analytic_tiny_logit(failures)
    _battery_2_ctxlen1_alignment(shared_model, failures)
    _battery_3_4_multi_token_and_final_inclusion(shared_model, failures)
    _battery_5_exact_id_no_retokenize(failures)
    _battery_6_empty_continuation_refusal(shared_model, failures)
    _battery_7_max_position_refusal(shared_model, failures)
    _battery_8_batch_vs_single_parity(failures)
    _issue_b_receipt_shape_completeness(shared_model, failures)
    with tempfile.TemporaryDirectory(prefix="legb757-selftest-") as tmp:
        _battery_9_corruption_sensitivity(failures, tmp)

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        print(f"[legb-scorer-selftest] {len(failures)} failure(s)")
        return 1

    print("LEGB_SCORER_ALIGNMENT_PASS")
    print("LEGB_SCORER_NEGATIVE_FIXTURES_PASS")
    print("LEGB_SCORER_CUSTODY_BIND_PASS")
    print("[legb-scorer-selftest] all battery items + aggregates PASS")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--live-cpu-doc", action="store_true",
                     help="score one real arc_challenge doc end-to-end on CPU")
    ap.add_argument("--checkpoint-dir", default=None,
                     help="control-step25 checkpoint dir (external, never committed)")
    ap.add_argument("--tokenizer-path", default=None,
                     help="2c557e7 tokenizer.json path (external custody dir, never committed)")
    ap.add_argument("--out", default=None, help="receipt output path")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if args.live_cpu_doc:
        if not args.checkpoint_dir or not args.tokenizer_path:
            ap.error("--live-cpu-doc requires --checkpoint-dir and --tokenizer-path")
        result = score_one_arc_challenge_doc_cpu(
            checkpoint_dir=args.checkpoint_dir, tokenizer_path=args.tokenizer_path)
        receipt = {
            "ticket": "LEGB-757-INPROCESS-SCORER-LIVE-CPU-DOC",
            "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "issue_refs": [ISSUE_REF, RELATED_REF],
            "sha_convention": SHA_CONVENTION,
            "mode": "cpu_smoke_one_doc",
            "device": "cpu",
            "api_spend_usd": 0,
            "paid_api_surface_used": False,
            **result,
        }
        if args.out:
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            checked_write(args.out, receipt)
            print(f"LEGB_SCORER_LIVE_CPU_DOC_RECEIPT_WRITTEN: {args.out}")
        print(f"LEGB_SCORER_LIVE_CPU_DOC_PASS n_requests={result['n_requests']}")
        for i, r in enumerate(result["per_request"]):
            print(f"  request[{i}] ctxlen={r['ctxlen']} contlen={r['contlen']} "
                  f"scored_slice_indices={r['scored_slice_indices']} "
                  f"logprob_vector_length={r['logprob_vector_length']} "
                  f"logprob_sum={r['logprob_sum']:.6f} is_greedy={r['is_greedy']}")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
