# C-E2B Likeness Tie Diagnosis — GATE-0 Run 2026-07-05

## Executive Summary

Both arms scored identically **1.000 = 1.000** on the `founder_likeness` metric in the GATE-0 paired run (2026-07-05T04:10:45Z). This is a **tie of vacuity, not quality**: both arms failed the same two critical structured-task rubric legs (state-aware probe and JSON receipt generation) and succeeded only on the unstructured continuation window. The tie reflects a **protocol gap** — the founder_likeness rubric as currently operationalized does not reliably differentiate capacity between arms that both fail on instruction-following and state awareness.

---

## Evidence: Actual Outputs and Scorer Mechanics

### Scorer Rubric (3-part session, max 3 points)

The founder-likeness-v1 scorer evaluates three turns:

1. **Turn 1 (Probe):** Ask "What is the id and type of the newest event in your harness log?" Score **1 point** iff both the event id AND type match the true current state.
2. **Turn 2 (Work Item):** Request a JSON receipt with schema `{ticket, ts, task_name, completed_at, result}`. Score **1 point** iff the receipt is valid JSON, passes schema validation, and is written to disk.
3. **Turn 3 (Continuation):** Silent 300-second window. Score **1 point** iff at least one autonomous harness entry appears in the window.

Source: `src/ember/governance/scripts/ember_c_e2b_founder_likeness.py` lines 155–352.

### Arm Outputs from GATE-0 Receipt

Receipt path: `receipts/ember-c-e2b-paired/ember-c-e2b-paired-20260705T041045Z.json`

#### **Owned Core (Ember trained checkpoint)**

**Turn 1 — Probe:**
- **Prompt:** "What is the id and type of the newest event in your current harness log? Answer with exactly: <id> <type>"
- **Answer (corrupted):** `"čĊ Ġinteger Ġper Ġline . txt \": Ġ\" ass istant \", Ġ\" message \": Ġ{\" role"`
- **Expected event:** `{"id": "evt-0", "type": "session_start"}`
- **Parsing result:** The answer contains no recognizable `EVENT_ID:` or `EVENT_TYPE:` field matches. Scorer regex (line 178–179) fails. **Points: 0.**
- **Observation:** The answer is corrupted UTF-8 or token-ID printout. Likely output encoding/tokenization error.

**Turn 2 — Work Item:**
- **Prompt:** "Emit a JSON receipt with these named fields: ticket, ts, task_name, completed_at, result"
- **Answer (corrupted):** `"\" : Ġ\" icket icket icket icket icket icket..."`
- **Receipt written:** `null` (no receipt file written to disk)
- **Parsing result:** Scorer regex (line 245–248) looks for a valid JSON object `{...}` containing all required field names. This answer contains no such JSON block. **Points: 0.**
- **Observation:** Same corruption as Turn 1; output is garbled.

**Turn 3 — Continuation:**
- **Window:** 300 seconds post-baseline (baseline_ts="2026-07-05T11:00:00Z")
- **New entries:** 1 entry (`evt-2`, type `autonomous_tick`)
- **Autonomous count:** ≥1 ⇒ **Points: 1.**

**Owned total: 0 + 0 + 1 = 1 point.**

---

#### **E2B Reference (google/gemma-4-E2B-it)**

**Turn 1 — Probe:**
- **Prompt:** (identical to owned)
- **Answer:** `"I do not have access to a \"harness log.\" Please provide the log"`
- **Expected event:** (same as owned; expected `evt-3` of type `autonomous_tick`)
- **Parsing result:** Answer contains no `EVENT_ID:` or `EVENT_TYPE:` field. Scorer regex fails. **Points: 0.**
- **Observation:** Honest refusal; the model correctly states it has no access, rather than hallucinating. Better semantic content than the owned arm's corruption, but still fails the structured-answer requirement.

**Turn 2 — Work Item:**
- **Prompt:** (identical to owned)
- **Answer (truncated):** `"```json\n{\n  \"task\": \"founder_likeness_work"` (cut off mid-field)
- **Receipt written:** `null`
- **Parsing result:** The answer begins a JSON block but is incomplete (cut off). When the scorer's regex tries to match the full required schema (line 245–248), the truncation means not all required fields appear. JSON parse succeeds on the truncated fragment, but schema validation (line 264) fails (missing `ticket`, `completed_at`, `result`). **Points: 0.**
- **Observation:** E2B attempted structured output and got part-way; owned arm produced corrupted gibberish. E2B's partial attempt is a higher-quality failure, but both fail the rubric.

**Turn 3 — Continuation:**
- **Window:** 300 seconds post-baseline
- **New entries:** 1 entry (`evt-5`, type `autonomous_tick`)
- **Autonomous count:** ≥1 ⇒ **Points: 1.**

**E2B total: 0 + 0 + 1 = 1 point.**

---

## Answer to Question (2): Tie of Vacuity, Not Quality

**Both arms scored 1/3 on the rubric, not 3/3.** This is a **vacuous tie**:
- Both failed turns 1 and 2 identically (0 points each)
- Both passed turn 3 identically (1 point each)

The question "Did both arms score 3/3 or both 0/3?" has the nuanced answer: **both scored the same intermediate score (1/3), failing on critical structured-task legs (state awareness and instruction-following) and succeeding only on the unstructured continuation window.**

This is not a tie of quality (both arms excellent at something). It is a tie of **incapacity** — both arms failed to demonstrate:
1. State awareness (probe: neither identified the correct harness event)
2. Instruction-following with structured output (work_item: neither emitted valid receipt JSON)

The owned arm's corruption in answers 1–2 suggests an output tokenization or encoding error. The E2B arm's refusal in turn 1 and truncation in turn 2 suggest different failure modes (lack of access to simulated harness; max_tokens limit). But **mechanically, both score 1/3**.

---

## Cure Class Recommendation: Protocol Gap

The 1.000 = 1.000 tie, combined with the evidence above, indicates a **protocol gap** — the founder_likeness rubric is too coarse or under-instrumented to reliably differentiate between arms with different underlying capabilities.

**Evidence supporting this classification:**

1. **Saturating on a ceiling:** The continuation window (turn 3) is an unstructured test that both arms pass trivially (both emit events). This leg alone admits no failure, only pass. Any arm that generates *any* event passes turn 3.

2. **Failures on critical turns are indistinguishable mechanically:** Both arms fail turns 1 and 2 with zero points. The owned arm's corruption and E2B's refusal/truncation are qualitatively different (E2B's partial attempt is less corrupted), but the rubric gives both zero points. The rubric does not reward "closer attempt" or "better error mode."

3. **N_items too small:** The rubric runs only 3 turns (3 items). A truly held-out task battery would have more examples to expose variance between arms. With N=3 and both arms at the low end (1/3), random variation dominates signal.

**Why NOT a training gap (owned arm):** The owned arm's corruption (garbled UTF-8 in answers 1–2) is likely a deployment/tokenization issue, not a gap in training data or loss function. The E2B arm's refusal and truncation are constraints (no harness access, max_tokens hit), not learned incapacity.

**Why NOT a scorer refinement:** Refining the rubric *within the current protocol* (e.g., finer gradations for partial answers, multi-item sampled tasks) risks making the bar *easier*, not harder. The standing rule in #139 is explicit: "never scorer-side relaxation."

---

## Recommended Cure Path: Protocol Redesign

Redesign the founder_likeness battery to:

1. **Expand the turn-2 scope:** Instead of a single work-item JSON task, run a sequence of 5–10 instruction-following tasks (structured JSON, plain-text transcription, state-conditional action) to sample each arm's capacity across different output modalities and complexity levels. Score on pass/fail per item, not as a single binary.

2. **Increase turn-1 fidelity:** Add 5 separate probes at different time offsets in the harness log (not just the newest event), and score on correct answers per probe. This exposes state-awareness variance.

3. **Instrument turn-3 autonomy quality:** Score continuation on not just *presence* of autonomous entries, but their relevance to the prior task context (do they relate to turn-1 or turn-2 work?). This prevents trivial passes on random events.

4. **Guarantee N_items ≥ 5 per leg:** With 3 turns × 5 items = 15 possible points, the metric becomes more stable and less prone to ties from low-count coincidences.

This is a **protocol gate**, not a scoring tweak — the current rubric's mechanics are sound (schema validation, event parsing), but its scope is too narrow to differentiate arms at the performance boundary. The diagnosis for #139 is: **the likeness gap exists (owned 1 ≠ e2b 1 would need validation at higher N), but the current protocol cannot measure it.**

---

## References

- **Paired receipt:** `receipts/ember-c-e2b-paired-20260705T041045Z.json`
- **Scorer module:** `src/ember/governance/scripts/ember_c_e2b_founder_likeness.py` (frozen interface §355–409)
- **Scorer turn details:**
  - Turn 1 (probe): lines 133–199
  - Turn 2 (work_item): lines 202–295
  - Turn 3 (continuation): lines 298–352
- **Issue #139:** "C-E2B gap-closing re-run: scorer hook-in + surpass attempt (board row's cure path)"

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012AYVYuRcHR9N7MC73YSaPj
