#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for Ember's fail-closed pre-loop resident gate inspector."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_preloop_resident_gate as gate

    with tempfile.TemporaryDirectory(prefix="ember-preloop-gate-selftest-") as td:
        root = Path(td)
        repo = root / "repo"
        paper_root = root / "papers"
        reference_root = root / "the predecessor CLI"

        _write(
            repo / "docs/domains/governance/authority/GOAL.md",
            """
## Current Blocker Packet
Requirement 14 requires clean-room the predecessor CLI resident harness parity, RLM,
iGRPO, actual neural parameter updates, before/after, A/B/C/deleted,
transfer, deletion-sensitive evidence, and no symbolic-template-policy
substitution, prompt-only substitution, scalar dictionary, handcrafted routing,
or RLM/iGRPO-style wording without a neural parameter update.
""",
        )
        _write(
            repo / "docs" / "charter" / "ember-floor-contract.md",
            """
| QAT | Muon | QK-norm | Governor |
| Encoder-free multimodal TRAINING | BitNet / 1.58-bit ternary |
| SDEK / GDN-Jet fast-weight sleep consolidation | MLA / KV-cache compression |
| GRPO / RL-on-verifier-reward | FP8 training | MoE | DiffusionGemma sampler |
""",
        )
        _write(
            repo / "nc2-own-technique-contract.md",
            "QAT turboquant BitNet SubQ sparse attention MTP SDEK Gemma-4 unified multimodal architecture\n",
        )
        _write(
            repo / "scripts" / "train_multimodal_v0.py",
            """
# §6 primitive-typed action-log contract
PRIMITIVES = ["emit-token", "emit-scalar", "emit-pointer", "commit", "stop"]
optimizer = torch.optim.AdamW(all_params, lr=3e-4)
checkpoint = {"model": model.state_dict(), "optimizer": optimizer.state_dict()}
def _model_load_state_dict(model, state): model.load_state_dict(state)
""",
        )

        rlm_dir = paper_root / "recursive-language-models"
        igrpo_dir = paper_root / "igrpo-self-feedback-driven-llm-reasoning"
        _write(rlm_dir / "recursive-language-models-arxiv-abs.html", '<meta name="citation_abstract" content="Recursive Language Models use recursive calls over external context.">')
        _write(igrpo_dir / "igrpo-self-feedback-driven-llm-reasoning-arxiv-abs.html", '<meta name="citation_abstract" content="iGRPO uses self-feedback and verifier reward to refine reasoning.">')
        _write(
            rlm_dir / "source-receipt.json",
            json.dumps(
                {
                    "kind": "RLM",
                    "title": "Recursive Language Models",
                    "arxiv_id": "2512.24601",
                    "files": {
                        "pdf": {"path": str(rlm_dir / "recursive-language-models.pdf"), "sha256": "r" * 64, "bytes": 10},
                        "source": {"path": str(rlm_dir / "recursive-language-models-source.tar"), "sha256": "s" * 64, "bytes": 20},
                        "abs_html": {"path": str(rlm_dir / "recursive-language-models-arxiv-abs.html"), "sha256": "a" * 64, "bytes": 30},
                    },
                },
                indent=2,
            ),
        )
        _write(
            igrpo_dir / "source-receipt.json",
            json.dumps(
                {
                    "kind": "iGRPO",
                    "title": "iGRPO: Self-Feedback-Driven LLM Reasoning",
                    "arxiv_id": "2602.09000",
                    "files": {
                        "pdf": {"path": str(igrpo_dir / "igrpo-self-feedback-driven-llm-reasoning.pdf"), "sha256": "i" * 64, "bytes": 10},
                        "source": {"path": str(igrpo_dir / "igrpo-self-feedback-driven-llm-reasoning-source.tar"), "sha256": "g" * 64, "bytes": 20},
                        "abs_html": {"path": str(igrpo_dir / "igrpo-self-feedback-driven-llm-reasoning-arxiv-abs.html"), "sha256": "b" * 64, "bytes": 30},
                    },
                },
                indent=2,
            ),
        )
        _write(
            paper_root / "INDEX.json",
            json.dumps(
                {
                    "receipt_type": "ember_rlm_igrpo_source_papers",
                    "papers": [
                        {
                            "kind": "RLM",
                            "arxiv_id": "2512.24601",
                            "title": "Recursive Language Models",
                            "receipt": str(rlm_dir / "source-receipt.json"),
                            "pdf_sha256": "r" * 64,
                            "source_sha256": "s" * 64,
                        },
                        {
                            "kind": "iGRPO",
                            "arxiv_id": "2602.09000",
                            "title": "iGRPO: Self-Feedback-Driven LLM Reasoning",
                            "receipt": str(igrpo_dir / "source-receipt.json"),
                            "pdf_sha256": "i" * 64,
                            "source_sha256": "g" * 64,
                        },
                    ],
                },
                indent=2,
            ),
        )
        _write(reference_root / "predecessor-cli.exe", "binary placeholder")

        out = root / "receipt.json"
        receipt = gate.build_receipt(
            repo=repo,
            paper_root=paper_root,
            reference_root=reference_root,
            out=out,
            reference_command_definition=None,
        )

        assert receipt["verdict"] == "PRELOOP_RESIDENT_GATE_BLOCKED"
        assert receipt["gate_allows_loops"] is False
        assert receipt["preconditions"]["clean_room_the predecessor CLI"]["status"] == "BLOCKED"
        assert receipt["preconditions"]["rlm"]["status"] == "BLOCKED"
        assert receipt["preconditions"]["igrpo"]["status"] == "BLOCKED"
        assert receipt["next_missing_precondition"] == "clean_room_the predecessor CLI_resident_harness"
        assert "ember_gate_cleanroom_inventory.py" in receipt["next_executable_command"]
        assert "symbolic-template-policy" in receipt["invalid_substitutions_rejected"]
        assert "scalar dictionary" in receipt["invalid_substitutions_rejected"]
        assert receipt["train_multimodal_inventory"]["has_adamw"] is True
        assert receipt["train_multimodal_inventory"]["has_state_dict"] is True
        assert receipt["train_multimodal_inventory"]["has_action_log_contract"] is True
        assert {row["kind"] for row in receipt["paper_sources_read"]} == {"RLM", "iGRPO"}
        assert all(row["source_receipt_read"] is True for row in receipt["paper_sources_read"])
        assert receipt["floor_contract_manifest"]["BitNet / 1.58-bit ternary"]["status"] in {
            "preserved_trigger_gated",
            "blocked_with_exact_adapter_surface",
        }

    print("EMBER_PRELOOP_RESIDENT_GATE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
