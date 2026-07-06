# Incidents Ledger

This directory contains the append-only disclosure ledger for the ember invariant system.

## Format

`ledger.jsonl` is an append-only JSONL file. Each row records a violation, incident, or risk disclosed to the invariant record.

### Row structure

```json
{
  "id": "unique-incident-id",
  "severity": "breach|wound|risk",
  "class": "category-name",
  "timestamp": "ISO8601Z",
  "title": "short description",
  "description": "detailed explanation",
  "clauses_affected": ["clause number(s)"],
  "receipts": ["ref/to/receipt1.json", "ref/to/receipt2.json"],
  "status": "disclosed|resolved|waived",
  "quarantine": "ref/to/quarantine/receipt.json"
}
```

- **severity**: `breach` (immediate identity threat), `wound` (integrity impact, survivable if disclosed), `risk` (prospective threat to future work)
- **class**: Classification of the incident (e.g., "data-provenance", "tool-integration", "design-deviation")
- **status**: `disclosed` (now in the ledger), `resolved` (remediation complete), `waived` (explicitly accepted by steward)
- **timestamp**: When the incident was discovered/disclosed, not when it occurred
- **clauses_affected**: References to INVARIANT.md clauses

## Genesis Founding (2026-07-06)

The following five incidents are disclosed at genesis, per the genesis-audit-result.md:

1. **FineWeb-Edu external-model taint** (primary)
   - Severity: wound
   - Class: data-provenance
   - Status: disclosed
   - Affects: INVARIANT clause 3 (CREATION)
   - Impact: All from-scratch checkpoints trained on tainted corpus

2. **SFT-toolagent lineage has no receipted generator**
   - Severity: wound
   - Class: generator-missing
   - Status: disclosed
   - Affects: INVARIANT clause 3 (CREATION)
   - Impact: Unknown provenance of synthetic traces in SFT training

3. **Frozen-design-doc deviation: stack-v2 → codeparrot substitution**
   - Severity: wound
   - Class: design-deviation
   - Status: disclosed
   - Affects: INVARIANT clause 3 (CREATION)
   - Impact: Pinned corpus substitution under time pressure

4. **C-BASE board condition does not audit clause-3 data provenance**
   - Severity: wound
   - Class: board-condition-gap
   - Status: disclosed
   - Affects: INVARIANT clause 3 (CREATION)
   - Impact: Board GREEN could mask data-provenance violations

5. **"Dynamic teacher system" design is a live risk for future work**
   - Severity: risk
   - Class: prospective-risk
   - Status: disclosed
   - Affects: INVARIANT clause 3 (CREATION)
   - Impact: Future SFT infrastructure may violate clause 3 if built as designed

See `genesis-audit-20260706.md` for the full audit report.
