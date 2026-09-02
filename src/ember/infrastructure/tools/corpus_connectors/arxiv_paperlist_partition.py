#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""arxiv_paperlist_partition.py -- OAI-XML-to-ordered-paper-list partition step.

Consumes the raw OAI-PMH bulk harvest pages (harvest_oai.py output, one <record>
per arXiv id, each carrying an optional <license> element) for a single arXiv
set (e.g. math, stat) and produces a declared-order, exact-license-filtered,
deterministically-partitioned paper-list file directly consumable by
arxiv_fetch.py's --paper-list flag.

Partition rule (research-lead ruling, confirmed against real harvested data):

  1. Parse every <record> across all pages, keep (id, license) where id is the
     raw OAI <id> field (no version suffix -- confirmed absent for both math
     and stat ids by direct harvest inspection, not assumed by analogy).
  2. Exact-SPDX filter: license == 'http://creativecommons.org/licenses/by/4.0/'
     only (CC-BY-4.0 exact match -- NOT the connector's broader is_cc(), which
     would also admit by-sa/by-nc-*/publicdomain variants this partition must
     exclude).
  3. residue = sha256(raw id, utf-8) interpreted as a big-endian integer, mod 2.
     Equivalent shortcut: parity of the hex digest's final hex digit (every
     higher place value in a base-16 number is a multiple of 2, so only the
     last digit affects the number's parity) -- this script computes the mod-2
     value directly from the full digest rather than relying on the shortcut,
     but the two are mathematically identical and cross-checked in tests.
  4. residue 0 -> this set's train-2 class (what this script emits, ordered).
     residue 1 -> held out from this run. Its meaning is set-specific and NOT
     decided by this script -- callers pass --heldout-label describing what
     residue 1 means for the set being partitioned (e.g. "A heldout-1, future
     fetch" for math; "reserved, independent Elsevier source is B's real
     heldout-1" for stat). This script only computes and records the split;
     it never fetches or otherwise acts on residue 1.
  5. Within residue 0 (train-2), order ascending by the full hex digest.

Writes, under --out-dir:
  train2-paper-list.txt   -- one id per line, in the declared ascending-hex
                              order, directly consumable by arxiv_fetch.py's
                              --paper-list flag.
  heldout-id-list.txt     -- residue-1 ids, same ascending-hex order, for
                              reproducibility -- NOT fetched by this script.
  partition-manifest.json -- full rule declaration + counts (the permanent
                              reproducibility record; no GitHub issue exists
                              or will exist for this partition -- the issue
                              freeze is standing law until the goal completes).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, NamedTuple, Optional

OAI_NS = "http://www.openarchives.org/OAI/2.0/"
ARXIV_NS = "http://arxiv.org/OAI/arXiv/"
NS = {"oai": OAI_NS, "arxiv": ARXIV_NS}

EXACT_CC_BY_4_0 = "http://creativecommons.org/licenses/by/4.0/"

_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


class Candidate(NamedTuple):
    arxiv_id: str
    digest_hex: str
    residue: int


def _iter_records(xml_path: Path) -> Iterator[tuple[Optional[str], Optional[str]]]:
    """Yield (raw_id, raw_license_url_or_None) per <record> in one OAI page.

    Uses ET.iterparse over the default OAI namespace and clears each <record>
    element after reading it -- pages can carry ~1000+ records each and this
    keeps peak memory bounded to one record at a time, not one page.

    Opens the file explicitly (rather than handing iterparse the path) so the
    handle closes deterministically via the `with` block even when a caller
    abandons this generator mid-iteration (e.g. raises out of the consuming
    for-loop) -- iterparse(path) otherwise leaves the file locked on Windows
    until GC gets to it, which broke TemporaryDirectory cleanup in tests.
    """
    with xml_path.open("rb") as f:
        for event, elem in ET.iterparse(f, events=("end",)):
            if elem.tag != f"{{{OAI_NS}}}record":
                continue
            arxiv_el = elem.find(f".//{{{ARXIV_NS}}}id")
            license_el = elem.find(f".//{{{ARXIV_NS}}}license")
            raw_id = arxiv_el.text.strip() if arxiv_el is not None and arxiv_el.text else None
            raw_license = license_el.text.strip() if license_el is not None and license_el.text else None
            yield raw_id, raw_license
            elem.clear()


def collect_exact_cc_by_4_0_ids(pages_dir: Path) -> List[str]:
    """All raw (unversioned) OAI ids across pages_dir/*.xml whose <license>
    is an EXACT CC-BY-4.0 match. Raises on any duplicate id (the harvest is
    expected to be one record per identifier; a duplicate means the harvest
    page set overlaps and the caller must dedupe/re-harvest before trusting
    this partition, not silently collapse it here)."""
    seen: dict[str, Path] = {}
    ids: List[str] = []
    for xml_path in sorted(pages_dir.glob("*.xml")):
        for raw_id, raw_license in _iter_records(xml_path):
            if raw_id is None or raw_license != EXACT_CC_BY_4_0:
                continue
            if _VERSION_SUFFIX_RE.search(raw_id):
                raise ValueError(
                    f"{xml_path}: OAI id {raw_id!r} carries a version suffix -- this partition's "
                    f"no-version-suffix assumption (verified for math/stat at build time) does not "
                    f"hold for this set; fix _strip_version handling before trusting the split"
                )
            if raw_id in seen:
                raise ValueError(
                    f"duplicate OAI id {raw_id!r} in {xml_path} (first seen in {seen[raw_id]}) -- "
                    f"harvest pages overlap; re-harvest or dedupe before partitioning"
                )
            seen[raw_id] = xml_path
            ids.append(raw_id)
    return ids


def partition(ids: List[str]) -> tuple[List[Candidate], List[Candidate]]:
    """Split ids into (train2, heldout) Candidate lists, each ascending by
    full hex digest. train2 = residue 0, heldout = residue 1."""
    train2: List[Candidate] = []
    heldout: List[Candidate] = []
    for raw_id in ids:
        digest_hex = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        residue = int(digest_hex, 16) % 2
        c = Candidate(arxiv_id=raw_id, digest_hex=digest_hex, residue=residue)
        (train2 if residue == 0 else heldout).append(c)
    train2.sort(key=lambda c: c.digest_hex)
    heldout.sort(key=lambda c: c.digest_hex)
    return train2, heldout


def write_outputs(
    out_dir: Path,
    set_name: str,
    pages_dir: Path,
    heldout_label: str,
    train2: List[Candidate],
    heldout: List[Candidate],
) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    train2_path = out_dir / "train2-paper-list.txt"
    train2_path.write_text(
        "\n".join(c.arxiv_id for c in train2) + "\n",
        encoding="utf-8",
    )

    heldout_path = out_dir / "heldout-id-list.txt"
    heldout_path.write_text(
        "\n".join(c.arxiv_id for c in heldout) + "\n",
        encoding="utf-8",
    )

    manifest_path = out_dir / "partition-manifest.json"
    manifest = {
        "set": set_name,
        "source_pages_dir": str(pages_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "license_filter": {
            "rule": "exact-SPDX match, not is_cc() family membership",
            "accepted_license_url": EXACT_CC_BY_4_0,
        },
        "id_normalization": "raw OAI <id> field, no version suffix (verified present at build time)",
        "hash_primitive": {
            "algorithm": "sha256(raw_id.encode('utf-8'))",
            "assignment": "int(hexdigest, 16) % 2 (equivalently: parity of the digest's final hex digit)",
            "residue_0": "train-2 (this file's train2-paper-list.txt)",
            "residue_1": heldout_label,
        },
        "ordering_rule": "ascending by full hex digest, within each residue class independently",
        "counts": {
            "total_exact_cc_by_4_0": len(train2) + len(heldout),
            "residue_0_train2": len(train2),
            "residue_1_heldout": len(heldout),
        },
        "outputs": {
            "train2_paper_list": train2_path.name,
            "heldout_id_list": heldout_path.name,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return train2_path, heldout_path, manifest_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--pages-dir", type=Path, required=True, help="dir of harvested OAI XML pages (*.xml) for one set")
    p.add_argument("--set-name", required=True, help="label for this set, e.g. math, stat")
    p.add_argument("--out-dir", type=Path, required=True, help="dir to write train2-paper-list.txt + manifest")
    p.add_argument(
        "--heldout-label", required=True,
        help="what residue-1 means for this set (recorded in the manifest only -- this script "
             "never fetches or acts on residue 1), e.g. "
             "'A heldout-1, future fetch' or 'reserved -- B heldout-1 is an independent Elsevier source'",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    ids = collect_exact_cc_by_4_0_ids(args.pages_dir)
    train2, heldout = partition(ids)
    train2_path, heldout_path, manifest_path = write_outputs(
        args.out_dir, args.set_name, args.pages_dir, args.heldout_label, train2, heldout
    )
    print(f"set={args.set_name} total={len(ids)} train2={len(train2)} heldout={len(heldout)}")
    print(f"train2_paper_list={train2_path}")
    print(f"heldout_id_list={heldout_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
