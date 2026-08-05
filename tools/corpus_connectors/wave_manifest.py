#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""wave_manifest.py -- issue #1439 wave-2 source table as executable routing.

Encodes the per-charter-domain source table from the corpus sizing plan's
"Wave-2 source list -- REBOUND to docs/ai-lab-corpus-charter.md" section
(operator directive 2026-08-04, referenced from issue #1439) as data, plus
a driver that turns
each named source into the exact connector CLI invocation that fetches it --
so the routing decision ("this source uses arxiv_fetch with these flags")
lives in one reviewable place instead of being re-derived by hand at fetch
time.

This module does not perform any network I/O itself. It only:
  1. holds `WAVE2_SOURCES` -- one entry per named source, with its charter
     domain letter(s), a license basis note, the connector that fetches it,
     and the concrete argv for that connector;
  2. `build_argv(source)` returns that argv as a list of strings, ready to
     hand to `subprocess.run` or print for a dry run;
  3. `iter_sources(domain=None)` filters `WAVE2_SOURCES` by charter domain
     letter;
  4. a CLI (`--domain LETTER`, `--dry-run` default, `--execute` to actually
     shell out) prints or runs the routed commands.

`--dry-run` is the default specifically because this module's job in this PR
is the routing table and its tests, not a live multi-source pull (fetch
execution against real bulk sources is its own, later, disk/time-bounded
op). `--execute` is provided for completeness and reuses each connector's
own CLI (via `subprocess.run([sys.executable, connector_script, *argv])`),
so it inherits every connector's own license/receipt/fail-closed behavior
unchanged -- this module adds no separate execution path of its own.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent

CHARTER_DOMAINS = {
    "A": "Math",
    "B": "Stats/Inference",
    "C": "Physics/Dynamics",
    "D": "CS/Systems",
    "E": "ML/AI",
    "F": "Training-infra/CUDA/HW",
    "G": "Logic/Proof",
    "H": "SWE",
    "I": "Data/Eval/Decon",
    "J": "Sci-method/Lab-ops",
    "K": "Application worlds",
    "baseline": "cross-domain reference register",
}

CONNECTOR_SCRIPTS = {
    "arxiv_fetch": HERE / "arxiv_fetch.py",
    "http_fetch": HERE / "http_fetch.py",
    "openreview_fetch": HERE / "openreview_fetch.py",
    "hf_fetch": HERE / "hf_fetch.py",
    "bulk_fetch": HERE / "bulk_fetch.py",
}


@dataclass(frozen=True)
class WaveSource:
    """One named source from the wave-2 table, routed to one connector call."""

    name: str
    domains: tuple  # charter domain letters this source counts toward
    license_basis: str
    connector: str  # key into CONNECTOR_SCRIPTS
    argv: tuple  # connector-specific argv, NOT including the script path/python
    est_tokens_low_b: float
    est_tokens_high_b: float
    notes: str = ""

    def __post_init__(self) -> None:
        if self.connector not in CONNECTOR_SCRIPTS:
            raise ValueError(f"{self.name}: unknown connector {self.connector!r}")
        for d in self.domains:
            if d not in CHARTER_DOMAINS:
                raise ValueError(f"{self.name}: unknown charter domain {d!r}")
        if not self.argv:
            raise ValueError(f"{self.name}: argv must not be empty")
        if self.est_tokens_low_b <= 0 or self.est_tokens_high_b < self.est_tokens_low_b:
            raise ValueError(f"{self.name}: est_tokens bounds must be positive and ordered")


# Per-domain source table, transcribed from corpus-sizing-v1.md's "Wave-2
# source list" (operator-directed 2026-08-04, REBOUND to
# docs/ai-lab-corpus-charter.md). Only the sub-512MiB-per-fetch sources are
# routed through the ordinary single-shot connectors here; the six bulk
# veins (arXiv full-text bulk, PMC OA packages, StackExchange dumps, US
# federal bulk, large textbook archives, Wikipedia) route through
# bulk_fetch.py and are sized/gated by a per-wave --budget-bytes decided at
# dispatch time, not hardcoded in this table -- see WAVE2_BULK_VEINS below.
WAVE2_SOURCES: List[WaveSource] = [
    WaveSource(
        name="arxiv-math-metadata",
        domains=("A",),
        license_basis="arXiv per-paper license (CC-only content filter)",
        connector="arxiv_fetch",
        argv=("--query", "cat:math.*", "--max", "50", "--what", "meta"),
        est_tokens_low_b=3.0,
        est_tokens_high_b=8.0,
        notes="breadth pass; depth pass raises --max under the per-wave disk budget",
    ),
    WaveSource(
        name="openstax-math",
        domains=("A",),
        license_basis="CC-BY (OpenStax)",
        connector="http_fetch",
        argv=(
            "https://openstax.org/exports/precalculus.pdf",
            "--license", "CC-BY-4.0",
            "--license-evidence", "OpenStax textbook page license notice",
        ),
        est_tokens_low_b=0.05,
        est_tokens_high_b=0.15,
    ),
    WaveSource(
        name="arxiv-stat-metadata",
        domains=("B",),
        license_basis="arXiv per-paper license (CC-only content filter)",
        connector="arxiv_fetch",
        argv=("--query", "cat:stat.*", "--max", "50", "--what", "meta"),
        est_tokens_low_b=1.0,
        est_tokens_high_b=3.0,
    ),
    WaveSource(
        name="nist-sematech-handbook",
        domains=("B",),
        license_basis="US-gov public domain",
        connector="http_fetch",
        argv=(
            "https://www.itl.nist.gov/div898/handbook/index.htm",
            "--license", "public-domain-us-gov",
            "--license-evidence", "NIST/SEMATECH e-Handbook front matter",
        ),
        est_tokens_low_b=0.1,
        est_tokens_high_b=0.3,
    ),
    WaveSource(
        name="arxiv-physics-metadata",
        domains=("C",),
        license_basis="arXiv per-paper license (CC-only content filter)",
        connector="arxiv_fetch",
        argv=("--query", "cat:physics.* OR cat:cond-mat.* OR cat:nlin.*", "--max", "50", "--what", "meta"),
        est_tokens_low_b=2.0,
        est_tokens_high_b=6.0,
    ),
    WaveSource(
        name="arxiv-cs-systems-metadata",
        domains=("D",),
        license_basis="arXiv per-paper license (CC-only content filter)",
        connector="arxiv_fetch",
        argv=("--query", "cat:cs.DS OR cat:cs.OS OR cat:cs.DC OR cat:cs.DB OR cat:cs.NI", "--max", "50", "--what", "meta"),
        est_tokens_low_b=3.0,
        est_tokens_high_b=8.0,
    ),
    WaveSource(
        name="llvm-docs",
        domains=("F",),
        license_basis="Apache-2.0 (LLVM)",
        connector="http_fetch",
        argv=(
            "https://llvm.org/docs/",
            "--license", "Apache-2.0",
            "--license-evidence", "LLVM docs repository LICENSE.txt",
        ),
        est_tokens_low_b=0.05,
        est_tokens_high_b=0.2,
    ),
    WaveSource(
        name="arxiv-ml-metadata",
        domains=("E",),
        license_basis="arXiv per-paper license (CC-only content filter)",
        connector="arxiv_fetch",
        argv=("--query", "cat:cs.LG OR cat:cs.AI OR cat:cs.CL OR cat:cs.CV OR cat:cs.NE", "--max", "50", "--what", "meta"),
        est_tokens_low_b=8.0,
        est_tokens_high_b=20.0,
    ),
    WaveSource(
        name="openreview-neurips",
        domains=("E",),
        license_basis="OpenReview per-note resolved license (license-clean PDFs only)",
        connector="openreview_fetch",
        argv=("--venue", "NeurIPS.cc/2025/Conference", "--what", "meta"),
        est_tokens_low_b=1.0,
        est_tokens_high_b=4.0,
    ),
    WaveSource(
        name="metamath-set-mm",
        domains=("G",),
        license_basis="CC0 (Metamath set.mm)",
        connector="http_fetch",
        argv=(
            "https://raw.githubusercontent.com/metamath/set.mm/develop/set.mm",
            "--license", "CC0-1.0",
            "--license-evidence", "metamath/set.mm repository LICENSE",
        ),
        est_tokens_low_b=0.1,
        est_tokens_high_b=0.3,
    ),
    WaveSource(
        name="lean-mathlib-docs",
        domains=("G",),
        license_basis="Apache-2.0 (mathlib4)",
        connector="http_fetch",
        argv=(
            "https://leanprover-community.github.io/mathlib4_docs/",
            "--license", "Apache-2.0",
            "--license-evidence", "mathlib4 repository LICENSE",
        ),
        est_tokens_low_b=0.2,
        est_tokens_high_b=0.6,
    ),
    WaveSource(
        name="arxiv-dataset-eval-metadata",
        domains=("I",),
        license_basis="arXiv per-paper license (CC-only content filter)",
        connector="arxiv_fetch",
        argv=("--query", "abs:benchmark AND abs:dataset", "--max", "50", "--what", "meta"),
        est_tokens_low_b=0.5,
        est_tokens_high_b=2.0,
    ),
    WaveSource(
        name="hf-dataset-cards-eval",
        domains=("I",),
        license_basis="per-card HF license metadata",
        connector="hf_fetch",
        argv=("openai/gsm8k", "--dataset"),
        est_tokens_low_b=0.05,
        est_tokens_high_b=0.2,
        notes="representative card; per-wave dispatch expands this to the full I-domain card list",
    ),
    WaveSource(
        name="ros-docs",
        domains=("K",),
        license_basis="CC-BY (ROS wiki/docs)",
        connector="http_fetch",
        argv=(
            "https://docs.ros.org/en/rolling/index.html",
            "--license", "CC-BY-3.0",
            "--license-evidence", "ROS documentation footer license notice",
        ),
        est_tokens_low_b=0.1,
        est_tokens_high_b=0.3,
    ),
]


@dataclass(frozen=True)
class BulkVein:
    """One of the six deep bulk veins from corpus-sizing-v1.md's depth plan.

    These route through bulk_fetch.py (issue #1440's resumable chunked-bulk
    transport), which requires --budget-bytes at dispatch time -- there is
    deliberately no default budget baked in here; a wave dispatch names its
    own per-run cap under the <=50GB/wave charter rule.
    """

    name: str
    domains: tuple
    license_basis: str
    url: str
    est_tokens_low_b: float
    est_tokens_high_b: float

    def __post_init__(self) -> None:
        for d in self.domains:
            if d not in CHARTER_DOMAINS:
                raise ValueError(f"{self.name}: unknown charter domain {d!r}")
        if not self.url:
            raise ValueError(f"{self.name}: url must not be empty")

    def build_argv(self, budget_bytes: int) -> tuple:
        if budget_bytes <= 0:
            raise ValueError(f"{self.name}: budget_bytes must be positive")
        return (
            self.url,
            "--budget-bytes", str(budget_bytes),
            "--license", self.license_basis,
            "--license-evidence", f"{self.name} named-source license determination (wave_manifest.py)",
        )


WAVE2_BULK_VEINS: List[BulkVein] = [
    BulkVein(
        name="arxiv-fulltext-bulk",
        domains=("A", "B", "C", "D", "E", "F", "I"),
        license_basis="arXiv bulk access terms (per-paper CC filter applied downstream)",
        url="https://arxiv.org/help/bulk_data",
        est_tokens_low_b=18.0,
        est_tokens_high_b=25.0,
    ),
    BulkVein(
        name="pmc-oa-comm-use",
        domains=("J", "C", "E"),
        license_basis="PMC Open Access commercial-use subset (CC-BY/CC0)",
        url="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/",
        est_tokens_low_b=8.0,
        est_tokens_high_b=15.0,
    ),
    BulkVein(
        name="stackexchange-charter-sites",
        domains=("A", "B", "C", "D", "E", "H", "K"),
        license_basis="CC-BY-SA-4.0 (Stack Exchange data dump license)",
        url="https://archive.org/download/stackexchange",
        est_tokens_low_b=10.0,
        est_tokens_high_b=18.0,
    ),
    BulkVein(
        name="us-federal-technical-pd",
        domains=("C", "F", "J"),
        license_basis="US-gov public domain (NASA NTRS / DOE OSTI / NIST / USGS-NOAA)",
        url="https://ntrs.nasa.gov/api/citations/search",
        est_tokens_low_b=4.0,
        est_tokens_high_b=8.0,
    ),
    BulkVein(
        name="open-textbooks-reference",
        domains=("A", "B", "C", "D", "G"),
        license_basis="CC-BY / public-domain (OpenStax/LibreTexts CC-BY subset/Wikibooks/Stacks Project/nLab)",
        url="https://openstax.org/api/v2/pages/",
        est_tokens_low_b=3.0,
        est_tokens_high_b=6.0,
    ),
    BulkVein(
        name="wikipedia-en-baseline",
        domains=("baseline",),
        license_basis="CC-BY-SA-4.0 (Wikipedia EN dump)",
        url="https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2",
        est_tokens_low_b=4.0,
        est_tokens_high_b=5.0,
    ),
]


def build_argv(source: WaveSource) -> List[str]:
    """Return the full argv (connector script path first) for one source."""
    script = CONNECTOR_SCRIPTS[source.connector]
    return [str(script), *source.argv]


def iter_sources(domain: Optional[str] = None) -> List[WaveSource]:
    if domain is None:
        return list(WAVE2_SOURCES)
    return [s for s in WAVE2_SOURCES if domain in s.domains]


def iter_bulk_veins(domain: Optional[str] = None) -> List[BulkVein]:
    if domain is None:
        return list(WAVE2_BULK_VEINS)
    return [v for v in WAVE2_BULK_VEINS if domain in v.domains]


def domains_covered() -> set:
    """Every charter domain letter with at least one routed single-shot source
    or bulk vein -- used by tests to assert the table's charter-coverage
    claim rather than trust the prose above it."""
    covered = set()
    for s in WAVE2_SOURCES:
        covered.update(s.domains)
    for v in WAVE2_BULK_VEINS:
        covered.update(v.domains)
    return covered


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Route wave-2 charter-domain sources to their connector CLI invocations (issue #1439)."
    )
    p.add_argument("--domain", default=None, choices=sorted(CHARTER_DOMAINS), help="filter to one charter domain letter")
    p.add_argument("--include-bulk", action="store_true", help="also list the six bulk veins (no budget dispatched by default)")
    p.add_argument("--bulk-budget-bytes", type=int, default=None, help="required with --include-bulk --execute")
    p.add_argument("--execute", action="store_true", help="actually run each routed connector (default: print only)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    sources = iter_sources(args.domain)
    for s in sources:
        cmd = [sys.executable, *build_argv(s)]
        print(f"# {s.name} ({','.join(s.domains)}) [{s.license_basis}]")
        print(" ".join(cmd))
        if args.execute:
            subprocess.run(cmd, check=True)
    if args.include_bulk:
        for v in iter_bulk_veins(args.domain):
            if args.execute:
                if not args.bulk_budget_bytes:
                    print(f"BLOCKED: --bulk-budget-bytes required to --execute bulk vein {v.name}", file=sys.stderr)
                    return 1
                cmd = [sys.executable, str(CONNECTOR_SCRIPTS["bulk_fetch"]), *v.build_argv(args.bulk_budget_bytes)]
                print(f"# {v.name} ({','.join(v.domains)}) [{v.license_basis}]")
                print(" ".join(cmd))
                subprocess.run(cmd, check=True)
            else:
                print(f"# {v.name} ({','.join(v.domains)}) [{v.license_basis}] -- bulk vein, needs --bulk-budget-bytes to dispatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
