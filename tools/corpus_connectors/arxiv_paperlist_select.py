#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Select a deterministic, receipt-bound arXiv paper list from frozen OAI pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterator


SCHEMA = "ember-arxiv-paperlist-selection-v1"
MANIFEST_SCHEMA = "ember-arxiv-paperlist-selection-receipt-v1"
MANIFEST_NAME = "selection-manifest.json"
PAPER_LIST_NAME = "paper-list.txt"
OAI_NS = "http://www.openarchives.org/OAI/2.0/"
ARXIV_NS = "http://arxiv.org/OAI/arXiv/"
LICENSE_URLS = {
    "http://creativecommons.org/licenses/by/4.0/",
    "http://creativecommons.org/publicdomain/zero/1.0/",
}
_HEX = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[0-9]{4}\.[0-9]{4,5}$|^[a-z-]+(?:\.[A-Z]{2})?\/[0-9]{7}$")
_VERSION_SUFFIX = re.compile(r"v[0-9]+$")
_CATEGORY = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)?$")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class SelectionRefusal(ValueError):
    """The selection cannot satisfy the closed deterministic contract."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _regular(path: Path, label: str) -> Path:
    if _is_link(path) or not path.is_file():
        raise SelectionRefusal(f"{label} must be a regular non-reparse file")
    return path


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = _regular(path, label).read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SelectionRefusal(f"{label} must be strict UTF-8 JSON") from error
    if not isinstance(parsed, dict):
        raise SelectionRefusal(f"{label} must contain one JSON object")
    return raw, parsed


def _validate_spec(spec: dict[str, Any]) -> None:
    if set(spec) != {
        "schema", "as_of", "license_url", "categories", "category_mode",
        "date_range", "text_filter", "exclusions", "selection_label",
    } or spec.get("schema") != SCHEMA:
        raise SelectionRefusal("selection spec schema is not closed")
    if not isinstance(spec.get("as_of"), str) or not spec["as_of"].endswith("Z"):
        raise SelectionRefusal("selection spec as_of is invalid")
    if spec.get("license_url") not in LICENSE_URLS:
        raise SelectionRefusal("selection spec license URL is not an enumerated canonical form")
    categories = spec.get("categories")
    if (
        not isinstance(categories, list)
        or not categories
        or any(not isinstance(item, str) or _CATEGORY.fullmatch(item) is None for item in categories)
        or categories != sorted(set(categories))
    ):
        raise SelectionRefusal("selection categories must be a sorted unique canonical list")
    if spec.get("category_mode") not in {"any", "all"}:
        raise SelectionRefusal("selection category mode is invalid")
    period = spec.get("date_range")
    if period is not None:
        if not isinstance(period, dict) or set(period) != {"from", "through"}:
            raise SelectionRefusal("selection date range is not closed")
        try:
            start, end = date.fromisoformat(period["from"]), date.fromisoformat(period["through"])
        except (TypeError, ValueError) as error:
            raise SelectionRefusal("selection date range is invalid") from error
        if start > end:
            raise SelectionRefusal("selection date range is reversed")
    text_filter = spec.get("text_filter")
    if text_filter is not None:
        if (
            not isinstance(text_filter, dict)
            or set(text_filter) != {"pattern", "mode", "case_sensitive"}
            or not isinstance(text_filter.get("pattern"), str)
            or not text_filter["pattern"]
            or len(text_filter["pattern"]) > 1024
            or text_filter.get("mode") not in {"search", "fullmatch"}
            or type(text_filter.get("case_sensitive")) is not bool
        ):
            raise SelectionRefusal("selection text filter is not closed")
        try:
            re.compile(text_filter["pattern"], 0 if text_filter["case_sensitive"] else re.IGNORECASE)
        except re.error as error:
            raise SelectionRefusal("selection text filter regex is invalid") from error
    exclusions = spec.get("exclusions")
    if not isinstance(exclusions, list):
        raise SelectionRefusal("selection exclusions must be a list")
    prior_paths: list[str] = []
    for row in exclusions:
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "sha256"}
            or not isinstance(row.get("path"), str)
            or _HEX.fullmatch(row.get("sha256", "")) is None
        ):
            raise SelectionRefusal("selection exclusion binding is not closed")
        prior_paths.append(row["path"])
    if prior_paths != sorted(set(prior_paths)):
        raise SelectionRefusal("selection exclusion paths must be sorted and unique")
    if not isinstance(spec.get("selection_label"), str) or _LABEL.fullmatch(spec["selection_label"]) is None:
        raise SelectionRefusal("selection label is invalid")


def _page_inventory(pages_dir: Path) -> list[dict[str, Any]]:
    if _is_link(pages_dir) or not pages_dir.is_dir():
        raise SelectionRefusal("OAI pages directory must be a regular non-reparse directory")
    pages = sorted(pages_dir.glob("*.xml"), key=lambda item: item.name)
    if not pages:
        raise SelectionRefusal("OAI pages directory contains no XML pages")
    inventory = []
    for path in pages:
        raw = _regular(path, "OAI page").read_bytes()
        inventory.append({"path": path.name, "bytes": len(raw), "sha256": _sha256(raw)})
    return inventory


def _text(element: ET.Element, name: str) -> str | None:
    child = element.find(f"{{{ARXIV_NS}}}{name}")
    return child.text.strip() if child is not None and child.text else None


def _iter_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("rb") as handle:
        for _event, element in ET.iterparse(handle, events=("end",)):
            if element.tag != f"{{{OAI_NS}}}record":
                continue
            metadata = element.find(f".//{{{ARXIV_NS}}}arXiv")
            yield {
                "id": _text(metadata, "id") if metadata is not None else None,
                "license_url": _text(metadata, "license") if metadata is not None else None,
                "categories": (_text(metadata, "categories") or "").split() if metadata is not None else [],
                "created": _text(metadata, "created") if metadata is not None else None,
                "title": _text(metadata, "title") if metadata is not None else None,
                "abstract": _text(metadata, "abstract") if metadata is not None else None,
            }
            element.clear()


def _load_exclusions(spec: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    excluded: set[str] = set()
    bindings: list[dict[str, Any]] = []
    for row in spec["exclusions"]:
        path = Path(row["path"])
        raw = _regular(path, "prior paper list").read_bytes()
        if _sha256(raw) != row["sha256"]:
            raise SelectionRefusal("prior paper list bytes do not match the bound hash")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise SelectionRefusal("prior paper list must be strict UTF-8") from error
        if not lines or any(_ID.fullmatch(item) is None for item in lines) or len(lines) != len(set(lines)):
            raise SelectionRefusal("prior paper list is not a unique canonical arXiv ID list")
        excluded.update(lines)
        bindings.append({"path": str(path.resolve(strict=True)), "sha256": row["sha256"], "id_count": len(lines)})
    return excluded, bindings


def _derive(
    pages_dir: Path, spec_path: Path, spec_sha256: str
) -> tuple[dict[str, Any], list[str], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if _HEX.fullmatch(spec_sha256) is None:
        raise SelectionRefusal("selection spec hash is invalid")
    spec_raw, spec = _read_json(spec_path, "selection spec")
    if _sha256(spec_raw) != spec_sha256:
        raise SelectionRefusal("selection spec bytes do not match the bound hash")
    _validate_spec(spec)
    inventory = _page_inventory(pages_dir)
    excluded, exclusion_bindings = _load_exclusions(spec)
    category_set = set(spec["categories"])
    period = spec["date_range"]
    start = date.fromisoformat(period["from"]) if period is not None else None
    end = date.fromisoformat(period["through"]) if period is not None else None
    text_filter = spec["text_filter"]
    matcher = None
    if text_filter is not None:
        matcher = re.compile(text_filter["pattern"], 0 if text_filter["case_sensitive"] else re.IGNORECASE)
    accepted: list[tuple[str, str]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    parsed = 0
    for page in inventory:
        for record in _iter_records(pages_dir / page["path"]):
            parsed += 1
            arxiv_id = record["id"]
            if not isinstance(arxiv_id, str) or not arxiv_id:
                rejected["missing_metadata"] += 1
                continue
            if _VERSION_SUFFIX.search(arxiv_id):
                raise SelectionRefusal(f"arXiv id {arxiv_id!r} carries a version suffix")
            if _ID.fullmatch(arxiv_id) is None:
                raise SelectionRefusal(f"arXiv id {arxiv_id!r} is not canonical")
            if arxiv_id in seen:
                raise SelectionRefusal(f"duplicate arXiv id {arxiv_id!r} across OAI pages")
            seen.add(arxiv_id)
            raw_license = record["license_url"]
            if raw_license != spec["license_url"]:
                if isinstance(raw_license, str) and raw_license.rstrip("/") == spec["license_url"].rstrip("/"):
                    rejected["license_url_variant"] += 1
                else:
                    rejected["license_mismatch"] += 1
                continue
            record_categories = set(record["categories"])
            category_match = (
                bool(record_categories & category_set)
                if spec["category_mode"] == "any"
                else category_set <= record_categories
            )
            if not category_match:
                rejected["category_mismatch"] += 1
                continue
            if start is not None:
                try:
                    created = date.fromisoformat(record["created"])
                except (TypeError, ValueError):
                    rejected["invalid_date"] += 1
                    continue
                if created < start or created > end:
                    rejected["date_outside_range"] += 1
                    continue
            if matcher is not None:
                text = f"{record['title'] or ''}\n{record['abstract'] or ''}"
                matched = matcher.search(text) if text_filter["mode"] == "search" else matcher.fullmatch(text)
                if matched is None:
                    rejected["text_filter_mismatch"] += 1
                    continue
            if arxiv_id in excluded:
                rejected["excluded_by_bound_list"] += 1
                continue
            accepted.append((_sha256(arxiv_id.encode()), arxiv_id))
    accepted.sort()
    selected = [item[1] for item in accepted]
    if not selected:
        raise SelectionRefusal("selection produced no paper IDs")
    if len(selected) + sum(rejected.values()) != parsed:
        raise SelectionRefusal("selection reason accounting is not exhaustive")
    counts = {
        "parsed": parsed,
        "accepted": len(selected),
        "rejected_by_reason": dict(sorted(rejected.items())),
    }
    return spec, selected, counts, inventory, exclusion_bindings


def _manifest(
    *, pages_dir: Path, spec_path: Path, spec_sha256: str, output_dir: Path,
    spec: dict[str, Any], selected: list[str], counts: dict[str, Any],
    inventory: list[dict[str, Any]], exclusions: list[dict[str, Any]], list_raw: bytes,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "result": "VERIFIED",
        "claim_boundary": "deterministic paper-list selection only; no acquisition, admission, training, result, or issue-closure credit",
        "as_of": spec["as_of"],
        "source": {
            "pages_dir": str(pages_dir.resolve(strict=True)),
            "pages": inventory,
            "page_inventory_sha256": _sha256(_canonical(inventory)),
        },
        "spec": {"path": str(spec_path.resolve(strict=True)), "sha256": spec_sha256},
        "selection": {key: spec[key] for key in (
            "selection_label", "license_url", "categories", "category_mode", "date_range", "text_filter"
        )},
        "exclusions": exclusions,
        "counts": counts,
        "outputs": {
            "paper_list": PAPER_LIST_NAME,
            "paper_list_sha256": _sha256(list_raw),
            "paper_id_count": len(selected),
        },
    }
    manifest["receipt_sha256"] = _sha256(_canonical(manifest))
    return manifest


def produce_selection(*, pages_dir: Path, spec_path: Path, spec_sha256: str, output_dir: Path) -> dict[str, Any]:
    pages_dir, spec_path, output_dir = Path(pages_dir), Path(spec_path), Path(output_dir).absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise SelectionRefusal("output already exists")
    if _is_link(output_dir.parent) or not output_dir.parent.is_dir():
        raise SelectionRefusal("output parent must be a regular non-reparse directory")
    spec, selected, counts, inventory, exclusions = _derive(pages_dir, spec_path, spec_sha256)
    list_raw = ("\n".join(selected) + "\n").encode()
    manifest = _manifest(
        pages_dir=pages_dir, spec_path=spec_path, spec_sha256=spec_sha256, output_dir=output_dir,
        spec=spec, selected=selected, counts=counts, inventory=inventory, exclusions=exclusions, list_raw=list_raw,
    )
    staging = output_dir.with_name(f".{output_dir.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir()
    published = False
    try:
        (staging / PAPER_LIST_NAME).write_bytes(list_raw)
        (staging / MANIFEST_NAME).write_bytes(
            (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        )
        verify_selection(staging, expected_final_root=output_dir)
        os.rename(staging, output_dir)
        published = True
        verify_selection(output_dir)
        return manifest
    except BaseException:
        shutil.rmtree(output_dir if published else staging, ignore_errors=True)
        raise


def verify_selection(output_dir: Path, *, expected_final_root: Path | None = None) -> dict[str, Any]:
    output_dir = Path(output_dir).absolute()
    if _is_link(output_dir) or not output_dir.is_dir():
        raise SelectionRefusal("output custody must be a regular non-reparse directory")
    raw, manifest = _read_json(output_dir / MANIFEST_NAME, "selection manifest")
    if set(manifest) != {
        "schema", "result", "claim_boundary", "as_of", "source", "spec", "selection",
        "exclusions", "counts", "outputs", "receipt_sha256",
    } or manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("result") != "VERIFIED":
        raise SelectionRefusal("selection manifest schema is not closed")
    payload = dict(manifest)
    embedded = payload.pop("receipt_sha256", None)
    if embedded != _sha256(_canonical(payload)):
        raise SelectionRefusal("selection manifest self-hash does not rederive")
    source, spec_binding = manifest.get("source"), manifest.get("spec")
    if not isinstance(source, dict) or set(source) != {"pages_dir", "pages", "page_inventory_sha256"}:
        raise SelectionRefusal("selection source binding is not closed")
    if not isinstance(spec_binding, dict) or set(spec_binding) != {"path", "sha256"}:
        raise SelectionRefusal("selection spec binding is not closed")
    spec, selected, counts, inventory, exclusions = _derive(
        Path(source["pages_dir"]), Path(spec_binding["path"]), spec_binding["sha256"]
    )
    list_raw = _regular(output_dir / PAPER_LIST_NAME, "paper list").read_bytes()
    expected_list_raw = ("\n".join(selected) + "\n").encode()
    if list_raw != expected_list_raw:
        raise SelectionRefusal("paper list changed")
    expected = _manifest(
        pages_dir=Path(source["pages_dir"]), spec_path=Path(spec_binding["path"]),
        spec_sha256=spec_binding["sha256"], output_dir=expected_final_root or output_dir,
        spec=spec, selected=selected, counts=counts, inventory=inventory, exclusions=exclusions,
        list_raw=expected_list_raw,
    )
    if manifest != expected:
        raise SelectionRefusal("selection manifest does not rederive")
    if {path.name for path in output_dir.iterdir()} != {PAPER_LIST_NAME, MANIFEST_NAME}:
        raise SelectionRefusal("selection custody contains missing or extra paths")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--spec-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    result = (
        verify_selection(args.output)
        if args.verify
        else produce_selection(
            pages_dir=args.pages_dir,
            spec_path=args.spec,
            spec_sha256=args.spec_sha256,
            output_dir=args.output,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
