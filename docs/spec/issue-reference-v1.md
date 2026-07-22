<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Issue-reference normalization v1 (record-coherent, R4 / cond9)

## The fracture

Two issue-numbering eras share the bare `#N` notation:

- the **legacy** tracker used before the project migrated to GitHub, and
- the **github** tracker in use now.

Both trackers number issues from `#1`, so the same string `#207` can denote a
legacy issue *or* a GitHub issue. `receipts/CLAIMS.md` interleaves references
from both eras, and pre-genesis references such as `#207` are cited by current
docs. An unqualified `#N` is therefore **intrinsically ambiguous** whenever `N`
falls inside the legacy range. Any authority / evidence / dispatch decision made
on a mis-resolved reference is silently wrong.

## Canonical forms

Every issue reference resolves to exactly one canonical token:

| Canonical form  | Meaning                                                       |
|-----------------|--------------------------------------------------------------|
| `legacy:<n>`    | issue `<n>` in the legacy (pre-genesis) tracker              |
| `github:<n>`    | issue `<n>` in the current GitHub tracker                    |
| `unknown:<n>`   | number `<n>`, era not determinable from available evidence   |

`<n>` is a bare positive integer with no `#`, no leading zeros. This notation is
adopted deliberately over the earlier `pre#N` sketch: it is greppable, sorts
per-era, and has an explicit third state for the un-resolvable case.

## The genesis boundary

The **genesis boundary** is the migration cut between the two trackers. Because
both eras reuse low numbers, the boundary is *not* a value that a bare number can
be tested against on its own — the boundary is meaningful only together with the
per-number **sidecar mapping** below. Concretely the boundary is defined by a
single non-negative integer `genesis_boundary` = the highest issue number the
legacy tracker ever assigned. Its role:

- `N > genesis_boundary` — the legacy tracker never reached `N`, so a bare `#N`
  can only be a GitHub issue. It resolves to `github:N` **without** a sidecar
  entry.
- `N <= genesis_boundary` — the number lies in the overlap range and a bare `#N`
  is ambiguous. It resolves only via an explicit era qualifier or a sidecar
  entry; otherwise it fails closed (strict) or resolves to `unknown:N` (lenient).

`genesis_boundary` is data, not code — it is carried by the sidecar and set from
the actual migration record. When no sidecar is supplied, `genesis_boundary` is
treated as **+infinity**: every bare number is in the overlap range and every
bare reference is ambiguous. This is the safe default — absence of evidence
never silently promotes a reference to `github:`.

## Sidecar mapping (resolution authority; never mutation)

Historical bytes are **never rewritten**. `#207` stays `#207` in every file it
already appears in. Resolution is layered on top via a sidecar mapping, a JSON
document with this schema:

```json
{
  "genesis_boundary": 0,
  "map": { "207": "legacy", "29": "github" }
}
```

- `genesis_boundary` (int, required when a sidecar is supplied): highest legacy
  issue number.
- `map` (object): bare-number string -> `"legacy" | "github"`. An explicit entry
  overrides the boundary heuristic for that number (it may pin a number `>
  genesis_boundary` to `legacy`, or record the era of an in-overlap number).

The sidecar is the single authority. This reference implementation provides the
mechanism (a library + CLI that consume a sidecar); populating the project's real
sidecar file from the migration record is a separate data task and is out of
scope for v1.

## Resolution rule

Given a raw reference and an optional sidecar, resolve in this order:

1. **Explicit qualifier wins.** `legacy:<n>`, `github:<n>`, `unknown:<n>`, and the
   accepted aliases `L#<n>` / `l#<n>` (legacy) and `gh#<n>` / `GH-<n>` (github)
   canonicalize directly to their era. An explicit qualifier is authoritative and
   needs no sidecar.
2. **Sidecar entry wins next.** If the bare number has an entry in `map`, use it.
3. **Boundary heuristic.** Else if `N > genesis_boundary`, resolve to `github:N`.
4. **Ambiguous.** Else (`N <= genesis_boundary`, no qualifier, no map entry):
   - **strict mode** — FAIL CLOSED (raise / nonzero exit). Authority, evidence,
     and dispatch surfaces MUST call in strict mode.
   - **lenient mode** — resolve to `unknown:N`. Never guess an era.

A malformed reference (no extractable positive integer) fails closed in strict
mode and returns an `unknown:` failure in lenient mode — it is never guessed into
a real era.

## Fail-closed contract

Authority-binding, evidence-index, and dispatch code paths call the library in
**strict mode**. In strict mode an unqualified ambiguous `#N` never resolves to a
concrete era — it stops the operation. A number is promoted to `github:` without a
sidecar entry only when it provably exceeds the legacy range (`> genesis_boundary`),
which requires a sidecar to even be defined. This is the load-bearing property:
the system prefers to halt over to silently cite the wrong issue.
