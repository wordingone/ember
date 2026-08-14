# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Strict SPDX-expression gate for declared corpus-source licences (issue #1720).

Why this exists: a source's licence was recorded as a free-form string and
checked, if at all, by three different pieces of code that disagreed with each
other. Nine of thirteen landed rows carried a licence the training-admission
allow-list does not contain, and two of those nine were not policy questions at
all -- they were malformed SPDX (``-OR-``/``-WITH-`` written with hyphens where
SPDX requires spaces), which every string comparison in the tree silently read
as one unknown identifier.

Two design rules follow from that history:

1. **Bind, never copy.** The admission allow-list lives in
   ``tools/ember-restart-3b/text_lab_corpus.py`` and is read here at call time.
   This module holds no licence identifiers of its own. A fourth disagreeing
   copy of the allow-list is the bug this gate exists to prevent.
2. **Separate syntax from policy.** A malformed expression is a defect and
   raises. A well-formed expression outside the allow-list is *reported*, not
   refused -- admission is the allow-list owner's decision, not this module's.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]
_ADMISSION_DIR = _ROOT / "tools" / "ember-restart-3b"

OPERATORS = ("OR", "AND", "WITH")

# Exceptions judged not to alter the redistribution or training posture of their
# base licence. Seeded with the one exception an acquired row actually carries;
# widening it is a ruling, not a code change made in passing.
BENIGN_EXCEPTIONS = frozenset({"LLVM-exception"})

ADMITTED = "ADMITTED"
NOT_ALLOWED = "NOT_ALLOWED"
ELECTION_MISSING = "ELECTION_MISSING"
ELECTION_NOT_A_BRANCH = "ELECTION_NOT_A_BRANCH"
ELECTION_NOT_ALLOWED = "ELECTION_NOT_ALLOWED"
ELECTION_NOT_APPLICABLE = "ELECTION_NOT_APPLICABLE"
EXCEPTION_NOT_BENIGN = "EXCEPTION_NOT_BENIGN"
MALFORMED = "MALFORMED"

#: Statuses that indicate a defect in the row rather than a policy gap. A caller
#: enforcing the gate should fail on these; NOT_ALLOWED is a report.
DEFECT_STATUSES = frozenset(
    {
        MALFORMED,
        ELECTION_MISSING,
        ELECTION_NOT_A_BRANCH,
        ELECTION_NOT_ALLOWED,
        ELECTION_NOT_APPLICABLE,
        EXCEPTION_NOT_BENIGN,
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_HYPHENATED_OPERATOR_RE = re.compile(r"-(OR|AND|WITH)-", re.IGNORECASE)


class MalformedExpressionError(ValueError):
    """The declared licence is not a parseable SPDX expression."""


@dataclass(frozen=True)
class Term:
    """One SPDX identifier, optionally carrying a ``WITH`` exception."""

    identifier: str
    exception: Optional[str] = None

    @property
    def text(self) -> str:
        return f"{self.identifier} WITH {self.exception}" if self.exception else self.identifier


@dataclass(frozen=True)
class Expression:
    operator: Optional[str]  # "OR", "AND", or None for a single term
    terms: Tuple[Term, ...]


@dataclass(frozen=True)
class Verdict:
    expression: str
    status: str
    elected: Optional[str]
    detail: str

    @property
    def admitted(self) -> bool:
        return self.status == ADMITTED


@dataclass(frozen=True)
class AuditRow:
    name: str
    expression: str
    status: str
    elected: Optional[str]
    detail: str


def allowed_licenses() -> frozenset:
    """The live training-admission allow-list, read from its owning module.

    Deliberately re-read on every call: widening the authority set must move
    this gate with no edit here.
    """
    if str(_ADMISSION_DIR) not in sys.path:
        sys.path.insert(0, str(_ADMISSION_DIR))
    import text_lab_corpus  # noqa: PLC0415 -- lazy so importing this module is side-effect free

    return frozenset(text_lab_corpus.LICENSES)


def _reject(expression: str, reason: str) -> "MalformedExpressionError":
    return MalformedExpressionError(f"{expression!r}: {reason}")


def _check_token(expression: str, token: str) -> None:
    hyphenated = _HYPHENATED_OPERATOR_RE.search(token)
    if hyphenated:
        corrected = _HYPHENATED_OPERATOR_RE.sub(lambda m: f" {m.group(1).upper()} ", token)
        raise _reject(
            expression,
            f"SPDX operators are space-delimited, not hyphenated; write {corrected!r}",
        )
    if token.upper() in OPERATORS and token not in OPERATORS:
        raise _reject(expression, f"SPDX operators are uppercase; {token!r} is not an operator")
    if "+" in token:
        raise _reject(
            expression,
            f"{token!r} uses the '+' or-later suffix, which claims licences that do not exist yet",
        )
    if not _IDENTIFIER_RE.match(token):
        raise _reject(expression, f"{token!r} is not a valid SPDX identifier")


def _parse_term(expression: str, group: Sequence[str]) -> Term:
    if len(group) == 1 and group[0] not in OPERATORS:
        return Term(group[0])
    if len(group) == 3 and group[1] == "WITH" and group[0] not in OPERATORS and group[2] not in OPERATORS:
        return Term(group[0], group[2])
    joined = " ".join(group)
    raise _reject(expression, f"{joined!r} is not an identifier or an identifier WITH an exception")


def parse(expression: str) -> Expression:
    """Parse a strict subset of SPDX. Anything outside it refuses fail-closed."""
    if not isinstance(expression, str) or not expression.strip():
        raise _reject(expression, "licence expression is empty")
    raw = expression.strip()
    if "(" in raw or ")" in raw:
        raise _reject(raw, "parenthesised expressions are not supported by this gate")

    tokens = raw.split()
    for token in tokens:
        _check_token(raw, token)

    top_level = {t for t in tokens if t in ("OR", "AND")}
    if len(top_level) > 1:
        raise _reject(raw, "mixes OR and AND at one level, so its precedence is ambiguous")
    operator = next(iter(top_level), None)

    groups: List[List[str]] = [[]]
    for token in tokens:
        if token == operator:
            groups.append([])
        else:
            groups[-1].append(token)
    if any(not g for g in groups):
        raise _reject(raw, f"has a missing operand around {operator!r}")

    return Expression(operator, tuple(_parse_term(raw, g) for g in groups))


def _check_term(term: Term, allowed: frozenset) -> Tuple[bool, str]:
    if term.identifier not in allowed:
        return False, NOT_ALLOWED
    if term.exception is not None and term.exception not in BENIGN_EXCEPTIONS:
        return False, EXCEPTION_NOT_BENIGN
    return True, ADMITTED


def evaluate(expression: str, *, elected: Optional[str] = None) -> Verdict:
    """Decide a declared licence against the live admission allow-list.

    ``elected`` names which branch of an ``OR`` the row has chosen to take. An
    ``OR`` with no recorded election is not admitted: a choice nobody made is
    not a licence.
    """
    parsed = parse(expression)
    raw = expression.strip()
    allowed = allowed_licenses()

    if parsed.operator == "OR":
        branches = {t.text: t for t in parsed.terms}
        if elected is None:
            return Verdict(
                raw,
                ELECTION_MISSING,
                None,
                f"choice of {sorted(branches)} is unrecorded; the row must elect one branch",
            )
        if elected not in branches:
            return Verdict(
                raw, ELECTION_NOT_A_BRANCH, elected, f"{elected!r} is not one of {sorted(branches)}"
            )
        ok, status = _check_term(branches[elected], allowed)
        if ok:
            return Verdict(raw, ADMITTED, elected, f"elected branch {elected!r} is allow-listed")
        if any(_check_term(t, allowed)[0] for t in parsed.terms):
            return Verdict(
                raw,
                ELECTION_NOT_ALLOWED,
                elected,
                f"elected {elected!r} ({status}) while an allow-listed branch was available",
            )
        return Verdict(raw, status, elected, f"no branch of {sorted(branches)} is allow-listed")

    if elected is not None:
        return Verdict(
            raw, ELECTION_NOT_APPLICABLE, elected, "an election was recorded but the licence offers no choice"
        )

    for term in parsed.terms:
        ok, status = _check_term(term, allowed)
        if not ok:
            detail = (
                f"exception {term.exception!r} is not on the benign-exception list"
                if status == EXCEPTION_NOT_BENIGN
                else f"{term.identifier!r} is not in the training-admission allow-list"
            )
            return Verdict(raw, status, None, detail)
    return Verdict(raw, ADMITTED, None, "every term is allow-listed")


def audit(name: str, expression: str, elected: Optional[str] = None) -> AuditRow:
    try:
        verdict = evaluate(expression, elected=elected)
    except MalformedExpressionError as exc:
        return AuditRow(name, expression, MALFORMED, elected, str(exc))
    return AuditRow(name, verdict.expression, verdict.status, verdict.elected, verdict.detail)


def _wave_manifest():
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import wave_manifest  # noqa: PLC0415

    return wave_manifest


def audit_wave_sources(sources: Optional[Iterable] = None) -> List[AuditRow]:
    """Audit each source's real ``--license`` argv value, not a parallel table."""
    if sources is None:
        sources = _wave_manifest().WAVE2_SOURCES
    rows: List[AuditRow] = []
    for source in sources:
        argv = list(source.argv)
        if "--license" not in argv:
            continue
        rows.append(
            audit(
                source.name,
                argv[argv.index("--license") + 1],
                getattr(source, "license_elected", None) or None,
            )
        )
    return rows


def audit_bulk_veins(veins: Optional[Iterable] = None) -> List[AuditRow]:
    """Audit the value each bulk vein passes as ``--license``.

    ``BulkVein.build_argv`` forwards ``license_basis`` -- a human-readable
    sentence -- straight into the SPDX field, so every vein currently audits
    MALFORMED. That is a real gap in the vein schema, not a gate defect.
    """
    if veins is None:
        veins = _wave_manifest().WAVE2_BULK_VEINS
    return [audit(v.name, v.license_basis) for v in veins]


def main(argv: Optional[Sequence[str]] = None) -> int:
    rows = audit_wave_sources() + audit_bulk_veins()
    width = max(len(r.name) for r in rows)
    for row in rows:
        print(f"{row.name:<{width}}  {row.status:<24}  {row.expression}")
        if row.status in DEFECT_STATUSES:
            print(f"{'':<{width}}  -> {row.detail}")
    return 1 if any(r.status in DEFECT_STATUSES for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
