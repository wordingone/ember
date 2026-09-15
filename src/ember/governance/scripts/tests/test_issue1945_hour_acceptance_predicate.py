#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for #1945's hour-acceptance predicate.

WHAT THIS GUARDS. The 2026-09-13 gate-B audit found that nothing in the repository read the
governed hour's p10, that `cia_hour.hour_complete` contains no rate term at all, and that the
string 80,000 appeared nowhere in `src/` as a threshold. This predicate is the consumer that
closes the first of those. A consumer with no test is the same defect one layer over, so the
cases below pin the three things a reader would otherwise have to take on trust:

  1. the p10 STATISTIC, against hand-computed nearest-rank values including the boundary sizes
     where an off-by-one in `ceil(0.1 * n) - 1` would change the answer;
  2. the three STATUSES, and specifically that ACCEPTED is unreachable from throughput alone --
     revision 1 printed ACCEPTED on a throughput pass and that is the regression this pins;
  3. the REFUSAL paths, including one deliberate red through `main` proving the tool exits
     non-zero and writes a REFUSED payload rather than a silent no-op.

The predicate's own constants are asserted too. They are the bar, they are quoted in the issue
and in the operating rules, and a test suite that lets them drift while passing would be worse
than none.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
PREDICATE = (REPO_ROOT / "src" / "ember" / "governance" / "scripts"
             / "issue1945_hour_acceptance_predicate.py")


def load_predicate_module():
    spec = importlib.util.spec_from_file_location("hour_acceptance_under_test", PREDICATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def predicate():
    assert PREDICATE.is_file(), "predicate source is missing: %s" % PREDICATE
    return load_predicate_module()


# --------------------------------------------------------------------------------------------
# 1. The bar itself.
# --------------------------------------------------------------------------------------------

def test_constants_are_the_bar(predicate):
    """These four values ARE #1945's gate A and gate B. Drift here is a silent bar change."""
    assert predicate.TERMINAL_POSITIONS_PER_SECOND == 80000.0
    assert predicate.MINIMUM_WARMED_UPDATES == 1024
    assert predicate.MINIMUM_GOVERNED_SECONDS == 3600.0
    assert predicate.HOUR_SCHEMA == "ember-cia-hour-result-v1"


# --------------------------------------------------------------------------------------------
# 2. The statistic.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "values,expected",
    [
        # n=10: ceil(1.0) - 1 = 0 -> the smallest value.
        (list(range(10, 110, 10)), 10),
        # n=1: the only value, whatever it is.
        ([42.0], 42.0),
        # n=9: ceil(0.9) - 1 = 0 -> still the smallest. The boundary an off-by-one moves.
        (list(range(1, 10)), 1),
        # n=11: ceil(1.1) - 1 = 1 -> the SECOND smallest.
        (list(range(1, 12)), 2),
        # n=20: ceil(2.0) - 1 = 1 -> the second smallest.
        (list(range(1, 21)), 2),
        # Order of the input must not matter.
        ([5, 1, 4, 2, 3, 9, 8, 7, 6, 10], 1),
    ],
)
def test_nearest_rank_p10(predicate, values, expected):
    assert predicate.nearest_rank_p10(list(values)) == expected


def test_nearest_rank_p10_is_a_tenth_not_a_mean(predicate):
    """A p10 of a skewed sample must track the slow tail, not the average.

    Nine fast steps and one slow one average fast; the p10 is the slow one. Reporting a mean here
    would let a run with a pathological tail qualify, which is the whole reason the bar names p10.
    """
    assert predicate.nearest_rank_p10([100.0] + [1000.0] * 9) == 100.0


# --------------------------------------------------------------------------------------------
# 3. The three statuses. ACCEPTED must be unreachable from throughput alone.
# --------------------------------------------------------------------------------------------

def _payload(*, composed: bool, throughput: bool) -> dict:
    return {"composed_acceptance": {"met": composed},
            "throughput_subverdict": {"met": throughput}}


def test_status_accepted_requires_composed_acceptance(predicate):
    assert predicate.status_of(_payload(composed=True, throughput=True)) == "ACCEPTED"


def test_status_throughput_alone_is_not_accepted(predicate):
    """The revision-1 regression, pinned.

    A qualifying rate whose licence, Evaluation and custody verdicts have not been read is
    THROUGHPUT_MET_COMPOSITION_NOT_ESTABLISHED. It is not a pass, and it must never render as one.
    """
    assert (predicate.status_of(_payload(composed=False, throughput=True))
            == "THROUGHPUT_MET_COMPOSITION_NOT_ESTABLISHED")


def test_status_below_threshold(predicate):
    assert (predicate.status_of(_payload(composed=False, throughput=False))
            == "THROUGHPUT_NOT_MET")


def test_only_three_statuses_are_reachable(predicate):
    """Every combination of the two sub-verdicts lands in the declared set, with no fourth state."""
    seen = {predicate.status_of(_payload(composed=c, throughput=t))
            for c in (True, False) for t in (True, False)}
    assert seen == {"ACCEPTED",
                    "THROUGHPUT_MET_COMPOSITION_NOT_ESTABLISHED",
                    "THROUGHPUT_NOT_MET"}


# --------------------------------------------------------------------------------------------
# 4. Refusals.
# --------------------------------------------------------------------------------------------

def test_refusal_token_must_be_declared(predicate):
    """An undeclared token is an assertion failure, so a typo cannot become a silent new state."""
    with pytest.raises(AssertionError):
        predicate.Refusal("token:that:is:not:declared", "detail")


def test_refusal_carries_its_token_and_detail(predicate):
    token = sorted(predicate.TOKENS)[0]
    refusal = predicate.Refusal(token, "a detail", observed=1, expected=2)
    assert refusal.token == token
    assert refusal.detail == "a detail"
    assert (refusal.observed, refusal.expected) == (1, 2)


def test_read_json_refuses_an_absent_file(predicate, tmp_path):
    with pytest.raises(predicate.Refusal) as excinfo:
        predicate.read_json(tmp_path / "nope.json", "input:hour-result-absent", "input:hour-result-unreadable")
    assert excinfo.value.token == "input:hour-result-absent"


def test_read_json_refuses_unparseable_bytes(predicate, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(predicate.Refusal) as excinfo:
        predicate.read_json(bad, "input:hour-result-absent", "input:hour-result-unreadable")
    assert excinfo.value.token == "input:hour-result-unreadable"


# --------------------------------------------------------------------------------------------
# 5. The deliberate red through main(), which is the leg that proves the gate can FAIL.
# --------------------------------------------------------------------------------------------

def test_main_refuses_and_exits_nonzero_on_an_absent_hour_result(predicate, tmp_path):
    """real-path-closure clause 5: a gate ships with one proven red.

    A refusal that exits 0 is a silent no-op, and this repository has shipped one before. This
    case asserts the exit code AND the written payload, because a tool that prints REFUSED while
    returning success gates nothing.
    """
    out = tmp_path / "verdict.json"
    code = predicate.main([
        "--hour-result", str(tmp_path / "absent-hour.json"),
        "--rows", str(tmp_path / "absent-rows.jsonl"),
        "--out", str(out),
    ])
    assert code != 0, "a refusal that exits 0 gates nothing"
    assert out.is_file(), "the refusal must be written, not only printed"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "REFUSED"
    assert payload["token"] in predicate.TOKENS
    assert payload["schema"] == "ember-1945-hour-acceptance-v2"
