#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""hf_fetch.py -- HuggingFace datasets/files connector CLI.

    hf_fetch.py REPO_ID [--revision R] [--include GLOB ...] [--dest DIR]
                [--dataset|--model] [--allow-unverified-license]

Resolves `--revision` (a branch/tag/ref, default "main") to a pinned commit SHA
via the HuggingFace Hub API, downloads via `huggingface_hub.snapshot_download`
(this connector requires huggingface_hub -- confirmed present at build time;
see README "Dependency posture"), reads the license from the repo card
metadata, and writes an L4 receipt. Prints `RECEIPT <path>` on success or
`BLOCKED <reason>` (nonzero exit) on refusal.

No GPU, no model inference, no dedup/decontamination (L3: fetch-only).

Token auth (fast-follow): `--hf-token`/`HF_TOKEN` accepts an already-obtained
HuggingFace token, forwarded explicitly to `HfApi(token=...)` and
`snapshot_download(..., token=...)` -- for gated/private repos. Explicit by
design (this codebase's "no ambient magic" convention, matching every other
connector's explicit `--license`/credential flags): when neither the flag
nor the env var is set, `token` is not passed to either call at all, so
behavior is byte-identical to before (whatever huggingface_hub's own default
resolution already did, unaffected).

License-evidence override (fast-follow): mirrors the `--license`/
`--license-evidence`-together pattern `http_fetch.py`/`bulk_fetch.py`
already use. Applies ONLY when the repo card's own metadata carries no
`license` field (the UNVERIFIED case) -- a resolved metadata license is
never silently overridden by a human-supplied flag; the override exists to
turn an UNVERIFIED tranche into a verified receipt when the lead has
independently confirmed the license, not to contest what the card states.
`--allow-unverified-license` is unaffected and still means what it always
has: proceed anyway with UNVERIFIED recorded.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from huggingface_hub import HfApi, snapshot_download

# Direct execution appends the repository root so the package import resolves
# without publishing connector-local bare names or shadowing earlier imports.
_REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from src.ember.infrastructure.tools.corpus_connectors import receipt as rcpt  # noqa: E402

CONNECTOR_NAME = "hf_fetch"

_HF_LICENSE_CANONICAL = {
    "apache-2.0": "Apache-2.0",
    "bsd-3-clause": "BSD-3-Clause",
    "cc-by-4.0": "CC-BY-4.0",
    "cc0-1.0": "CC0-1.0",
    "mit": "MIT",
}


def _resolve_token(cli_token: Optional[str]) -> Optional[str]:
    """CLI flag wins; falls back to HF_TOKEN env var; None if neither is set
    (unchanged default behavior -- token kwarg not passed at all)."""
    if cli_token:
        return cli_token
    return os.environ.get("HF_TOKEN") or None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch a HuggingFace dataset/model repo with an L4 receipt.")
    p.add_argument("repo_id", help="HuggingFace repo id, e.g. org/name")
    p.add_argument("--revision", default="main", help="branch/tag/ref to resolve and pin (default: main)")
    p.add_argument("--include", nargs="*", default=None, metavar="GLOB", help="allow_patterns passed to snapshot_download")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/hf/<safe repo_id>)")
    repo_type_group = p.add_mutually_exclusive_group()
    repo_type_group.add_argument("--dataset", action="store_const", dest="repo_type", const="dataset")
    repo_type_group.add_argument("--model", action="store_const", dest="repo_type", const="model")
    p.set_defaults(repo_type="dataset")
    p.add_argument("--hf-token", dest="hf_token", default=None, help="HuggingFace token (or set HF_TOKEN); for gated/private repos")
    p.add_argument("--license", dest="license_str", default=None, metavar="STR")
    p.add_argument("--license-evidence", dest="license_evidence", default=None, metavar="STR")
    p.add_argument("--allow-unverified-license", action="store_true", help="proceed with license recorded UNVERIFIED")
    return p


def _extract_license(info) -> Optional[str]:
    card_data = getattr(info, "card_data", None) or getattr(info, "cardData", None)
    if card_data is None:
        return None
    if isinstance(card_data, dict):
        lic = card_data.get("license")
    else:
        lic = getattr(card_data, "license", None)
    if isinstance(lic, list):
        return ", ".join(str(x) for x in lic) if lic else None
    return lic


def _canonical_hf_license(value: str) -> str:
    """Translate only closed, known HuggingFace card tags to project SPDX casing.

    Unknown tags are preserved byte-for-byte so the downstream license gate continues
    to refuse them rather than guessing a new authority mapping.
    """
    return ", ".join(
        _HF_LICENSE_CANONICAL.get(component.strip(), component.strip())
        for component in value.split(",")
    )


def fetch(args: argparse.Namespace) -> Path:
    if (args.license_str is None) != (args.license_evidence is None):
        raise rcpt.BlockedError("--license and --license-evidence must be supplied together")

    token = _resolve_token(getattr(args, "hf_token", None))
    api_kwargs = {"token": token} if token else {}
    api = HfApi(**api_kwargs)
    if args.repo_type == "model":
        info = api.model_info(args.repo_id, revision=args.revision)
    else:
        info = api.dataset_info(args.repo_id, revision=args.revision)

    pinned_sha = getattr(info, "sha", None)
    metadata_license = _extract_license(info)
    if metadata_license:
        license_str = _canonical_hf_license(metadata_license)
        license_evidence = "HuggingFace repo card metadata `license` field"
    elif args.license_str:
        # metadata carried no license -- a human-supplied, evidenced override
        # (never applied when the card DOES resolve a license; see module
        # docstring "License-evidence override").
        license_str = args.license_str
        license_evidence = args.license_evidence
    else:
        license_str = rcpt.UNVERIFIED
        license_evidence = "no `license` field present in repo card metadata"
    rcpt.gate_license(license_str, args.allow_unverified_license)

    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "hf" / rcpt.safe_key(args.repo_id)
    if dest_root.exists() and any(dest_root.iterdir()):
        raise rcpt.DestCollisionError(f"destination already has content: {dest_root}")
    dest_root.mkdir(parents=True, exist_ok=True)

    snapshot_kwargs = {"token": token} if token else {}
    snapshot_download(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        revision=pinned_sha or args.revision,
        allow_patterns=args.include,
        local_dir=str(dest_root),
        **snapshot_kwargs,
    )

    rel_paths = rcpt.relative_files_under(dest_root)
    if not rel_paths:
        raise rcpt.BlockedError(f"no files landed under {dest_root} after snapshot_download")
    files = rcpt.build_file_entries(dest_root, rel_paths)
    downloaded_paths = [dest_root / p.path for p in files]

    receipt = rcpt.Receipt(
        source="huggingface",
        source_id=args.repo_id,
        canonical_url=f"https://huggingface.co/{'datasets/' if args.repo_type == 'dataset' else ''}{args.repo_id}",
        license=license_str,
        license_evidence=license_evidence,
        revision=pinned_sha,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=f"repo_type={args.repo_type}; include={args.include or 'ALL'}",
    )
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return rcpt.run_cli(lambda: fetch(args))


if __name__ == "__main__":
    sys.exit(main())
