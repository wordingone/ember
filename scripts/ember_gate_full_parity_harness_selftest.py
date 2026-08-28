#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the clean-room the predecessor CLI full parity harness gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_gate_full_parity_harness as gate

    with tempfile.TemporaryDirectory(prefix="ember-gate-full-parity-") as td:
        root = Path(td)
        repo = root / "repo"
        reference_root = root / "the predecessor CLI"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        inventory = receipt_dir / "inventory.json"
        bootstrap = receipt_dir / "bootstrap.json"
        out = root / "receipt.json"

        _write(
            repo / "docs/domains/governance/authority/GOAL.md",
            """
# Ember Goal
## Current Blocker Packet
- **Current blocker:** full the predecessor CLI parity gate.
- **Current executable command:** implement and run
  `python scripts\\ember_gate_full_parity_harness.py --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json`.
- **Required receipt:** `THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_PASS` or BLOCKED.
- **Kill/ablate test:** deleting UI/backend/goal organ surfaces blocks.
- **Next blocker if pass:** RLM/iGRPO neural resident-training organ.
- **Next blocker if fail:** continue exact missing the predecessor CLI full-parity surface.
""",
        )
        _write(
            inventory,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-CLEANROOM-INVENTORY",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "THE_PREDECESSOR_CLI_CLEANROOM_INVENTORY_BLOCKED",
                    "launch_surface": {
                        "reference_root": str(reference_root),
                        "reference_root_exists": True,
                        "reference_exe": {"path": str(reference_root / "predecessor-cli.exe"), "exists": True},
                        "launch_ps1": {"path": str(reference_root / "launch.ps1"), "exists": False},
                    },
                    "copyright_cleanroom_boundary": {
                        "legal_provenance_files": [
                            {"path": "legal/origin.md", "sha256": "a" * 64},
                            {"path": "legal/ui-parity-audit.md", "sha256": "b" * 64},
                        ]
                    },
                    "source_inventory": {"text_file_count_scanned": 2956},
                },
                indent=2,
            ),
        )
        _write(
            bootstrap,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-GOAL-MODE-PARITY-ADAPTER",
                    "ts": "20260621T000001Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "THE_PREDECESSOR_CLI_GOAL_MODE_PARITY_ADAPTER_PASS",
                    "does_not_satisfy_full_the predecessor CLI_parity": True,
                    "next_missing_precondition": "the predecessor CLI_full_parity_harness_gate",
                },
                indent=2,
            ),
        )
        for rel in [
            "legal/origin.md",
            "legal/ui-parity-audit.md",
            "legal/ui-parity-audit-pass2.md",
            "legal/ui-parity-audit-pass3.md",
            "package.json",
        ]:
            _write(reference_root / rel, f"# {rel}\n")

        receipt = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            out=out,
        )

        assert receipt["verdict"] == "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_BLOCKED"
        assert receipt["classification"] == "FULL_PARITY_GATE_BLOCKED_NOT_HEADLESS_PASS"
        assert receipt["headless_bootstrap_classification"] == "HEADLESS_BOOTSTRAP_ONLY"
        assert receipt["next_missing_precondition"] == "function_slash_commands"
        assert "near_99_percent" in receipt["parity_target"]
        assert len(receipt["surface_matrix"]) >= 12
        by_id = {row["surface_id"]: row for row in receipt["surface_matrix"]}
        for required in gate.REQUIRED_SURFACE_IDS:
            assert required in by_id, required
            assert by_id[required]["cleanroom_implemented"] is False
            assert by_id[required]["status"] == "BLOCKED"
        native_refs = by_id["native_goal_organ"]["reference_evidence"]
        assert any(row["source_root"] == "ember_repo" and row["path"] == "docs/domains/governance/authority/GOAL.md" and row["exists"] for row in native_refs)
        assert receipt["bootstrap_receipt"]["does_not_satisfy_full_the predecessor CLI_parity"] is True
        assert "headless_bootstrap_only" in receipt["blocked_reasons"]
        assert receipt["delete_ablate_required"]["native_goal_organ_deleted_blocks"] is False
        assert receipt["next_executable_command"].startswith("python scripts\\ember_gate_full_parity_harness.py")

        native = receipt_dir / "native-goal.json"
        _write(
            native,
            json.dumps(
                {
                    "ticket": "EMBER-NATIVE-GOAL-ORGAN",
                    "ts": "20260621T000002Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "NATIVE_GOAL_ORGAN_PASS",
                    "native_goal_organ": {
                        "implemented_surface": "parse/read/select/compile/act-or-delegate/verify/write/preserve",
                    },
                    "deletion_ablation": {
                        "organ_deleted_blocks_selection": True,
                        "receipt_reader_alone_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            out=out,
        )
        advanced_by_id = {row["surface_id"]: row for row in advanced["surface_matrix"]}
        assert advanced_by_id["native_goal_organ"]["status"] == "PASS"
        assert advanced_by_id["native_goal_organ"]["cleanroom_implemented"] is True
        assert advanced["delete_ablate_required"]["native_goal_organ_deleted_blocks"] is True
        assert advanced["native_goal_organ_receipt"]["applied"] is True
        assert advanced["next_missing_precondition"] != "native_goal_organ"

        function_surface = receipt_dir / "function-slash.json"
        _write(
            function_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-FUNCTION-SLASH-COMMANDS",
                    "ts": "20260621T000003Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "FUNCTION_SLASH_COMMANDS_GATE_PASS",
                    "command_surface": {
                        "registry_counts": {
                            "n_registered": 66,
                            "n_local": 45,
                            "n_goal_safe_replacement": 19,
                            "n_trigger_gated": 2,
                            "n_unclassified": 0,
                        }
                    },
                    "deletion_ablation": {
                        "registry_deleted_blocks_resolution": True,
                        "dispatcher_deleted_blocks_action": True,
                        "static_docs_only_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        function_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            out=out,
        )
        function_by_id = {row["surface_id"]: row for row in function_advanced["surface_matrix"]}
        assert function_by_id["function_slash_commands"]["status"] == "PASS"
        assert function_by_id["function_slash_commands"]["cleanroom_implemented"] is True
        assert function_advanced["delete_ablate_required"]["backend_command_router_deleted_blocks"] is True
        assert function_advanced["function_slash_commands_receipt"]["applied"] is True
        assert function_advanced["next_missing_precondition"] == "uiux_repl_components"

        uiux_surface = receipt_dir / "uiux-repl.json"
        _write(
            uiux_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-UIUX-REPL-COMPONENTS",
                    "ts": "20260621T000004Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "UIUX_REPL_COMPONENTS_GATE_PASS",
                    "uiux_repl_components": {
                        "contract_counts": {
                            "n_components": 50,
                            "n_local": 35,
                            "n_goal_safe_replacement": 13,
                            "n_trigger_gated": 2,
                            "n_unclassified": 0,
                        }
                    },
                    "deletion_ablation": {
                        "component_contract_deleted_blocks_prompt_input": True,
                        "component_contract_deleted_blocks_rendering": True,
                        "command_registry_alone_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        uiux_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            out=out,
        )
        uiux_by_id = {row["surface_id"]: row for row in uiux_advanced["surface_matrix"]}
        assert uiux_by_id["uiux_repl_components"]["status"] == "PASS"
        assert uiux_by_id["uiux_repl_components"]["cleanroom_implemented"] is True
        assert uiux_advanced["delete_ablate_required"]["visible_uiux_deleted_blocks"] is True
        assert uiux_advanced["uiux_repl_components_receipt"]["applied"] is True
        assert uiux_advanced["next_missing_precondition"] == "backend_coordinator_agents"

        backend_surface = receipt_dir / "backend-coordinator.json"
        _write(
            backend_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-BACKEND-COORDINATOR-AGENTS",
                    "ts": "20260621T000005Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "BACKEND_COORDINATOR_AGENTS_GATE_PASS",
                    "backend_coordinator_agents": {
                        "contract_counts": {
                            "n_components": 20,
                            "n_local": 14,
                            "n_goal_safe_replacement": 5,
                            "n_trigger_gated": 1,
                            "n_unclassified": 0,
                        }
                    },
                    "deletion_ablation": {
                        "coordinator_backend_deleted_blocks_delegation": True,
                        "agent_registry_deleted_blocks_selection": True,
                        "worker_lifecycle_deleted_blocks_completion": True,
                        "task_panel_without_backend_is_mock_only": True,
                        "command_registry_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        backend_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            out=out,
        )
        backend_by_id = {row["surface_id"]: row for row in backend_advanced["surface_matrix"]}
        assert backend_by_id["backend_coordinator_agents"]["status"] == "PASS"
        assert backend_by_id["backend_coordinator_agents"]["cleanroom_implemented"] is True
        assert backend_advanced["delete_ablate_required"]["backend_coordinator_agents_deleted_blocks"] is True
        assert backend_advanced["backend_coordinator_agents_receipt"]["applied"] is True
        assert backend_advanced["next_missing_precondition"] == "launch_packaging"

        launch_surface = receipt_dir / "launch-packaging.json"
        _write(
            launch_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-LAUNCH-PACKAGING",
                    "ts": "20260621T000006Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "LAUNCH_PACKAGING_GATE_PASS",
                    "launch_packaging": {
                        "bin_name": "ember",
                        "launcher_path": "Ember.cmd",
                        "uses_reference_exe": False,
                    },
                    "deletion_ablation": {
                        "launcher_deleted_blocks_invocation": True,
                        "entrypoint_deleted_blocks_handoff": True,
                        "package_metadata_alone_insufficient": True,
                        "stale_launch_ps1_pointer_insufficient": True,
                        "reference_exe_not_invoked": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        launch_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            out=out,
        )
        launch_by_id = {row["surface_id"]: row for row in launch_advanced["surface_matrix"]}
        assert launch_by_id["launch_packaging"]["status"] == "PASS"
        assert launch_by_id["launch_packaging"]["cleanroom_implemented"] is True
        assert launch_advanced["delete_ablate_required"]["launch_packaging_deleted_blocks"] is True
        assert launch_advanced["launch_packaging_receipt"]["applied"] is True
        assert launch_advanced["next_missing_precondition"] == "process_supervision"

        process_surface = receipt_dir / "process-supervision.json"
        _write(
            process_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-PROCESS-SUPERVISION",
                    "ts": "20260621T000007Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "PROCESS_SUPERVISION_GATE_PASS",
                    "verification": {"probe": {"record": {"timeout_s": 0.25, "status": "terminated"}}},
                    "deletion_ablation": {
                        "supervisor_deleted_blocks_spawn_and_tracking": True,
                        "timeout_handler_deleted_blocks_termination": True,
                        "survivor_probe_deleted_blocks_cleanup_verification": True,
                        "background_lifecycle_accounting_deleted_blocks_receipt": True,
                        "manual_taskkill_insufficient": True,
                        "launcher_only_behavior_insufficient": True,
                        "static_process_policy_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        process_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            out=out,
        )
        process_by_id = {row["surface_id"]: row for row in process_advanced["surface_matrix"]}
        assert process_by_id["process_supervision"]["status"] == "PASS"
        assert process_by_id["process_supervision"]["cleanroom_implemented"] is True
        assert process_advanced["delete_ablate_required"]["process_supervisor_deleted_blocks"] is True
        assert process_advanced["process_supervision_receipt"]["applied"] is True
        assert process_advanced["next_missing_precondition"] == "hook_runner"

        hook_surface = receipt_dir / "hook-runner.json"
        _write(
            hook_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-HOOK-RUNNER",
                    "ts": "20260621T000008Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "HOOK_RUNNER_GATE_PASS",
                    "hook_runner": {
                        "implemented": True,
                        "event_surface": ["pre_tool", "post_tool"],
                        "policy_surface": ["read_only", "deny_mutation", "unknown_event_fail_closed"],
                    },
                    "deletion_ablation": {
                        "hook_runner_deleted_blocks_event_dispatch": True,
                        "policy_engine_deleted_blocks_read_only_enforcement": True,
                        "permission_denial_deleted_blocks_fail_closed_unknown_event": True,
                        "lifecycle_log_deleted_blocks_receipt_accounting": True,
                        "static_hook_list_insufficient": True,
                        "docs_only_policy_insufficient": True,
                        "permissive_callback_runner_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        hook_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            out=out,
        )
        hook_by_id = {row["surface_id"]: row for row in hook_advanced["surface_matrix"]}
        assert hook_by_id["hook_runner"]["status"] == "PASS"
        assert hook_by_id["hook_runner"]["cleanroom_implemented"] is True
        assert hook_advanced["delete_ablate_required"]["hook_runner_deleted_blocks"] is True
        assert hook_advanced["hook_runner_receipt"]["applied"] is True
        assert hook_advanced["next_missing_precondition"] == "tool_dispatch_permissions"

        tool_surface = receipt_dir / "tool-dispatch-permissions.json"
        _write(
            tool_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-TOOL-DISPATCH-PERMISSIONS",
                    "ts": "20260621T000009Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "TOOL_DISPATCH_PERMISSIONS_GATE_PASS",
                    "tool_dispatch_permissions": {
                        "implemented": True,
                        "tool_surface": ["status.read", "note.write", "repo.delete"],
                        "permission_surface": ["read_allow", "write_allow_with_rollback", "destructive_deny"],
                    },
                    "deletion_ablation": {
                        "tool_registry_deleted_blocks_lookup": True,
                        "permission_policy_deleted_blocks_prompt_and_decision": True,
                        "dispatcher_deleted_blocks_execution_handoff": True,
                        "verifier_hook_deleted_blocks_verification_accounting": True,
                        "rollback_hook_deleted_blocks_reversal_accounting": True,
                        "static_tool_list_insufficient": True,
                        "docs_only_permission_policy_insufficient": True,
                        "always_allow_runner_insufficient": True,
                        "prompt_only_route_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        tool_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            tool_dispatch_permissions_receipt=tool_surface,
            out=out,
        )
        tool_by_id = {row["surface_id"]: row for row in tool_advanced["surface_matrix"]}
        assert tool_by_id["tool_dispatch_permissions"]["status"] == "PASS"
        assert tool_by_id["tool_dispatch_permissions"]["cleanroom_implemented"] is True
        assert tool_advanced["tool_dispatch_permissions_receipt"]["applied"] is True
        assert tool_advanced["delete_ablate_required"]["tool_dispatch_permissions_deleted_blocks"] is True
        assert tool_advanced["next_missing_precondition"] == "state_persistence"

        state_surface = receipt_dir / "state-persistence.json"
        _write(
            state_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-STATE-PERSISTENCE",
                    "ts": "20260621T000010Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "STATE_PERSISTENCE_GATE_PASS",
                    "state_persistence": {
                        "implemented": True,
                        "state_surface": ["sessions", "memory", "settings", "accounts", "compaction", "resume"],
                    },
                    "deletion_ablation": {
                        "state_store_deleted_blocks_write": True,
                        "state_store_deleted_blocks_read": True,
                        "state_store_deleted_blocks_resume": True,
                        "compaction_deleted_blocks_memory_consolidation": True,
                        "settings_store_deleted_blocks_reload": True,
                        "model_account_store_deleted_blocks_reload": True,
                        "lifecycle_log_deleted_blocks_state_accounting": True,
                        "transient_in_memory_dict_insufficient": True,
                        "docs_only_state_policy_insufficient": True,
                        "prompt_only_memory_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        state_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            tool_dispatch_permissions_receipt=tool_surface,
            state_persistence_receipt=state_surface,
            out=out,
        )
        state_by_id = {row["surface_id"]: row for row in state_advanced["surface_matrix"]}
        assert state_by_id["state_persistence"]["status"] == "PASS"
        assert state_by_id["state_persistence"]["cleanroom_implemented"] is True
        assert state_advanced["state_persistence_receipt"]["applied"] is True
        assert state_advanced["delete_ablate_required"]["state_persistence_deleted_blocks"] is True
        assert state_advanced["next_missing_precondition"] == "receipt_store"

        receipt_store_surface = receipt_dir / "receipt-store.json"
        _write(
            receipt_store_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-RECEIPT-STORE",
                    "ts": "20260621T000011Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "RECEIPT_STORE_GATE_PASS",
                    "receipt_store": {
                        "implemented": True,
                        "receipt_surface": ["checked_write", "checked_read", "schema_validation", "event_log", "replay", "evidence_lookup"],
                    },
                    "deletion_ablation": {
                        "receipt_store_deleted_blocks_fail_closed_write": True,
                        "receipt_store_deleted_blocks_read": True,
                        "schema_validator_deleted_blocks_invalid_receipt_rejection": True,
                        "event_log_deleted_blocks_append_read": True,
                        "replay_hook_deleted_blocks_replay": True,
                        "evidence_lookup_deleted_blocks_ticket_search": True,
                        "loose_json_dump_insufficient": True,
                        "docs_only_receipt_policy_insufficient": True,
                        "non_validating_logger_insufficient": True,
                        "prompt_only_evidence_trail_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        receipt_store_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            tool_dispatch_permissions_receipt=tool_surface,
            state_persistence_receipt=state_surface,
            receipt_store_receipt=receipt_store_surface,
            out=out,
        )
        receipt_store_by_id = {row["surface_id"]: row for row in receipt_store_advanced["surface_matrix"]}
        assert receipt_store_by_id["receipt_store"]["status"] == "PASS"
        assert receipt_store_by_id["receipt_store"]["cleanroom_implemented"] is True
        assert receipt_store_advanced["receipt_store_receipt"]["applied"] is True
        assert receipt_store_advanced["delete_ablate_required"]["receipt_store_deleted_blocks"] is True
        assert receipt_store_advanced["next_missing_precondition"] == "rollback_rewind"

        rollback_surface = receipt_dir / "rollback-rewind.json"
        _write(
            rollback_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-ROLLBACK-REWIND",
                    "ts": "20260621T000012Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "ROLLBACK_REWIND_GATE_PASS",
                    "rollback_rewind": {
                        "implemented": True,
                        "rollback_surface": ["checkpoint_store", "diff_engine", "restore_path", "checkpoint_selector", "rollback_event_log"],
                    },
                    "deletion_ablation": {
                        "rollback_store_deleted_blocks_checkpoint_discovery": True,
                        "diff_engine_deleted_blocks_diff_generation": True,
                        "restore_path_deleted_blocks_restore_execution": True,
                        "checkpoint_selector_deleted_blocks_selection": True,
                        "rollback_events_deleted_blocks_accounting": True,
                        "manual_git_reset_insufficient": True,
                        "static_docs_insufficient": True,
                        "prompt_only_rewind_claim_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        rollback_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            tool_dispatch_permissions_receipt=tool_surface,
            state_persistence_receipt=state_surface,
            receipt_store_receipt=receipt_store_surface,
            rollback_rewind_receipt=rollback_surface,
            out=out,
        )
        rollback_by_id = {row["surface_id"]: row for row in rollback_advanced["surface_matrix"]}
        assert rollback_by_id["rollback_rewind"]["status"] == "PASS"
        assert rollback_by_id["rollback_rewind"]["cleanroom_implemented"] is True
        assert rollback_advanced["rollback_rewind_receipt"]["applied"] is True
        assert rollback_advanced["delete_ablate_required"]["rollback_path_deleted_blocks"] is True
        assert rollback_advanced["next_missing_precondition"] == "communication_mailbox_computer_use"

        communication_surface = receipt_dir / "communication-mailbox-computer-use.json"
        _write(
            communication_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-COMMUNICATION-MAILBOX-COMPUTER-USE",
                    "ts": "20260621T000013Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_PASS",
                    "communication_mailbox_computer_use": {
                        "implemented": True,
                        "communication_surface": ["mailbox_identity", "user_facing", "founder_mailbox", "inbound", "reachability_status", "computer_use_route", "event_log"],
                    },
                    "deletion_ablation": {
                        "identity_deleted_blocks_message_construction": True,
                        "founder_addressing_deleted_blocks_route_selection": True,
                        "reachability_deleted_blocks_status_accounting": True,
                        "computer_use_route_deleted_blocks_computer_use": True,
                        "communication_events_deleted_blocks_receipt_rows": True,
                        "static_docs_insufficient": True,
                        "mock_only_chat_text_insufficient": True,
                        "live_codex_mailbox_polling_insufficient": True,
                        "prompt_only_coordination_claim_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        communication_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            tool_dispatch_permissions_receipt=tool_surface,
            state_persistence_receipt=state_surface,
            receipt_store_receipt=receipt_store_surface,
            rollback_rewind_receipt=rollback_surface,
            communication_mailbox_computer_use_receipt=communication_surface,
            out=out,
        )
        communication_by_id = {row["surface_id"]: row for row in communication_advanced["surface_matrix"]}
        assert communication_by_id["communication_mailbox_computer_use"]["status"] == "PASS"
        assert communication_by_id["communication_mailbox_computer_use"]["cleanroom_implemented"] is True
        assert communication_advanced["communication_mailbox_computer_use_receipt"]["applied"] is True
        assert communication_advanced["delete_ablate_required"]["communication_bridge_deleted_blocks"] is True
        assert communication_advanced["next_missing_precondition"] == "cleanroom_legal_boundary"

        legal_surface = receipt_dir / "cleanroom-legal-boundary.json"
        _write(
            legal_surface,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-CLEANROOM-LEGAL-BOUNDARY",
                    "ts": "20260621T000014Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "CLEANROOM_LEGAL_BOUNDARY_GATE_PASS",
                    "cleanroom_legal_boundary": {
                        "implemented": True,
                        "legal_surface": ["legal_file_discovery", "provenance_hash_checks", "copy_boundary", "surface_linkage", "inventory_accounting", "legal_event_log"],
                    },
                    "deletion_ablation": {
                        "legal_file_discovery_deleted_blocks_legal_files": True,
                        "provenance_deleted_blocks_hash_checks": True,
                        "copy_boundary_deleted_blocks_copy_enforcement": True,
                        "surface_linkage_deleted_blocks_per_surface_provenance": True,
                        "inventory_deleted_blocks_file_inventory_accounting": True,
                        "legal_events_deleted_blocks_receipt_rows": True,
                        "static_policy_text_insufficient": True,
                        "handwaved_cleanroom_claim_insufficient": True,
                        "copied_the predecessor CLI_implementation_insufficient": True,
                        "prompt_only_provenance_narration_insufficient": True,
                        "headless_adapter_alone_insufficient": True,
                        "manual_codex_steering_insufficient": True,
                    },
                },
                indent=2,
            ),
        )
        legal_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            tool_dispatch_permissions_receipt=tool_surface,
            state_persistence_receipt=state_surface,
            receipt_store_receipt=receipt_store_surface,
            rollback_rewind_receipt=rollback_surface,
            communication_mailbox_computer_use_receipt=communication_surface,
            cleanroom_legal_boundary_receipt=legal_surface,
            out=out,
        )
        legal_by_id = {row["surface_id"]: row for row in legal_advanced["surface_matrix"]}
        assert legal_by_id["cleanroom_legal_boundary"]["status"] == "PASS"
        assert legal_by_id["cleanroom_legal_boundary"]["cleanroom_implemented"] is True
        assert legal_advanced["cleanroom_legal_boundary_receipt"]["applied"] is True
        assert legal_advanced["next_missing_precondition"] == "real_reference_uiux_ax_observation"
        assert legal_advanced["verdict"] == "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_BLOCKED"
        assert legal_advanced["classification"] == "FULL_PARITY_GATE_BLOCKED_NOT_HEADLESS_PASS"
        assert "real_reference_uiux_ax_observation_missing" in legal_advanced["blocked_reasons"]
        assert legal_advanced["real_reference_uiux_ax_observation_receipt"]["exists"] is False

        real_observation = receipt_dir / "real-observation.json"
        _write(
            real_observation,
            json.dumps(
                {
                    "ticket": "EMBER-REAL-PREDECESSOR-CLI-UIUX-AX-OBSERVATION",
                    "ts": "20260622T000015Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "REAL_PREDECESSOR_CLI_UIUX_AX_OBSERVATION_PASS",
                    "classification": "REAL_reference_LIVED_SURFACE_OBSERVED",
                    "observed_real_reference_binary": True,
                    "observed_real_tui": True,
                    "observed_agent_loop": True,
                    "observed_uiux_ax": True,
                    "resource_governed": True,
                },
                indent=2,
            ),
        )
        real_observed_advanced = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            inventory_receipt=inventory,
            bootstrap_receipt=bootstrap,
            native_goal_organ_receipt=native,
            function_slash_commands_receipt=function_surface,
            uiux_repl_components_receipt=uiux_surface,
            backend_coordinator_agents_receipt=backend_surface,
            launch_packaging_receipt=launch_surface,
            process_supervision_receipt=process_surface,
            hook_runner_receipt=hook_surface,
            tool_dispatch_permissions_receipt=tool_surface,
            state_persistence_receipt=state_surface,
            receipt_store_receipt=receipt_store_surface,
            rollback_rewind_receipt=rollback_surface,
            communication_mailbox_computer_use_receipt=communication_surface,
            cleanroom_legal_boundary_receipt=legal_surface,
            real_observation_receipt=real_observation,
            out=out,
        )
        assert real_observed_advanced["next_missing_precondition"] == "rlm_igrpo_train_multimodal_adapter"
        assert real_observed_advanced["verdict"] == "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_PASS"
        assert real_observed_advanced["classification"] == "FULL_PARITY_GATE_PASS"
        assert real_observed_advanced["headless_bootstrap_classification"] == "SUPERSEDED_BY_FULL_CLEANROOM_PARITY_RECEIPTS"
        assert real_observed_advanced["blocked_reasons"] == []
        assert real_observed_advanced["real_reference_uiux_ax_observation_receipt"]["verdict"] == "REAL_PREDECESSOR_CLI_UIUX_AX_OBSERVATION_PASS"
    print("EMBER_GATE_FULL_PARITY_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
