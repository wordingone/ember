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
     shell out) prints or runs the routed commands. Bulk execution is refused
     unless a closed resolution JSON map and an external license-evidence JSON
     map are supplied; entry-page URLs are never handed to `bulk_fetch.py`.

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
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
BULK_RESOLUTION_SCHEMA = "ember-wave2-bulk-resolution-v1"

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


def is_entry_page_url(url: str) -> bool:
    """True when a URL names a site root or directory index rather than an artifact.

    #1480 gave `BulkVein` an entry-page-vs-artifact distinction via
    `requires_resolution`; `WaveSource` never got one, so eight single-shot rows
    shipped pointing at documentation roots that fetch one HTML page.
    """
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path = parsed.path
    if not path or path == "/" or path.endswith("/"):
        return True
    return "." not in Path(path).name


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
    requires_resolution: bool = False
    #: For a disjunctive licence ("A OR B"), which branch this row takes. An
    #: unelected OR is not a licence, so spdx_gate refuses one that omits this.
    license_elected: Optional[str] = None

    def __post_init__(self) -> None:
        if self.connector not in CONNECTOR_SCRIPTS:
            raise ValueError(f"{self.name}: unknown connector {self.connector!r}")
        for d in self.domains:
            if d not in CHARTER_DOMAINS:
                raise ValueError(f"{self.name}: unknown charter domain {d!r}")
        if not self.argv:
            raise ValueError(f"{self.name}: argv must not be empty")
        if self.requires_resolution:
            url = next((a for a in self.argv if a.startswith(("http://", "https://"))), "")
            if is_entry_page_url(url):
                raise ValueError(
                    f"{self.name}: {url!r} is an entry page, not a concrete artifact URL"
                )
        if self.license_elected is not None:
            argv = list(self.argv)
            if "--license" not in argv:
                raise ValueError(f"{self.name}: license_elected set but no --license is declared")
            declared = argv[argv.index("--license") + 1]
            if self.license_elected not in declared.split(" OR "):
                raise ValueError(
                    f"{self.name}: elected {self.license_elected!r} is not a branch of {declared!r}"
                )
        if self.est_tokens_low_b <= 0 or self.est_tokens_high_b < self.est_tokens_low_b:
            raise ValueError(f"{self.name}: est_tokens bounds must be positive and ordered")


@dataclass(frozen=True)
class ProseGapSource:
    """One rule-based prose-gap row; estimates remain planning-only until receipted."""

    name: str
    domains: tuple
    estimated_tokens_low_b: float
    estimated_tokens_high_b: float
    license_evidence: str
    status: str = "candidate-unfetched"

    def __post_init__(self) -> None:
        if not self.name or not self.domains:
            raise ValueError("prose-gap source requires a name and domain")
        for domain in self.domains:
            if domain not in CHARTER_DOMAINS or domain == "baseline":
                raise ValueError(f"{self.name}: invalid prose-gap domain {domain!r}")
        if self.estimated_tokens_low_b <= 0 or self.estimated_tokens_high_b < self.estimated_tokens_low_b:
            raise ValueError(f"{self.name}: estimated token bounds must be positive and ordered")
        if not self.license_evidence.strip():
            raise ValueError(f"{self.name}: license evidence is required")
        if self.status not in {"existing-receipted-pending-normalize", "unverified", "candidate-unfetched"}:
            raise ValueError(f"{self.name}: unknown planning status {self.status!r}")


@dataclass(frozen=True)
class ProseGapPlan:
    """Closed, deterministic, CPU-only planning projection for issue #1437."""

    selection_policy: str
    current_clean_prose_tokens_b: float
    target_additional_tokens_b: float
    domain_coverage: tuple
    sources: tuple
    baseline_basis: str
    claim_boundary: str


def build_prose_gap_plan() -> ProseGapPlan:
    """Build the rule-based plan without fetching or executing any connector."""

    sources = (
        ProseGapSource(
            name="arxiv-abstracts",
            domains=("E", "I"),
            estimated_tokens_low_b=0.405,
            estimated_tokens_high_b=0.670,
            license_evidence="arXiv per-paper license records in the existing L4 receipt",
            status="existing-receipted-pending-normalize",
        ),
        ProseGapSource(
            name="stackexchange-dumps",
            domains=("D", "H", "K"),
            estimated_tokens_low_b=0.9,
            estimated_tokens_high_b=1.1,
            license_evidence="Stack Exchange data-dump CC-BY-SA-4.0 terms",
            status="unverified",
        ),
        ProseGapSource(
            name="pubmed-abstracts-pre-2022",
            domains=("E", "I", "J"),
            estimated_tokens_low_b=0.2,
            estimated_tokens_high_b=0.5,
            license_evidence="NLM terms and PubMed source notice",
        ),
        ProseGapSource(
            name="uspto-patents-public-domain",
            domains=("D", "I", "K"),
            estimated_tokens_low_b=0.3,
            estimated_tokens_high_b=0.6,
            license_evidence="USPTO public-domain publication terms",
        ),
        ProseGapSource(
            name="europarl-un-multilingual",
            domains=("B", "D", "K"),
            estimated_tokens_low_b=0.2,
            estimated_tokens_high_b=0.4,
            license_evidence="EuroParl/UN open multilingual source terms",
        ),
        ProseGapSource(
            name="gutenberg-expansion",
            domains=("H", "K"),
            estimated_tokens_low_b=0.3,
            estimated_tokens_high_b=0.6,
            license_evidence="Project Gutenberg public-domain item records",
        ),
    )
    coverage = tuple(sorted(set(domains_covered()) & set("ABCDEFGHIJK")))
    if coverage != tuple("ABCDEFGHIJK"):
        raise ValueError("wave routing table does not cover every A-K charter domain")
    return ProseGapPlan(
        selection_policy="RULE_BASED",
        current_clean_prose_tokens_b=1.253,
        target_additional_tokens_b=1.67,
        domain_coverage=coverage,
        sources=sources,
        baseline_basis="issue-1437 L3 audit dated 2026-08-04",
        claim_boundary="PREP_ONLY; zero source is credited until canonical L4 receipt and deterministic import validation",
    )


def render_prose_gap_plan(plan: ProseGapPlan) -> str:
    """Render the numbered plan; this function performs no I/O or fetching."""

    lines = [
        "# 1437 prose-gap plan (PREP_ONLY)",
        "",
        f"1. Current clean prose total: {plan.current_clean_prose_tokens_b:.3f}B planning tokens.",
        f"2. Rule-based target addition: {plan.target_additional_tokens_b:.3f}B planning tokens.",
        "3. Candidate additions require human provenance, license evidence, and a canonical connector receipt before credit.",
        "4. Domain coverage is recomputed from the routed table before any governed import.",
        "",
        f"Selection policy: {plan.selection_policy}; no model-derived filter, rank, score, or language-ID step.",
        f"Baseline: {plan.baseline_basis}.",
        f"Claim boundary: {plan.claim_boundary}.",
    ]
    for source in plan.sources:
        lines.append(
            f"- {source.name}: {source.estimated_tokens_low_b:g}-{source.estimated_tokens_high_b:g}B; "
            f"domains={','.join(source.domains)}; status={source.status}; license={source.license_evidence}."
        )
    return "\n".join(lines) + "\n"


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
        notes=(
            "UNRESOLVED as of 2026-08-14: itl.nist.gov answers 200 with Content-Type "
            "text/html for every path including handbook.zip and handbook.tgz, so no "
            "bundle URL can be confirmed and status codes cannot tell a hit from a miss. "
            "This URL fetches a single 2,064-byte index page, not the handbook. Needs a "
            "crawling connector or a replacement source before it can be credited."
        ),
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
        license_basis="Apache-2.0 WITH LLVM-exception (LLVM)",
        connector="http_fetch",
        argv=(
            "https://github.com/llvm/llvm-project/archive/refs/heads/main.tar.gz",
            "--license", "Apache-2.0 WITH LLVM-exception",
            "--license-evidence",
            "llvm/llvm-project LICENSE.TXT; GitHub license API returns NOASSERTION because "
            "the LLVM exception is non-standard, so the bare Apache-2.0 tag understated it",
        ),
        est_tokens_low_b=0.05,
        est_tokens_high_b=0.2,
        requires_resolution=True,
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
            "https://github.com/leanprover-community/mathlib4/archive/refs/heads/master.tar.gz",
            "--license", "Apache-2.0",
            "--license-evidence", "leanprover-community/mathlib4 LICENSE via GitHub license API = Apache-2.0",
        ),
        est_tokens_low_b=0.2,
        est_tokens_high_b=0.6,
        requires_resolution=True,
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
        license_basis="CC-BY-4.0 (ROS 2 documentation)",
        connector="http_fetch",
        argv=(
            "https://github.com/ros2/ros2_documentation/archive/refs/heads/rolling.tar.gz",
            "--license", "CC-BY-4.0",
            "--license-evidence",
            "ros2/ros2_documentation LICENSE via GitHub license API = CC-BY-4.0; "
            "the table previously declared CC-BY-3.0",
        ),
        est_tokens_low_b=0.1,
        est_tokens_high_b=0.3,
        requires_resolution=True,
    ),
    WaveSource(
        name="python-language-docs",
        domains=("H",),
        license_basis="Python Software Foundation License (Python documentation)",
        connector="http_fetch",
        argv=(
            "https://docs.python.org/3/archives/python-3.14-docs-text.zip",
            "--license", "Python-2.0",
            "--license-evidence",
            "python/cpython LICENSE (PSF License Agreement); archive published on "
            "docs.python.org/3/download.html",
        ),
        est_tokens_low_b=0.1,
        est_tokens_high_b=0.4,
        notes="independent API/reference register for H-domain diversity; text variant, not HTML",
        requires_resolution=True,
    ),
    WaveSource(
        name="rust-reference-docs",
        domains=("H",),
        license_basis="MIT/Apache-2.0 (Rust project documentation)",
        connector="http_fetch",
        argv=(
            "https://github.com/rust-lang/reference/archive/refs/heads/master.tar.gz",
            "--license", "MIT OR Apache-2.0",
            "--license-evidence",
            "rust-lang/reference LICENSE-APACHE and LICENSE-MIT via GitHub license API",
        ),
        est_tokens_low_b=0.1,
        est_tokens_high_b=0.4,
        notes="independent language-reference register for H-domain diversity",
        requires_resolution=True,
        license_elected="MIT",
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
    requires_resolution: bool = False

    def __post_init__(self) -> None:
        for d in self.domains:
            if d not in CHARTER_DOMAINS:
                raise ValueError(f"{self.name}: unknown charter domain {d!r}")
        if not self.url:
            raise ValueError(f"{self.name}: url must not be empty")

    def build_argv(
        self,
        budget_bytes: int,
        *,
        license_evidence: str,
        resolved_url: Optional[str] = None,
    ) -> tuple:
        if type(budget_bytes) is not int or budget_bytes <= 0:
            raise ValueError(f"{self.name}: budget_bytes must be positive")
        if not isinstance(license_evidence, str) or not license_evidence.strip():
            raise ValueError(f"{self.name}: external license evidence is required")
        if "wave_manifest.py" in license_evidence.casefold():
            raise ValueError(f"{self.name}: license evidence must not self-cite wave_manifest.py")
        if self.requires_resolution and not resolved_url:
            raise ValueError(f"{self.name}: concrete artifact URL resolution is required")
        target_url = resolved_url or self.url
        parsed = urlparse(target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.path:
            raise ValueError(f"{self.name}: resolved artifact URL is invalid")
        return (
            target_url,
            "--budget-bytes", str(budget_bytes),
            "--license", self.license_basis,
            "--license-evidence", license_evidence.strip(),
        )


WAVE2_BULK_VEINS: List[BulkVein] = [
    BulkVein(
        name="arxiv-fulltext-bulk",
        domains=("A", "B", "C", "D", "E", "F", "I"),
        license_basis="arXiv bulk access terms (per-paper CC filter applied downstream)",
        url="https://arxiv.org/help/bulk_data",
        est_tokens_low_b=18.0,
        est_tokens_high_b=25.0,
        requires_resolution=True,
    ),
    BulkVein(
        name="pmc-oa-comm-use",
        domains=("J", "C", "E"),
        license_basis="PMC Open Access commercial-use subset (CC-BY/CC0)",
        url="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/",
        est_tokens_low_b=8.0,
        est_tokens_high_b=15.0,
        requires_resolution=True,
    ),
    BulkVein(
        name="stackexchange-charter-sites",
        domains=("A", "B", "C", "D", "E", "H", "K"),
        license_basis="CC-BY-SA-4.0 (Stack Exchange data dump license)",
        url="https://archive.org/download/stackexchange",
        est_tokens_low_b=10.0,
        est_tokens_high_b=18.0,
        requires_resolution=True,
    ),
    BulkVein(
        name="us-federal-technical-pd",
        domains=("C", "F", "J"),
        license_basis="US-gov public domain (NASA NTRS / DOE OSTI / NIST / USGS-NOAA)",
        url="https://ntrs.nasa.gov/api/citations/search",
        est_tokens_low_b=4.0,
        est_tokens_high_b=8.0,
        requires_resolution=True,
    ),
    BulkVein(
        name="open-textbooks-reference",
        domains=("A", "B", "C", "D", "G"),
        license_basis="CC-BY / public-domain (OpenStax/LibreTexts CC-BY subset/Wikibooks/Stacks Project/nLab)",
        url="https://openstax.org/api/v2/pages/",
        est_tokens_low_b=3.0,
        est_tokens_high_b=6.0,
        requires_resolution=True,
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


def _independence_projection(entry: WaveSource | BulkVein) -> tuple[str, str]:
    """Return the closed register/license identity used for diversity checks."""
    if isinstance(entry, WaveSource):
        urls = [token for token in entry.argv if token.startswith(("http://", "https://"))]
        register_input = urls[0] if urls else f"{entry.connector}|{' '.join(entry.argv)}"
        connector = entry.connector
    else:
        register_input = entry.url
        connector = "bulk_fetch"
    parsed = urlparse(register_input)
    if parsed.scheme and parsed.netloc:
        # A register is the publishing host, not an arbitrary page path.
        # Counting /reference and /tutorial as separate registers would let
        # same-host aliases satisfy the independence gate.
        register = f"{parsed.scheme}://{parsed.netloc}".casefold()
    else:
        register = register_input.strip().casefold()
    license_basis = " ".join(entry.license_basis.split()).casefold()
    return f"{connector.casefold()}|{register}", license_basis


def validate_domain_diversity() -> dict[str, list[str]]:
    """Return domains lacking two distinct register and license identities."""
    deficits: dict[str, list[str]] = {}
    for domain in CHARTER_DOMAINS:
        if domain == "baseline":
            continue
        entries = [s for s in WAVE2_SOURCES if domain in s.domains]
        entries.extend(v for v in WAVE2_BULK_VEINS if domain in v.domains)
        projections = [_independence_projection(entry) for entry in entries]
        registers = {register for register, _ in projections}
        licenses = {license_basis for _, license_basis in projections}
        if len(entries) < 2 or len(registers) < 2 or len(licenses) < 2:
            deficits[domain] = [entry.name for entry in entries]
    return deficits


def _resolution_receipt_sha256(vein_name: str, urls: list[str]) -> str:
    payload = {
        "schema": BULK_RESOLUTION_SCHEMA,
        "vein": vein_name,
        "urls": list(urls),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_bulk_mapping(path: str, selected: list[BulkVein], label: str) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} file is unreadable or malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} file must be a JSON object")
    expected = {v.name for v in selected}
    if set(payload) != expected:
        raise ValueError(f"{label} file must contain exactly the selected bulk veins")
    return payload


def _bulk_dispatch_plan(
    selected: list[BulkVein],
    resolution_file: str,
    evidence_file: str,
) -> list[tuple[BulkVein, str, str]]:
    resolutions = _load_bulk_mapping(resolution_file, selected, "bulk resolution")
    evidence = _load_bulk_mapping(evidence_file, selected, "bulk license evidence")
    plan: list[tuple[BulkVein, str, str]] = []
    for vein in selected:
        resolution = resolutions[vein.name]
        if not isinstance(resolution, dict) or set(resolution) != {"urls", "resolution_receipt_sha256"}:
            raise ValueError(f"bulk vein {vein.name} resolution receipt has an invalid closed schema")
        receipt_sha256 = resolution["resolution_receipt_sha256"]
        if (
            not isinstance(receipt_sha256, str)
            or len(receipt_sha256) != 64
            or any(char not in "0123456789abcdef" for char in receipt_sha256)
        ):
            raise ValueError(f"bulk vein {vein.name} resolution receipt hash is invalid")
        urls = resolution["urls"]
        if vein.requires_resolution:
            if not isinstance(urls, list) or not urls or not all(isinstance(url, str) for url in urls):
                raise ValueError(f"bulk vein {vein.name} has no concrete resolved artifact URLs")
            if len(set(urls)) != len(urls):
                raise ValueError(f"bulk vein {vein.name} resolution receipt has duplicate URLs")
        elif urls != [vein.url]:
            raise ValueError(f"bulk vein {vein.name} receipt must bind its direct artifact URL")
        target_urls = urls
        expected_receipt_sha256 = _resolution_receipt_sha256(vein.name, target_urls)
        if receipt_sha256 != expected_receipt_sha256:
            raise ValueError(f"bulk vein {vein.name} resolution receipt does not bind its URL set")
        text = evidence[vein.name]
        if not isinstance(text, str) or not text.strip() or "wave_manifest.py" in text.casefold():
            raise ValueError(f"bulk vein {vein.name} has invalid external license evidence")
        for target_url in target_urls:
            if vein.requires_resolution and urlparse(target_url).path.endswith("/"):
                raise ValueError(f"bulk vein {vein.name} resolution points to an entry page")
            vein.build_argv(1, license_evidence=text, resolved_url=target_url)
            plan.append((vein, target_url, text))
    return plan


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Route wave-2 charter-domain sources to their connector CLI invocations (issue #1439)."
    )
    p.add_argument("--domain", default=None, choices=sorted(CHARTER_DOMAINS), help="filter to one charter domain letter")
    p.add_argument("--include-bulk", action="store_true", help="also list the six bulk veins (no budget dispatched by default)")
    p.add_argument("--bulk-budget-bytes", type=int, default=None, help="required with --include-bulk --execute")
    p.add_argument("--bulk-resolution-file", default=None, help="closed JSON map of selected entry pages to concrete artifact URLs")
    p.add_argument("--bulk-license-evidence-file", default=None, help="closed JSON map of selected veins to external license evidence")
    p.add_argument("--execute", action="store_true", help="actually run each routed connector (default: print only)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    sources = iter_sources(args.domain)
    bulk_plan: list[tuple[BulkVein, str, str]] = []
    selected_bulk = iter_bulk_veins(args.domain) if args.include_bulk else []
    if args.include_bulk and args.execute:
        if type(args.bulk_budget_bytes) is not int or args.bulk_budget_bytes <= 0:
            print("BLOCKED: --bulk-budget-bytes required to --execute bulk veins", file=sys.stderr)
            return 1
        if not args.bulk_resolution_file or not args.bulk_license_evidence_file:
            print("BLOCKED: --bulk-resolution-file and --bulk-license-evidence-file are required before bulk dispatch", file=sys.stderr)
            return 1
        try:
            bulk_plan = _bulk_dispatch_plan(
                selected_bulk,
                args.bulk_resolution_file,
                args.bulk_license_evidence_file,
            )
        except ValueError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 1
    for s in sources:
        cmd = [sys.executable, *build_argv(s)]
        print(f"# {s.name} ({','.join(s.domains)}) [{s.license_basis}]")
        print(" ".join(cmd))
        if args.execute:
            subprocess.run(cmd, check=True)
    if args.include_bulk:
        if args.execute:
            for v, target_url, evidence in bulk_plan:
                cmd = [
                    sys.executable,
                    str(CONNECTOR_SCRIPTS["bulk_fetch"]),
                    *v.build_argv(
                        args.bulk_budget_bytes,
                        license_evidence=evidence,
                        resolved_url=target_url,
                    ),
                ]
                print(f"# {v.name} ({','.join(v.domains)}) [{v.license_basis}]")
                print(" ".join(cmd))
                subprocess.run(cmd, check=True)
        for v in selected_bulk:
            if not args.execute:
                print(f"# {v.name} ({','.join(v.domains)}) [{v.license_basis}] -- bulk vein, needs explicit resolution/evidence before dispatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
