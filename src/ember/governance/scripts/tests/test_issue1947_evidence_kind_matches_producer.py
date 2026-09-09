# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The evidence-kind table must agree with what each producer actually consumes.

`PREDICTION_SOURCE` is deliberately hand-maintained: deriving a row's kind from the row's own
output would let a bundle promote itself, which is the defect the table exists to prevent.  But a
hand-maintained table drifts, and it already has -- in both directions within one week.  First it
counted six asset-integrity rows as model evidence.  The cure for that classified all nine rows as
asset-derived, and two of them consume a designated checkpoint, so the corrected bar under-counted
exactly as far as its predecessor over-counted.  Neither error was visible from the table.

What makes the drift detectable is that the two facts have independent sources.  The table says
what a row's evidence is *claimed* to be; an adapter's signature says what it is *able* to be,
because a producer that never receives `expected_checkpoint_manifest_sha256` cannot bind a
checkpoint and a producer that requires one cannot avoid binding it.  Comparing the two catches a
future row left unclassified in either direction, which is the only reason this file is worth more
than the assertion it replaces.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src" / "ember" / "governance" / "scripts"))
import issue1947_release_execute as execute  # noqa: E402
import issue1947_release_row as producers  # noqa: E402

CHECKPOINT_BINDING_PARAMETER = "expected_checkpoint_manifest_sha256"

# Every protected row and the producer that builds it.  Kept explicit, and then checked against
# `execute.ROWS` below, so a row added to one side and not the other fails here rather than
# silently dropping out of the comparison.
ROW_PRODUCERS = {
    "E-MATRIX-TEXT-LANGUAGE": producers.adapt_text,
    "E-MATRIX-IMAGE": producers.adapt_image,
    "E-MATRIX-AUDIO": producers.adapt_audio,
    "E-MATRIX-IMAGE-TEXT": producers.adapt_image_text,
    "E-MATRIX-AUDIO-TEXT": producers.adapt_audio_text,
    "E-MATRIX-IMAGE-AUDIO-TEXT": producers.adapt_image_audio_text,
    "E-MATRIX-REASONING": producers.adapt_reasoning,
    "E-MATRIX-TOOL-USE": producers.adapt_tool_use,
    "E-MATRIX-ROUTING-PATHWAY": producers.adapt_routing_pathway,
}

CHECKPOINT_DERIVED_KINDS = {execute.MODEL_PREDICTION, execute.PATHWAY_ENGAGEMENT}


def test_every_protected_row_has_exactly_one_named_producer() -> None:
    assert set(ROW_PRODUCERS) == set(execute.ROWS)


@pytest.mark.parametrize("row_id", sorted(ROW_PRODUCERS))
def test_declared_kind_matches_whether_the_producer_binds_a_checkpoint(row_id: str) -> None:
    """The table's claim and the adapter's signature are two independent sources for one fact."""
    binds_checkpoint = CHECKPOINT_BINDING_PARAMETER in inspect.signature(ROW_PRODUCERS[row_id]).parameters
    kind = execute.evidence_kind(row_id)
    if binds_checkpoint:
        assert kind in CHECKPOINT_DERIVED_KINDS, (
            f"{row_id}'s producer requires {CHECKPOINT_BINDING_PARAMETER} and so derives its "
            f"prediction from the designated checkpoint, but the table classifies it {kind}"
        )
    else:
        assert kind == execute.INTEGRITY_PLACEHOLDER, (
            f"{row_id}'s producer never receives {CHECKPOINT_BINDING_PARAMETER}, so it cannot "
            f"produce checkpoint evidence, but the table classifies it {kind}"
        )


def test_the_two_checkpoint_rows_are_the_ones_that_bind_a_checkpoint() -> None:
    """Stated as a fact about today's matrix, so a change to it has to be deliberate."""
    bound = {
        row_id
        for row_id, adapter in ROW_PRODUCERS.items()
        if CHECKPOINT_BINDING_PARAMETER in inspect.signature(adapter).parameters
    }
    assert bound == {"E-MATRIX-TOOL-USE", "E-MATRIX-ROUTING-PATHWAY"}


def test_pathway_engagement_is_checkpoint_derived_and_still_outside_the_bar() -> None:
    """An engagement rate is not capability evidence, and the row says so itself.

    The distinction is the whole reason this kind exists: the routing row is produced by real
    inference against the designated checkpoint, which is what makes it tempting to count, and it
    measures whether declared pathways execute rather than whether the prediction is any good.
    """
    assert execute.evidence_kind("E-MATRIX-ROUTING-PATHWAY") == execute.PATHWAY_ENGAGEMENT
    assert execute.evidence_kind("E-MATRIX-ROUTING-PATHWAY") != execute.MODEL_PREDICTION
    assert "NOT CAPABILITY" in producers.ROUTING_PATHWAY_CLAIM_BOUNDARY


def test_an_unclassified_row_refuses_rather_than_defaulting() -> None:
    with pytest.raises(execute.ReleaseExecutionRefusal):
        execute.evidence_kind("E-MATRIX-NOT-A-ROW")
