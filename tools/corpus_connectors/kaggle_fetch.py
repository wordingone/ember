#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""kaggle_fetch.py -- Kaggle CLI wrapper connector.

    kaggle_fetch.py DATASET_SLUG [--dest DIR] [--allow-unverified-license]

Credentials are checked BEFORE anything else touches the `kaggle` package or
CLI (env vars KAGGLE_USERNAME/KAGGLE_KEY, or `~/.kaggle/kaggle.json` /
$KAGGLE_CONFIG_DIR/kaggle.json existence-only -- this connector never reads
or logs credential contents). If absent: a single `BLOCKED` line, nonzero
exit, no account creation, no prompts (per spec §3/§5).

Wraps the `kaggle` CLI (`kaggle datasets metadata` then `kaggle datasets
download`) via subprocess -- the `kaggle` package is confirmed present at
build time (see README "Dependency posture"), but this connector shells out
to its console-script CLI rather than importing its Python API, so that a
credential problem surfaces as this connector's own BLOCKED line rather than
an exception raised deep inside the `kaggle` package at import/config time.

No Kaggle credential handling beyond detect-and-refuse (spec §5 scope fence).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Optional

import receipt as rcpt

CONNECTOR_NAME = "kaggle_fetch"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch a Kaggle dataset with an L4 receipt.")
    p.add_argument("dataset_slug", help="Kaggle dataset slug, e.g. owner/dataset-name")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/kaggle/<slug>)")
    p.add_argument("--allow-unverified-license", action="store_true")
    return p


def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _fetch_license(dataset_slug: str, dest_root: Path, runner=_run) -> tuple[Optional[str], str]:
    """Runs `kaggle datasets metadata` into a scratch subdir and reads the
    written dataset-metadata.json for a `licenses` array. Returns
    (license_str_or_None, evidence)."""
    meta_dir = dest_root / "_kaggle_metadata_scratch"
    meta_dir.mkdir(parents=True, exist_ok=True)
    result = runner(["kaggle", "datasets", "metadata", "-p", str(meta_dir), "-d", dataset_slug])
    if result.returncode != 0:
        return None, f"kaggle datasets metadata failed: {result.stderr.strip()[:300]}"
    meta_file = meta_dir / "dataset-metadata.json"
    if not meta_file.is_file():
        return None, "kaggle datasets metadata produced no dataset-metadata.json"
    try:
        payload = json.loads(meta_file.read_text(encoding="utf-8"))
        if isinstance(payload, str):
            # Real Kaggle CLI (v1.7.4.5, confirmed at this connector's build
            # time) writes dataset-metadata.json double-JSON-encoded: a JSON
            # string wrapping the object. Re-decode exactly once; a second
            # str result is malformed, not a crash.
            payload = json.loads(payload)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"could not parse dataset-metadata.json: {exc}"
    if not isinstance(payload, dict):
        return None, f"dataset-metadata.json did not decode to an object (got {type(payload).__name__})"
    licenses = payload.get("licenses") or []
    names = [lic.get("name") for lic in licenses if isinstance(lic, dict) and lic.get("name")]
    if not names:
        return None, "dataset-metadata.json has no non-empty licenses[].name"
    return ", ".join(names), "Kaggle dataset metadata endpoint (`kaggle datasets metadata`) licenses[].name"


def fetch(args: argparse.Namespace, runner=_run, creds_present=None) -> Path:
    present = creds_present() if creds_present else rcpt.kaggle_credentials_present()
    if not present:
        raise rcpt.MissingCredentialsError(
            "Kaggle credentials absent (no KAGGLE_USERNAME/KAGGLE_KEY env vars and no "
            "kaggle.json found); create a Kaggle API token yourself and place it at "
            "~/.kaggle/kaggle.json -- this connector will not create an account or prompt"
        )

    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "kaggle" / rcpt.safe_key(args.dataset_slug)
    if dest_root.exists() and any(p for p in dest_root.iterdir() if p.name != "_kaggle_metadata_scratch"):
        raise rcpt.DestCollisionError(f"destination already has content: {dest_root}")
    dest_root.mkdir(parents=True, exist_ok=True)

    license_str, license_evidence = _fetch_license(args.dataset_slug, dest_root, runner)
    license_str = license_str or rcpt.UNVERIFIED
    rcpt.gate_license(license_str, args.allow_unverified_license)

    result = runner(["kaggle", "datasets", "download", "-d", args.dataset_slug, "-p", str(dest_root)])
    if result.returncode != 0:
        raise rcpt.BlockedError(f"kaggle datasets download failed: {result.stderr.strip()[:300]}")

    zips = list(dest_root.glob("*.zip"))
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            zf.extractall(dest_root)
        z.unlink()

    exclude_dirs = (*rcpt.DEFAULT_EXCLUDE_DIRNAMES, "_kaggle_metadata_scratch")
    rel_paths = rcpt.relative_files_under(dest_root, exclude_dirnames=exclude_dirs)
    if not rel_paths:
        raise rcpt.BlockedError(f"no files landed under {dest_root} after kaggle datasets download")
    files = rcpt.build_file_entries(dest_root, rel_paths)
    downloaded_paths = [dest_root / p.path for p in files]

    receipt = rcpt.Receipt(
        source="kaggle",
        source_id=args.dataset_slug,
        canonical_url=f"https://www.kaggle.com/datasets/{args.dataset_slug}",
        license=license_str,
        license_evidence=license_evidence,
        revision=None,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes="",
    )
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return rcpt.run_cli(lambda: fetch(args))


if __name__ == "__main__":
    sys.exit(main())
