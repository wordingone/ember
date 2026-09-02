# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generic gate-invariant checker.

Generalizes RESEARCH_WORKFLOW.md:33-44's fail-closed gate assertions (every
harness independently checks n_leaves/budget/space_hash/prev_space_hash
before trusting a canonical run) from hardcoded Python asserts scattered
across ~986 single-instance probe scripts into data: a node's
`gate_invariants` array, checked here by one shared function instead of by
every new `fpNN_*.py` reimplementing the same checks by hand.

Three invariant forms, matching the schema sketch:
  - {"field": F, "asserted": true}
        F must be present and non-null in `result` -- it was independently
        computed/asserted rather than assumed or hardcoded.
  - {"field": F, "expect": "unchanged"}
        result[F] must equal baseline[F] (the same field's value from a
        supplied baseline dict, e.g. the prior stage's recorded result).
  - {"field": F, "expect_equals": "<node_id>.<other_field>"}
        result[F] must equal prior_node_outputs[node_id][other_field] --
        the chain-integrity check (prev_space_hash chaining to a named
        prior node's output_hash).

Fail-closed on the unrecognized (review-pr1310.md MEDIUM-1): a gate
invariant is meant to be a hard check, so an invariant this checker cannot
interpret -- an `expect` value that isn't `"unchanged"` (a typo, or a form
this version doesn't implement), or a `{"field": F}` entry that carries none
of the three directive keys at all -- is reported as a problem, never
silently skipped. The prior version of this function let both of those cases
fall through every branch untouched and returned `ok=True`, which is the
worst failure mode for a fail-closed gate system: the node looks gated and
isn't. `expect` is also enum-restricted to `["unchanged"]` in
execution-graph-v1.schema.json so the same typo is caught at validation
time, before it ever reaches this function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_KNOWN_EXPECT_VALUES = {"unchanged"}


@dataclass
class GateResult:
    ok: bool
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems)}


def check_gate_invariants(
    gate_invariants: list[dict[str, Any]],
    result: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    prior_node_outputs: dict[str, dict[str, Any]] | None = None,
) -> GateResult:
    problems: list[str] = []
    baseline = baseline or {}
    prior_node_outputs = prior_node_outputs or {}

    for invariant in gate_invariants:
        field_name = invariant.get("field")
        if not field_name:
            problems.append(f"gate invariant missing 'field': {invariant!r}")
            continue

        recognized = False

        if "asserted" in invariant:
            recognized = True
            if invariant["asserted"]:
                if field_name not in result or result[field_name] is None:
                    problems.append(f"{field_name!r}: expected an independently asserted value, none present in result")

        if "expect" in invariant:
            recognized = True
            expect_value = invariant["expect"]
            if expect_value not in _KNOWN_EXPECT_VALUES:
                problems.append(
                    f"{field_name!r}: unrecognized expect directive {expect_value!r} "
                    f"(fail-closed; known values: {sorted(_KNOWN_EXPECT_VALUES)})"
                )
            elif expect_value == "unchanged":
                if field_name not in baseline:
                    problems.append(f"{field_name!r}: expect:unchanged but no baseline value was supplied")
                elif result.get(field_name) != baseline.get(field_name):
                    problems.append(
                        f"{field_name!r}: expected unchanged from baseline ({baseline.get(field_name)!r}), "
                        f"got {result.get(field_name)!r}"
                    )

        expect_equals = invariant.get("expect_equals")
        if expect_equals:
            recognized = True
            if "." not in expect_equals:
                problems.append(f"{field_name!r}: malformed expect_equals reference {expect_equals!r} (want <node_id>.<field>)")
            else:
                ref_node_id, ref_field = expect_equals.rsplit(".", 1)
                ref_outputs = prior_node_outputs.get(ref_node_id)
                if ref_outputs is None:
                    problems.append(f"{field_name!r}: expect_equals references unknown node {ref_node_id!r}")
                elif ref_field not in ref_outputs:
                    problems.append(f"{field_name!r}: node {ref_node_id!r} has no output field {ref_field!r}")
                elif result.get(field_name) != ref_outputs[ref_field]:
                    problems.append(
                        f"{field_name!r}: expected to equal {expect_equals} ({ref_outputs[ref_field]!r}), "
                        f"got {result.get(field_name)!r}"
                    )

        if not recognized:
            problems.append(
                f"{field_name!r}: gate invariant has no recognized directive (fail-closed): {invariant!r}"
            )

    return GateResult(ok=not problems, problems=problems)
