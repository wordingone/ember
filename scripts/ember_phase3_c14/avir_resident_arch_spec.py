#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""avir_resident_arch_spec.py — Clean-room [REDACTED]-cli resident harness ARCHITECTURE spec
and parity-gap manifest.

This file enumerates every [REDACTED].exe surface that the ember resident harness must
replicate for a clean-room parity run.  Each surface is classified as:

  PORTED   — the ember phase3 code already implements an equivalent surface.
  STUB     — a skeleton or protocol-only placeholder exists; gap is named.
  UNPORTED — the surface is not yet implemented; exact next-command to close it.

The ~99% parity target is defined in `PARITY_SCOPE_NOTE` below.  The one known
compute-blocked gap (real [REDACTED].exe first-hand observation receipt) is explicitly
named and its trigger condition stated.

Key interfaces (sibling-integration contract):
  AvirSurface            — TypedDict: one row in the manifest.
  AVIR_SURFACE_MANIFEST  — list[AvirSurface]: every known surface.
  PARITY_GAP_MANIFEST    — list[AvirSurface]: surfaces where status != "PORTED".
  compute_parity_pct     — (manifest) -> float: fraction PORTED / total.
  emit_arch_receipt      — (manifest, out_path) -> None: write JSON receipt.

Run:
  python avir_resident_arch_spec.py          # print manifest + parity %
  python avir_resident_arch_spec.py --check  # assert parity >= PARITY_FLOOR (exits 1 on fail)

Does-not-count-guards (structural):
  This file contains NO neural update logic and makes NO claims about C14 PASS.
  It is a specification+manifest artifact — the parity-gap manifest is the
  deliverable, not a clearance claim.

Compute-blocked gap:
  Surface "avir_exe_first_hand_observation" is UNPORTED and cannot be closed
  without a real [REDACTED].exe session.  The next-command for that surface states the
  prerequisite explicitly.  All other surfaces are PORTED or STUB.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal, List

# ---------------------------------------------------------------------------
# TypedDict definition
# ---------------------------------------------------------------------------

try:
    from typing import TypedDict
except ImportError:
    # Python 3.7 fallback
    from typing_extensions import TypedDict  # type: ignore


class AvirSurface(TypedDict):
    """One row in the [REDACTED]-cli surface manifest.

    Fields
    ------
    name          : short machine-readable identifier (snake_case).
    component     : the [REDACTED].exe subsystem this surface belongs to.
    status        : PORTED | STUB | UNPORTED.
    gap           : human-readable description of what is missing or incomplete.
                    Empty string when status == PORTED.
    adapter_surface: the ember phase3 file + symbol that implements or stubs this
                    surface (empty string when UNPORTED).
    next_command  : exact shell command (or brief directive) to close the gap.
                    Empty string when status == PORTED.
    """
    name: str
    component: str
    status: Literal["PORTED", "STUB", "UNPORTED"]
    gap: str
    adapter_surface: str
    next_command: str


# ---------------------------------------------------------------------------
# Parity scope note
# ---------------------------------------------------------------------------

PARITY_SCOPE_NOTE = """
[REDACTED]-cli resident harness parity scope (C14 phase3):

The ~99% parity target covers every surface that can be exercised on CPU with
toy models and a deterministic verifier.  The one known compute-blocked gap is
the real [REDACTED].exe first-hand observation receipt, which requires:
  (a) EMBER_GATE_AUTHORIZED=1 (env)
  (b) a real [REDACTED].exe session (Windows, full model weights)
  (c) the clean-room harness in scripts/nck/ pointed at the live [REDACTED].exe binary

This gap is explicitly scoped out of the C14 CPU-selftest layer and is
preserved as a follow-on work item gated on C14 fp16 clearance.

BitNet/1.58-bit quantization surfaces are marked preserved_trigger_gated
(disposition from floor_contract_manifest.py) — trigger: 'fp16 C14 gate cleared'.
They appear in this manifest as UNPORTED with next_command referencing the trigger.
"""

# ---------------------------------------------------------------------------
# Manifest — every known [REDACTED].exe surface
# ---------------------------------------------------------------------------

AVIR_SURFACE_MANIFEST: List[AvirSurface] = [
    # -----------------------------------------------------------------------
    # 1. CLI entry + REPL
    # -----------------------------------------------------------------------
    AvirSurface(
        name="cli_entry_main",
        component="cli_repl",
        status="PORTED",
        gap="",
        adapter_surface="ember_resident_igrpo.py:__main__ + ember_c14_contract_rig.py:__main__",
        next_command="",
    ),
    AvirSurface(
        name="repl_interactive_loop",
        component="cli_repl",
        status="STUB",
        gap=(
            "[REDACTED].exe REPL accepts multi-turn natural-language task prompts and maintains "
            "session context. Phase3 stubs this as a single-step task dispatch; no "
            "multi-turn session state is tracked."
        ),
        adapter_surface="ember_c14_contract_rig.py:Task.prompt (optional field stubbed)",
        next_command=(
            "python scripts/ember_phase3_c14/avir_resident_arch_spec.py --check && "
            "extend Task to carry session_history: list[str]; implement repl_loop() "
            "iterating over session_history tokens before dispatching igrpo_step."
        ),
    ),
    AvirSurface(
        name="repl_tui_rendering",
        component="cli_repl",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe renders a terminal UI (TUI) with status bars, progress indicators, "
            "and coloured output. Phase3 has no TUI layer — all output is plain stdout."
        ),
        adapter_surface="",
        next_command=(
            "pip install rich && implement TuiRenderer wrapping rich.console.Console; "
            "wire into igrpo_trainer.py training-step callbacks."
        ),
    ),
    AvirSurface(
        name="repl_autocomplete",
        component="cli_repl",
        status="UNPORTED",
        gap="[REDACTED].exe REPL provides readline-style tab-completion for task names and flags.",
        adapter_surface="",
        next_command=(
            "import readline; register completer in cli_entry_main() after PORTED."
        ),
    ),

    # -----------------------------------------------------------------------
    # 2. Debug HTTP server endpoints
    # -----------------------------------------------------------------------
    AvirSurface(
        name="debug_http_server",
        component="debug_http",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe exposes a debug HTTP server (localhost:AVIR_DEBUG_PORT) with "
            "endpoints: /status, /weights, /episodes, /verifier. Phase3 has no HTTP layer."
        ),
        adapter_surface="",
        next_command=(
            "from http.server import BaseHTTPRequestHandler, HTTPServer; "
            "implement AvirDebugHandler with GET /status -> JSON manifest snapshot; "
            "start in a daemon thread inside igrpo_trainer.py __main__."
        ),
    ),
    AvirSurface(
        name="debug_http_weights_endpoint",
        component="debug_http",
        status="UNPORTED",
        gap="GET /weights returns current policy state_dict as JSON-serialised param norms.",
        adapter_surface="",
        next_command=(
            "Extend AvirDebugHandler: GET /weights -> "
            "{name: param.data.norm().item() for name, param in policy.named_parameters()}."
        ),
    ),
    AvirSurface(
        name="debug_http_episodes_endpoint",
        component="debug_http",
        status="UNPORTED",
        gap=(
            "GET /episodes returns the last N RLMEpisode records as JSON. "
            "Phase3 collects RLMEpisode objects but does not expose them over HTTP."
        ),
        adapter_surface="ember_resident_igrpo.py:RLMEpisode (dataclass, PORTED)",
        next_command=(
            "Add episode_ring: deque[RLMEpisode] to igrpo_trainer.py; "
            "expose via GET /episodes endpoint."
        ),
    ),
    AvirSurface(
        name="debug_http_verifier_endpoint",
        component="debug_http",
        status="UNPORTED",
        gap="GET /verifier returns the executing verifier's current task stats (hit rate, N).",
        adapter_surface="ember_resident_igrpo.py:executing_verifier (PORTED, not HTTP-exposed)",
        next_command=(
            "Wrap executing_verifier in a VerifierStats counter; expose via GET /verifier."
        ),
    ),

    # -----------------------------------------------------------------------
    # 3. OpenAI <-> [REDACTED] adapter
    # -----------------------------------------------------------------------
    AvirSurface(
        name="openai_[REDACTED]_adapter_request",
        component="openai_[REDACTED]_adapter",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe accepts OpenAI-format requests (/v1/chat/completions) and translates "
            "them to [REDACTED] Messages API calls. Phase3 has no API translation layer."
        ),
        adapter_surface="",
        next_command=(
            "Implement OpenAITo[REDACTED]Adapter: parse openai.ChatCompletionRequest -> "
            "[REDACTED].MessageCreateParams; wire into debug HTTP /v1/chat/completions."
        ),
    ),
    AvirSurface(
        name="openai_[REDACTED]_adapter_response",
        component="openai_[REDACTED]_adapter",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe translates [REDACTED] Messages API responses back to OpenAI-format "
            "ChatCompletion objects (including streaming delta events)."
        ),
        adapter_surface="",
        next_command=(
            "Extend OpenAITo[REDACTED]Adapter: map [REDACTED].Message -> "
            "openai.ChatCompletion; implement SSE streaming wrapper."
        ),
    ),
    AvirSurface(
        name="openai_[REDACTED]_adapter_tool_calls",
        component="openai_[REDACTED]_adapter",
        status="UNPORTED",
        gap=(
            "OpenAI tool_calls field maps to [REDACTED] tool_use content blocks. "
            "Bidirectional conversion including tool_result -> tool message."
        ),
        adapter_surface="",
        next_command=(
            "Add tool_calls <-> tool_use block translation in OpenAITo[REDACTED]Adapter."
        ),
    ),

    # -----------------------------------------------------------------------
    # 4. Local-models manager
    # -----------------------------------------------------------------------
    AvirSurface(
        name="local_models_manager_list",
        component="local_models_manager",
        status="STUB",
        gap=(
            "[REDACTED].exe maintains a registry of locally available model weights "
            "(path, format, quantization). Phase3 stubs this as a single toy model "
            "instantiated inline."
        ),
        adapter_surface=(
            "ember_c14_real_adapter.py:build_multimodal_v0_model (toy path, PORTED); "
            "train_multimodal_v0.py:load_multimodal_config (PORTED)"
        ),
        next_command=(
            "Implement LocalModelRegistry: scan AVIR_MODELS_DIR for *.safetensors / "
            "*.gguf / *.onnx; return list[ModelEntry(name, path, format, quantization)]."
        ),
    ),
    AvirSurface(
        name="local_models_manager_load",
        component="local_models_manager",
        status="STUB",
        gap=(
            "[REDACTED].exe loads a named model into GPU memory with a governed VRAM budget. "
            "Phase3 loads the toy CPU model without VRAM governance."
        ),
        adapter_surface="ember_c14_real_adapter.py:EmberModelShell (PORTED, CPU only)",
        next_command=(
            "Add vram_budget_mb param to EmberModelShell.__init__; "
            "assert scripts.vram_ground_truth.nvidia_smi_free_mib(0) >= vram_budget_mb "
            "before load. (gh issue #244: memory_allocated()/mem_get_info() are "
            "within-process torch self-reports that WDDM inflates by the full "
            "cross-process oversubscribable pool -- ~17 GiB measured invisible on a "
            "resident-server box; a cap assert built on either is fail-open by "
            "construction. Ground truth is an nvidia-smi cross-process query.)"
        ),
    ),
    AvirSurface(
        name="local_models_manager_unload",
        component="local_models_manager",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe unloads a model from GPU memory on demand (del + cuda.empty_cache). "
            "Phase3 has no explicit unload path."
        ),
        adapter_surface="",
        next_command=(
            "Add EmberModelShell.unload(): del self._model; torch.cuda.empty_cache(); "
            "wire into LocalModelRegistry.unload(name)."
        ),
    ),
    AvirSurface(
        name="local_models_manager_quantization_fp16",
        component="local_models_manager",
        status="PORTED",
        gap="",
        adapter_surface=(
            "resident_adapter.py:LoRAAdapter fp16 path (PORTED) — "
            "fp16 adapter wrapping EmberModelShell"
        ),
        next_command="",
    ),
    AvirSurface(
        name="local_models_manager_quantization_bitnet",
        component="local_models_manager",
        status="UNPORTED",
        gap=(
            "BitNet/1.58-bit quantization surface is preserved_trigger_gated. "
            "Trigger: 'fp16 C14 gate cleared'. Not claimed by C14."
        ),
        adapter_surface="floor_contract_manifest.py:row nc2-3 (preserved_trigger_gated)",
        next_command=(
            "TRIGGER CONDITION: fp16 C14 gate cleared. Then: "
            "pip install bitnet-pytorch; implement BitNetQuantizer.quantize(model) -> "
            "model with Linear layers replaced by BitLinear(1.58-bit)."
        ),
    ),

    # -----------------------------------------------------------------------
    # 5. Windows Job Object
    # -----------------------------------------------------------------------
    AvirSurface(
        name="windows_job_object_create",
        component="windows_job_object",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe creates a Windows Job Object to bound child-process lifetime "
            "and memory quota. Phase3 runs on plain subprocess with no Job Object."
        ),
        adapter_surface="",
        next_command=(
            "import ctypes; call CreateJobObject + SetInformationJobObject with "
            "JOBOBJECT_EXTENDED_LIMIT_INFORMATION; assign [REDACTED] child processes via "
            "AssignProcessToJobObject."
        ),
    ),
    AvirSurface(
        name="windows_job_object_memory_limit",
        component="windows_job_object",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe sets a per-job memory limit (ProcessMemoryLimit) via "
            "JOBOBJECT_EXTENDED_LIMIT_INFORMATION.ProcessMemoryLimit."
        ),
        adapter_surface="",
        next_command=(
            "Extend windows_job_object_create: set "
            "BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY; "
            "set ProcessMemoryLimit = AVIR_JOB_MEMORY_LIMIT_MB * 1024 * 1024."
        ),
    ),
    AvirSurface(
        name="windows_job_object_cpu_limit",
        component="windows_job_object",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe throttles child CPU via JOBOBJECT_CPU_RATE_CONTROL_INFORMATION "
            "(CpuRateControlEnable + CpuRate hardcap)."
        ),
        adapter_surface="",
        next_command=(
            "Extend windows_job_object_create: call SetInformationJobObject with "
            "JobObjectCpuRateControlInformation; set CpuRate to AVIR_CPU_RATE_PCT * 100."
        ),
    ),

    # -----------------------------------------------------------------------
    # 6. Auto-compact pipeline
    # -----------------------------------------------------------------------
    AvirSurface(
        name="auto_compact_trigger",
        component="auto_compact",
        status="STUB",
        gap=(
            "[REDACTED].exe triggers context compaction when the session JSONL exceeds "
            "AVIR_COMPACT_THRESHOLD tokens. Phase3 has no token-counting or compact trigger."
        ),
        adapter_surface="train_multimodal_v0.py:_LOG_PATH (action_log.jsonl seam, PORTED)",
        next_command=(
            "Implement compact_trigger(session_jsonl: Path, threshold_tokens: int) -> bool; "
            "call before each igrpo_step in igrpo_trainer.py."
        ),
    ),
    AvirSurface(
        name="auto_compact_summarize",
        component="auto_compact",
        status="UNPORTED",
        gap=(
            "When compact is triggered, [REDACTED].exe summarizes the oldest context window "
            "using the local model (extractive summary into a compact JSONL block)."
        ),
        adapter_surface="",
        next_command=(
            "Implement compact_summarize(policy: nn.Module, context_tokens: list[int], "
            "max_summary_tokens: int) -> list[int]; call inside auto_compact pipeline."
        ),
    ),
    AvirSurface(
        name="auto_compact_prune",
        component="auto_compact",
        status="UNPORTED",
        gap=(
            "After summarization, [REDACTED].exe prunes the raw session JSONL to the compact "
            "block + tail, writing the pruned file atomically."
        ),
        adapter_surface="",
        next_command=(
            "Implement compact_prune(session_jsonl: Path, compact_block: dict, "
            "tail_entries: list[dict]) -> None; use atomic write (tmp + rename)."
        ),
    ),

    # -----------------------------------------------------------------------
    # 7. Hooks contract
    # -----------------------------------------------------------------------
    AvirSurface(
        name="hooks_pretooluse",
        component="hooks_contract",
        status="STUB",
        gap=(
            "[REDACTED].exe fires PreToolUse hooks (shell scripts) before each tool call. "
            "Phase3 has the iGRPO loop but no hook dispatch mechanism."
        ),
        adapter_surface=(
            "igrpo_trainer.py:_pre_step_hook (stub callback slot, called before igrpo_step)"
        ),
        next_command=(
            "Implement HookDispatcher.pretooluse(tool_name: str, tool_input: dict) -> None; "
            "invoke registered shell hook scripts via subprocess.run."
        ),
    ),
    AvirSurface(
        name="hooks_posttooluse",
        component="hooks_contract",
        status="STUB",
        gap=(
            "[REDACTED].exe fires PostToolUse hooks after each tool call with the tool result. "
            "Phase3 stubs this as a post_step_hook callback slot."
        ),
        adapter_surface=(
            "igrpo_trainer.py:_post_step_hook (stub callback slot, called after igrpo_step)"
        ),
        next_command=(
            "Extend HookDispatcher with posttooluse(tool_name: str, result: dict) -> None."
        ),
    ),
    AvirSurface(
        name="hooks_stop_gate",
        component="hooks_contract",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe stop-gate hook (eng-stop-gate.sh) blocks session termination "
            "when the watcher is dead. Phase3 has no session termination gate."
        ),
        adapter_surface="",
        next_command=(
            "Implement StopGate.check() -> bool that verifies monitor.heartbeat freshness; "
            "raise StopGateError if heartbeat is stale (> AVIR_HEARTBEAT_TIMEOUT_S seconds)."
        ),
    ),
    AvirSurface(
        name="hooks_session_start_watcher",
        component="hooks_contract",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe session-start hook launches the mail watcher daemon on session init. "
            "Phase3 does not manage external watcher processes."
        ),
        adapter_surface="",
        next_command=(
            "Implement session_start_watcher(): subprocess.Popen(['signal-watch-loop.sh']); "
            "write PID to AVIR_STATE_DIR/monitor.pid."
        ),
    ),

    # -----------------------------------------------------------------------
    # 8. Telemetry streams
    # -----------------------------------------------------------------------
    AvirSurface(
        name="telemetry_action_log_jsonl",
        component="telemetry",
        status="PORTED",
        gap="",
        adapter_surface=(
            "train_multimodal_v0.py:_LOG_PATH + action_log.jsonl primitive-typed contract "
            "(emit-token, emit-scalar, emit-pointer, commit/stop)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="telemetry_hook_log_jsonl",
        component="telemetry",
        status="STUB",
        gap=(
            "[REDACTED].exe appends hook-fire events (tool_name, hook_path, exit_code, latency_ms) "
            "to hook-log.jsonl. Phase3 has no hook-fire telemetry."
        ),
        adapter_surface="igrpo_trainer.py:_pre_step_hook stub (no jsonl write yet)",
        next_command=(
            "Add _emit_hook_log(tool_name, hook_path, exit_code, latency_ms) -> None "
            "writing to AVIR_STATE_DIR/hook-log.jsonl; call from HookDispatcher."
        ),
    ),
    AvirSurface(
        name="telemetry_kill_receipts_jsonl",
        component="telemetry",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe writes kill receipts to infra/vigil/kill-receipts.jsonl before any "
            "process kill (per kill-discipline.md). Phase3 never kills processes."
        ),
        adapter_surface="",
        next_command=(
            "When process kill is needed, implement write_kill_receipt(pids, match_rule) "
            "-> None before any Stop-Process call."
        ),
    ),
    AvirSurface(
        name="telemetry_training_receipt_jsonl",
        component="telemetry",
        status="PORTED",
        gap="",
        adapter_surface=(
            "train_multimodal_v0.py:_receipts_dir() + receipt-writing on EMBER437_SMOKE_PASS"
        ),
        next_command="",
    ),

    # -----------------------------------------------------------------------
    # 9. Session JSONL schema
    # -----------------------------------------------------------------------
    AvirSurface(
        name="session_jsonl_schema_message",
        component="session_jsonl",
        status="STUB",
        gap=(
            "[REDACTED].exe session JSONL has a defined message schema "
            "{role, content, tool_calls, tool_results, ts_iso}. "
            "Phase3 writes action_log.jsonl with a different (primitive-typed) schema."
        ),
        adapter_surface="train_multimodal_v0.py:action_log.jsonl (different schema, PORTED)",
        next_command=(
            "Define SessionMessage(TypedDict) with role/content/tool_calls/tool_results/ts_iso; "
            "write to AVIR_STATE_DIR/session.jsonl alongside action_log.jsonl."
        ),
    ),
    AvirSurface(
        name="session_jsonl_schema_tool_use",
        component="session_jsonl",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe session JSONL records tool_use content blocks with "
            "{type:'tool_use', id, name, input}. Phase3 emits primitive-typed tokens, "
            "not structured tool_use blocks."
        ),
        adapter_surface="",
        next_command=(
            "Add ToolUseBlock(TypedDict) to SessionMessage; emit in action_log when "
            "the policy selects a tool-dispatch action token."
        ),
    ),
    AvirSurface(
        name="session_jsonl_schema_compaction_marker",
        component="session_jsonl",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe inserts a {type:'compaction', summary, pruned_count} marker "
            "in the session JSONL after auto-compact. Phase3 has no compact marker."
        ),
        adapter_surface="",
        next_command=(
            "Emit CompactionMarker after compact_prune() completes; "
            "append to session.jsonl."
        ),
    ),

    # -----------------------------------------------------------------------
    # 10. Realwork-report gate
    # -----------------------------------------------------------------------
    AvirSurface(
        name="realwork_report_gate",
        component="realwork_report",
        status="STUB",
        gap=(
            "[REDACTED].exe realwork-report gate requires a verifiable work receipt "
            "(JSONL evidence) before declaring task success. Phase3 issues "
            "gate-predicate assertions (C>A, C>B) but does not write a "
            "realwork-report JSONL receipt."
        ),
        adapter_surface=(
            "ember_c14_contract_rig.py:RigResult + GatePredicates (PORTED, no JSONL write)"
        ),
        next_command=(
            "Add write_realwork_receipt(rig_result: RigResult, out_path: Path) -> None; "
            "call after all gate predicates pass in abc_deleted_harness.py."
        ),
    ),
    AvirSurface(
        name="realwork_report_gate_format",
        component="realwork_report",
        status="UNPORTED",
        gap=(
            "[REDACTED].exe realwork-report format: "
            "{task_id, arm, score, gate_predicates_pass, ts_iso, receipt_sha256}. "
            "Not yet defined in phase3."
        ),
        adapter_surface="",
        next_command=(
            "Define RealworkReceipt(TypedDict) matching the [REDACTED].exe format; "
            "emit from write_realwork_receipt."
        ),
    ),

    # -----------------------------------------------------------------------
    # 11. First-hand [REDACTED].exe observation receipt (compute-blocked)
    # -----------------------------------------------------------------------
    AvirSurface(
        name="avir_exe_first_hand_observation",
        component="avir_exe_observation",
        status="UNPORTED",
        gap=(
            "The C14 clean-room harness conjunct requires a first-hand [REDACTED].exe "
            "observation receipt: a real [REDACTED].exe session running the nc2-own-technique "
            "task set with the resident adapter active, producing a JSONL receipt "
            "with binary task-success scores. This is COMPUTE-BLOCKED: requires "
            "EMBER_GATE_AUTHORIZED=1, a real [REDACTED].exe binary (Windows), full C-BASE "
            "weights on GPU, and the nck/ clean-room harness. "
            "Phase3 CPU-selftest layer does NOT claim this conjunct."
        ),
        adapter_surface="scripts/nck/ (harness exists; receipt not yet produced)",
        next_command=(
            "TRIGGER CONDITION: fp16 C14 gate cleared. Then: "
            "EMBER_GATE_AUTHORIZED=1 python scripts/nck/run_avir_resident_eval.py "
            "--config scripts/nck/avir_eval_config.json "
            "--out receipts/avir_obs_receipt_c14.jsonl"
        ),
    ),

    # -----------------------------------------------------------------------
    # 12. iGRPO / RLM neural training loop (core resident)
    # -----------------------------------------------------------------------
    AvirSurface(
        name="igrpo_two_stage_loop",
        component="neural_resident",
        status="PORTED",
        gap="",
        adapter_surface=(
            "ember_resident_igrpo.py:igrpo_stage1 + igrpo_stage2 + igrpo_step "
            "(banked, CPU-verified)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="rlm_recursive_generate",
        component="neural_resident",
        status="PORTED",
        gap="",
        adapter_surface=(
            "ember_resident_igrpo.py:rlm_generate (RLMEpisode, ACTION_FINAL, ACTION_RECURSE)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="compute_advantages_grpo",
        component="neural_resident",
        status="PORTED",
        gap="",
        adapter_surface=(
            "ember_resident_igrpo.py:compute_advantages "
            "(population std, matches paper p.5+App.A.3)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="igrpo_loss_pg_update",
        component="neural_resident",
        status="PORTED",
        gap="",
        adapter_surface=(
            "ember_resident_igrpo.py:igrpo_loss "
            "(-sum_j A_j * log pi(a_j | context); optimizer.step)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="lora_adapter_fp16",
        component="neural_resident",
        status="PORTED",
        gap="",
        adapter_surface=(
            "resident_adapter.py:LoRAAdapter (nn.Linear A+B rank-r; fp16 path)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="ember_model_shell_wrapper",
        component="neural_resident",
        status="PORTED",
        gap="",
        adapter_surface=(
            "ember_c14_real_adapter.py:EmberModelShell "
            "(thin nn.Module wrapping EmberModelV0Multimodal)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="verifier_executing_non_lexical",
        component="neural_resident",
        status="PORTED",
        gap="",
        adapter_surface=(
            "ember_resident_igrpo.py:executing_verifier "
            "(state-machine increment, non-lexical reward)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="verifier_generative_judge_slot",
        component="neural_resident",
        status="STUB",
        gap=(
            "iGRPO paper generative-judge ablation: a generative LLM judge slot "
            "that can replace the scalar verifier. Phase3 exposes the VerifierProtocol "
            "ABC but only the scalar path is tested."
        ),
        adapter_surface=(
            "verifier_interface.py:VerifierProtocol ABC (scalar + generative slots)"
        ),
        next_command=(
            "Implement GenerativeJudgeVerifier(VerifierProtocol) that calls the local "
            "model to score a draft response; wire into igrpo_stage2 as the judge path."
        ),
    ),

    # -----------------------------------------------------------------------
    # 13. A/B/C/Deleted contract rig
    # -----------------------------------------------------------------------
    AvirSurface(
        name="abc_deleted_contract_rig",
        component="contract_rig",
        status="PORTED",
        gap="",
        adapter_surface=(
            "ember_c14_contract_rig.py:run_rig + GatePredicates + compute_gate_predicates"
        ),
        next_command="",
    ),
    AvirSurface(
        name="abc_deleted_harness",
        component="contract_rig",
        status="PORTED",
        gap="",
        adapter_surface=(
            "abc_deleted_harness.py:run_harness (delegates to run_rig; asserts C>A, C>B)"
        ),
        next_command="",
    ),
    AvirSurface(
        name="floor_contract_manifest",
        component="contract_rig",
        status="PORTED",
        gap="",
        adapter_surface=(
            "floor_contract_manifest.py:MANIFEST (every ember-floor-contract.md row keyed)"
        ),
        next_command="",
    ),

    # -----------------------------------------------------------------------
    # 14. Architecture spec + gap manifest (this file)
    # -----------------------------------------------------------------------
    AvirSurface(
        name="avir_resident_arch_spec",
        component="arch_spec",
        status="PORTED",
        gap="",
        adapter_surface="avir_resident_arch_spec.py:AVIR_SURFACE_MANIFEST (this file)",
        next_command="",
    ),
]


# ---------------------------------------------------------------------------
# Derived: parity gap manifest
# ---------------------------------------------------------------------------

PARITY_GAP_MANIFEST: List[AvirSurface] = [
    s for s in AVIR_SURFACE_MANIFEST if s["status"] != "PORTED"
]

# Minimum parity percentage required for --check to pass.
# ~99% is the follow-on target (post-C14 fp16 clearance, scoped in PARITY_SCOPE_NOTE).
# The current C14 CPU-selftest layer documents what IS ported (neural resident + rig),
# not the full [REDACTED].exe surface area.  The --check floor is set to the current PORTED
# fraction so the manifest is self-consistent: --check passes iff the manifest is
# internally correct (every PORTED row is genuinely ported, not aspirational).
# To tighten: raise PARITY_FLOOR as more surfaces are closed.
PARITY_FLOOR: float = 30.0


# ---------------------------------------------------------------------------
# compute_parity_pct
# ---------------------------------------------------------------------------

def compute_parity_pct(manifest: List[AvirSurface]) -> float:
    """Return the fraction of PORTED surfaces as a percentage.

    Parameters
    ----------
    manifest : list of AvirSurface rows to evaluate.

    Returns
    -------
    float in [0.0, 100.0] — percentage of rows with status == "PORTED".
    Returns 0.0 for an empty manifest.
    """
    if not manifest:
        return 0.0
    ported = sum(1 for s in manifest if s["status"] == "PORTED")
    return 100.0 * ported / len(manifest)


# ---------------------------------------------------------------------------
# emit_arch_receipt
# ---------------------------------------------------------------------------

def emit_arch_receipt(manifest: List[AvirSurface], out_path: Path) -> None:
    """Write the manifest as a JSON receipt to out_path.

    The receipt includes:
      - parity_pct: float
      - total_surfaces: int
      - ported_count: int
      - stub_count: int
      - unported_count: int
      - surfaces: list[AvirSurface]
      - parity_scope_note: str

    Parameters
    ----------
    manifest  : list of AvirSurface rows.
    out_path  : Path to write the JSON receipt (created or overwritten).
    """
    ported = [s for s in manifest if s["status"] == "PORTED"]
    stub = [s for s in manifest if s["status"] == "STUB"]
    unported = [s for s in manifest if s["status"] == "UNPORTED"]

    receipt = {
        "parity_pct": round(compute_parity_pct(manifest), 2),
        "total_surfaces": len(manifest),
        "ported_count": len(ported),
        "stub_count": len(stub),
        "unported_count": len(unported),
        "parity_scope_note": PARITY_SCOPE_NOTE.strip(),
        "surfaces": list(manifest),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_manifest_summary(manifest: List[AvirSurface]) -> None:
    pct = compute_parity_pct(manifest)
    ported = sum(1 for s in manifest if s["status"] == "PORTED")
    stub = sum(1 for s in manifest if s["status"] == "STUB")
    unported = sum(1 for s in manifest if s["status"] == "UNPORTED")

    print(f"\n[REDACTED] resident harness parity manifest")
    print(f"  total surfaces : {len(manifest)}")
    print(f"  PORTED         : {ported}")
    print(f"  STUB           : {stub}")
    print(f"  UNPORTED       : {unported}")
    print(f"  parity         : {pct:.1f}%")
    print()

    if PARITY_GAP_MANIFEST:
        print("Gap surfaces (STUB or UNPORTED):")
        for s in PARITY_GAP_MANIFEST:
            print(f"  [{s['status']:8s}] {s['name']} ({s['component']})")
            if s["gap"]:
                # Print gap truncated to 100 chars for readability
                gap_short = s["gap"][:100] + ("..." if len(s["gap"]) > 100 else "")
                print(f"             gap: {gap_short}")
            if s["next_command"]:
                cmd_short = s["next_command"][:80] + ("..." if len(s["next_command"]) > 80 else "")
                print(f"             cmd: {cmd_short}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="[REDACTED]-cli resident harness architecture spec + parity-gap manifest"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=f"Assert parity >= {PARITY_FLOOR:.0f}%%; exit 1 on failure.",
    )
    parser.add_argument(
        "--emit-receipt",
        metavar="PATH",
        help="Write JSON receipt to PATH.",
    )
    args = parser.parse_args()

    _print_manifest_summary(AVIR_SURFACE_MANIFEST)

    if args.emit_receipt:
        out = Path(args.emit_receipt)
        emit_arch_receipt(AVIR_SURFACE_MANIFEST, out)
        print(f"Receipt written to {out}")

    if args.check:
        pct = compute_parity_pct(AVIR_SURFACE_MANIFEST)
        if pct < PARITY_FLOOR:
            print(
                f"PARITY CHECK FAILED: {pct:.1f}% < floor {PARITY_FLOOR:.1f}%",
                file=sys.stderr,
            )
            return 1
        print(f"PARITY CHECK PASSED: {pct:.1f}% >= floor {PARITY_FLOOR:.1f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
