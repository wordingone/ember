# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""L4 manifest gate for planned, non-acquired AI-lab shared-text sources."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from jsonschema import Draft202012Validator
from typing import Any, Iterable


_CONNECTOR_RECEIPT_PATH = Path(__file__).resolve().parents[1] / "corpus_connectors" / "receipt.py"
_CONNECTOR_RECEIPT_SPEC = importlib.util.spec_from_file_location(
    "ember_connector_receipt_authority", _CONNECTOR_RECEIPT_PATH
)
if _CONNECTOR_RECEIPT_SPEC is None or _CONNECTOR_RECEIPT_SPEC.loader is None:
    raise RuntimeError("connector receipt authority cannot be loaded")
connector_receipt = importlib.util.module_from_spec(_CONNECTOR_RECEIPT_SPEC)
sys.modules[_CONNECTOR_RECEIPT_SPEC.name] = connector_receipt
_CONNECTOR_RECEIPT_SPEC.loader.exec_module(connector_receipt)

DOMAINS = ("mathematics", "statistics", "physics", "computer_science", "ml_ai", "training_infrastructure", "formal_logic", "software_engineering", "data_evaluation", "scientific_method", "application_worlds")
LICENSES = {"CC0-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "BSD-3-Clause", "PDDL-1.0", "ODC-By-1.0"}
_CONNECTOR_LICENSE_ALIASES = {
    "http://creativecommons.org/publicdomain/zero/1.0/": "CC0-1.0",
}
_HF_DATASET_CARD_LICENSES = {
    "apache-2.0": "Apache-2.0",
    "bsd-3-clause": "BSD-3-Clause",
    "cc-by-4.0": "CC-BY-4.0",
    "cc0-1.0": "CC0-1.0",
    "mit": "MIT",
    "odc-by": "ODC-By-1.0",
}
_UNRESOLVED_EVIDENCE = ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"]


def local_normalizer_v1(raw: bytes) -> tuple[bytes, str]:
    """D3: deterministic raw bytes -> canonical UTF-8 -> content_sha256. Pure, no model.

    Same input on any host produces the same (normalized_bytes, content_sha256). Policy: decode
    strict UTF-8, strip a leading BOM, Unicode-NFC normalize, normalize CRLF/CR newlines to LF,
    strip trailing whitespace per line, ensure exactly one trailing newline.
    """
    text = raw.decode("utf-8-sig", errors="strict")
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = text.strip("\n") + "\n"
    normalized = text.encode("utf-8")
    return normalized, hashlib.sha256(normalized).hexdigest()


def local_license_provenance_v1(
    *,
    content_sha256: str,
    license_spdx: str | list[str],
    evidence: dict[str, Any],
    generator: str = "local-normalizer-v1",
) -> dict[str, Any]:
    """D4: adjudicate (content, declared license, evidence) -> the exact VERIFIED l4_receipt.

    Highest-scrutiny component (resolver spec decision, "PD->CC0" section of the design spec).
    `evidence["kind"]` selects the provenance route:
      - "spdx_repo_license": evidence carries a repo LICENSE-file sha256 + the exact SPDX id it
        declares; license_spdx must match that declared id.
      - "publisher_terms": evidence carries the publisher's stated terms url/sha + the exact
        SPDX id those terms map to (e.g. PLOS's CC-BY-4.0 policy).
      - "hf_dataset_card": evidence binds the exact reopened root README.md and its sha256;
        the leading closed YAML front matter must declare exactly one known license token.
      - "us_gov_federal_authorship": PD->CC0 rule. Evidence must attest the work is authored by
        a US federal employee as part of official duties (17 USC 105) with an agency name and an
        attestation statement; license_spdx must be exactly "CC0-1.0" (there is no "Public
        Domain" SPDX token in the allow-set - L15/L31 of this module).
      - "jurisdiction_expiry": non-US PD or PD-by-age; evidence must carry jurisdiction + the
        expiry/authorship-date basis; license_spdx must be exactly "CC0-1.0".
    Raises ValueError on any inadmissible route; never silently downgrades to a different SPDX.
    Emits the v2 receipt literal on success (schema bump, hardening review 2026-07-20): binds
    `license_spdx` and `evidence_sha256` (sha256 of the canonical evidence JSON) into the
    receipt itself, so the license claim can't be swapped post-hoc without invalidating the
    receipt (adversarial review Finding 1b, state/ember02-resolver-review-findings.md).
    """
    if not isinstance(content_sha256, str) or _HEX.fullmatch(content_sha256) is None:
        raise ValueError("license provenance requires an exact content hash")
    if generator not in {"local-normalizer-v1", "local-tree-root-v1", "pdf-text-extraction-v1"}:
        raise ValueError("license provenance generator is not recognized")
    is_conjunction = isinstance(license_spdx, list)
    if is_conjunction:
        if not license_spdx or license_spdx != sorted(set(license_spdx)):
            raise ValueError("license provenance conjunction must be a closed sorted deduplicated nonempty list")
        if any(not isinstance(item, str) or item not in LICENSES for item in license_spdx):
            raise ValueError("license provenance conjunction is not wholly in the allow-set")
    elif not isinstance(license_spdx, str) or license_spdx not in LICENSES:
        raise ValueError("license provenance target is not in the allow-set")
    if not isinstance(evidence, dict):
        raise ValueError("license provenance evidence is missing")
    kind = evidence.get("kind")
    if is_conjunction and kind != "spdx_repo_license":
        raise ValueError("license provenance conjunction requires pinned repository LICENSE evidence")
    if kind == "spdx_repo_license":
        if not isinstance(evidence.get("license_sha256"), str) or _HEX.fullmatch(evidence["license_sha256"]) is None or evidence.get("declared_spdx") != license_spdx:
            raise ValueError("repo license evidence does not prove the declared SPDX id")
    elif kind == "publisher_terms":
        if not isinstance(evidence.get("terms_url"), str) or not evidence["terms_url"] or evidence.get("declared_spdx") != license_spdx:
            raise ValueError("publisher terms evidence does not prove the declared SPDX id")
    elif kind == "hf_dataset_card":
        if (
            set(evidence) != {"kind", "card_path", "card_sha256", "declared_spdx"}
            or evidence.get("card_path") != "README.md"
            or not isinstance(evidence.get("card_sha256"), str)
            or _HEX.fullmatch(evidence["card_sha256"]) is None
            or evidence.get("declared_spdx") != license_spdx
        ):
            raise ValueError("Hugging Face dataset card evidence does not prove the declared SPDX id")
    elif kind == "us_gov_federal_authorship":
        if license_spdx != "CC0-1.0":
            raise ValueError("US-gov PD provenance only admits under CC0-1.0")
        if not isinstance(evidence.get("agency"), str) or not evidence["agency"] or evidence.get("federal_employee_work_of_authorship") is not True:
            raise ValueError("US-gov federal-authorship attestation is incomplete")
    elif kind == "jurisdiction_expiry":
        if license_spdx != "CC0-1.0":
            raise ValueError("non-US/expiry PD provenance only admits under CC0-1.0")
        if not isinstance(evidence.get("jurisdiction"), str) or not evidence["jurisdiction"] or not evidence.get("expiry_basis"):
            raise ValueError("jurisdiction/expiry PD provenance is incomplete")
    else:
        raise ValueError("license provenance evidence kind is not recognized")
    evidence_sha256 = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if is_conjunction or generator != "local-normalizer-v1":
        return {
            "schema_version": "ember-text-source-receipt-v3", "result": "VERIFIED",
            "source_sha256": content_sha256, "generator": generator,
            "verifier": "local-license-provenance-v1", "model_mediated": False, "borrowed_labels": False,
            "license_spdx": license_spdx, "evidence_sha256": evidence_sha256,
        }
    return {
        "schema_version": "ember-text-source-receipt-v2", "result": "VERIFIED",
        "source_sha256": content_sha256, "generator": "local-normalizer-v1",
        "verifier": "local-license-provenance-v1", "model_mediated": False, "borrowed_labels": False,
        "license_spdx": license_spdx, "evidence_sha256": evidence_sha256,
    }

def adapt_connector_receipt(receipt: dict[str, Any], *, evidence: dict[str, Any]) -> dict[str, Any]:
    """Thin reshape: a tools/corpus_connectors Receipt (schema corpus-connector-receipt-v1) into
    this module's admitted-row fields (content_sha256, license_spdx, license_evidence, l4_receipt).

    Does not rebuild fetch tooling and does not invent verification the connector never
    performed: the connector's own `license_evidence` is free-form prose and cannot by itself
    prove any of the four routes `local_license_provenance_v1` recognizes, so the caller supplies
    the structured provenance route explicitly (the same `evidence` argument that function takes).
    The connector's recorded per-file sha256 is checked against the live file bytes before
    normalization so a receipt cannot be adapted against content it doesn't actually describe.
    """
    if not isinstance(receipt, dict) or receipt.get("schema") != "corpus-connector-receipt-v1":
        raise ValueError("connector receipt schema is not corpus-connector-receipt-v1")
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("connector receipt must carry at least one fetched file for a text-lab source")
    dest_root = receipt.get("dest_root")
    if not isinstance(dest_root, str) or not dest_root:
        raise ValueError("connector receipt dest_root is missing")
    root = Path(dest_root)
    if not root.is_dir() or _is_reparse_or_symlink(root):
        raise ValueError("connector receipt dest_root must be a regular non-reparse directory")

    verified_entries: list[dict[str, Any]] = []
    raw_by_path: dict[str, bytes] = {}
    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ValueError("connector receipt file entry is malformed")
        normalized_path = _normalize_connector_path(entry["path"])
        if normalized_path in seen_paths:
            raise ValueError("connector receipt has a duplicate normalized file path")
        seen_paths.add(normalized_path)
        recorded_bytes = entry["bytes"]
        recorded_sha256 = entry["sha256"]
        if not isinstance(recorded_bytes, int) or isinstance(recorded_bytes, bool) or recorded_bytes < 0:
            raise ValueError("connector receipt file entry has an invalid recorded size")
        if not isinstance(recorded_sha256, str) or _HEX.fullmatch(recorded_sha256) is None:
            raise ValueError("connector receipt file entry has an invalid recorded hash")
        raw_path = _regular_contained_file(root, normalized_path)
        raw_bytes = raw_path.read_bytes()
        if len(raw_bytes) != recorded_bytes:
            raise ValueError("connector receipt file bytes do not match its recorded size")
        recomputed_sha256 = _sha_bytes(raw_bytes)
        if recomputed_sha256 != recorded_sha256:
            raise ValueError("connector receipt file bytes do not match its own recorded hash")
        verified_entries.append({"path": normalized_path, "bytes": len(raw_bytes), "sha256": recomputed_sha256})
        raw_by_path[normalized_path] = raw_bytes

    actual_paths = _listed_data_paths(root)
    if actual_paths != seen_paths:
        missing = sorted(seen_paths - actual_paths)
        extra = sorted(actual_paths - seen_paths)
        if missing:
            raise ValueError(f"connector receipt listed file is missing: {missing[0]}")
        raise ValueError(f"connector receipt destination contains an unlisted file: {extra[0]}")
    total_bytes = sum(entry["bytes"] for entry in verified_entries)
    recorded_total_bytes = receipt.get("total_bytes")
    if (
        not isinstance(recorded_total_bytes, int)
        or isinstance(recorded_total_bytes, bool)
        or recorded_total_bytes != total_bytes
    ):
        raise ValueError("connector receipt total_bytes does not match reopened files")
    manifest_sha256 = _sha_bytes("\n".join(sorted(entry["sha256"] for entry in verified_entries)).encode("utf-8"))
    if receipt.get("sha256_manifest") != manifest_sha256:
        raise ValueError("connector receipt sha256_manifest does not match reopened files")

    raw_license = receipt.get("license")
    if (
        receipt.get("source") == "huggingface"
        and receipt.get("connector") == {"name": "hf_fetch", "version": "v1"}
        and evidence.get("kind") == "hf_dataset_card"
        and isinstance(raw_license, str)
        and raw_license == raw_license.strip()
    ):
        raw_license = _HF_DATASET_CARD_LICENSES.get(raw_license.lower(), raw_license)
    license_spdx = _closed_connector_license(raw_license)
    if isinstance(license_spdx, list) or len(verified_entries) > 1:
        has_repository_license = any(
            PurePosixPath(entry["path"]).name.upper().startswith("LICENSE")
            for entry in verified_entries
        )
        if has_repository_license or evidence.get("kind") != "hf_dataset_card":
            _bind_multi_file_license_artifact(verified_entries, evidence)
        else:
            _bind_hf_dataset_card_license(
                receipt,
                verified_entries,
                raw_by_path,
                evidence,
                license_spdx,
            )
    if len(verified_entries) == 1:
        raw_bytes = raw_by_path[verified_entries[0]["path"]]
        _, content_sha256 = local_normalizer_v1(raw_bytes)
        provenance_generator = "local-normalizer-v1"
    else:
        content_sha256 = _multi_file_content_root(verified_entries)
        provenance_generator = "local-tree-root-v1"
    l4_receipt = local_license_provenance_v1(
        content_sha256=content_sha256,
        license_spdx=license_spdx,
        evidence=evidence,
        generator=provenance_generator,
    )
    return {
        "content_sha256": content_sha256,
        "license_spdx": license_spdx,
        "license_evidence": evidence,
        "l4_receipt": l4_receipt,
    }


def adapt_pdf_extraction_receipt(
    *,
    receipt_path: Path,
    connector_receipt: Path,
    connector_receipt_sha256: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Reopen one governed PDF transform without pretending it was a connector fetch."""
    producer_path = Path(__file__).resolve().parents[2] / "tools" / "corpus_connectors" / "pdf_to_utf8.py"
    if not producer_path.is_file() or _is_reparse_or_symlink(producer_path):
        raise ValueError("PDF extraction reopener is unavailable")
    spec = importlib.util.spec_from_file_location("_ember_pdf_text_extraction_reopener", producer_path)
    if spec is None or spec.loader is None:
        raise ValueError("PDF extraction reopener is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        receipt = module.verify_pdf_text_receipt(
            receipt_path=Path(receipt_path),
            connector_receipt=Path(connector_receipt),
            connector_receipt_sha256=connector_receipt_sha256,
        )
    except Exception as error:
        raise ValueError(str(error)) from error
    source = receipt.get("source")
    output = receipt.get("output")
    if not isinstance(source, dict) or not isinstance(output, dict):
        raise ValueError("PDF extraction receipt identity is incomplete")
    output_path = Path(receipt_path).parent / output.get("path", "")
    if not output_path.is_file() or _is_reparse_or_symlink(output_path):
        raise ValueError("PDF extraction output is not a regular file")
    output_bytes = output_path.read_bytes()
    normalized, content_sha256 = local_normalizer_v1(output_bytes)
    if normalized != output_bytes or content_sha256 != output.get("sha256"):
        raise ValueError("PDF extraction output is not canonical text custody")
    license_spdx = _closed_connector_license(source.get("license"))
    if isinstance(license_spdx, list):
        raise ValueError("PDF extraction source license must be one closed SPDX value")
    l4_receipt = local_license_provenance_v1(
        content_sha256=content_sha256,
        license_spdx=license_spdx,
        evidence=evidence,
        generator="pdf-text-extraction-v1",
    )
    return {
        "content_sha256": content_sha256,
        "license_spdx": license_spdx,
        "license_evidence": evidence,
        "l4_receipt": l4_receipt,
    }


_CONNECTOR_SIDECAR_DIRS = set(connector_receipt.DEFAULT_EXCLUDE_DIRNAMES)
_CONNECTOR_SIDECAR_FILES = {"manifest.jsonl"}


def _normalize_connector_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("connector receipt file path is not a relative contained path")
    portable = value.replace("\\", "/")
    if portable.startswith("/") or re.match(r"^[A-Za-z]:", portable):
        raise ValueError("connector receipt file path is not a relative contained path")
    parts = portable.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("connector receipt file path is not a relative contained path")
    return "/".join(parts)


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _regular_contained_file(root: Path, normalized_path: str) -> Path:
    cursor = root
    for index, part in enumerate(normalized_path.split("/")):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError as exc:
            raise ValueError(f"connector receipt listed file is missing: {normalized_path}") from exc
        if _is_reparse_or_symlink(cursor):
            raise ValueError("connector receipt file path crosses a symlink or reparse point")
        if index < len(normalized_path.split("/")) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("connector receipt file path is not a relative contained path")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError("connector receipt listed path is not a regular file")
    try:
        cursor.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("connector receipt file path is not a relative contained path") from exc
    return cursor


def _is_connector_sidecar(normalized_path: str) -> bool:
    parts = normalized_path.split("/")
    return parts[0] in _CONNECTOR_SIDECAR_DIRS or (
        len(parts) == 1 and parts[0] in _CONNECTOR_SIDECAR_FILES
    )


def _listed_data_paths(root: Path) -> set[str]:
    result: set[str] = set()
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for directory in directories:
            child = current_path / directory
            relative = child.relative_to(root).as_posix()
            if _is_connector_sidecar(relative):
                continue
            if _is_reparse_or_symlink(child):
                raise ValueError("connector receipt destination contains a symlink or reparse point")
            kept_directories.append(directory)
        directories[:] = kept_directories
        for filename in filenames:
            child = current_path / filename
            relative = child.relative_to(root).as_posix()
            if _is_connector_sidecar(relative):
                continue
            if _is_reparse_or_symlink(child):
                raise ValueError("connector receipt destination contains a symlink or reparse point")
            if not child.is_file():
                raise ValueError("connector receipt destination contains a non-regular file")
            result.add(relative)
    return result


def _closed_connector_license(value: Any) -> str | list[str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("connector receipt license is not on the text-lab allow-list")
    value = _CONNECTOR_LICENSE_ALIASES.get(value, value)
    if re.search(r"(?:\bOR\b|\|\|)", value, flags=re.IGNORECASE):
        raise ValueError("connector receipt license is an OR expression and cannot be guessed as a conjunction")
    components = sorted(set(part.strip() for part in re.split(r"[,+]", value) if part.strip()))
    if not components:
        raise ValueError("connector receipt license is not on the text-lab allow-list")
    if any(component not in LICENSES for component in components):
        raise ValueError("connector receipt whole conjunction is not on the text-lab allow-list")
    return components[0] if len(components) == 1 else components


def _multi_file_content_root(entries: list[dict[str, Any]]) -> str:
    canonical_entries = sorted(entries, key=lambda entry: entry["path"].encode("utf-8"))
    payload = json.dumps(canonical_entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _sha_bytes(b"ember-text-source-tree-v1\0" + payload)


def _hf_dataset_card_license(raw: bytes) -> str:
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Hugging Face dataset card is not strict UTF-8") from exc
    if not lines or lines[0] != "---":
        raise ValueError("Hugging Face dataset card lacks leading YAML front matter")
    try:
        close = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("Hugging Face dataset card front matter is not closed") from exc
    declared: list[str] = []
    front_matter = lines[1:close]
    index = 0
    while index < len(front_matter):
        line = front_matter[index]
        if line.lstrip().lower().startswith("license"):
            scalar = re.fullmatch(r"license:\s*([A-Za-z0-9][A-Za-z0-9.-]*)\s*", line)
            if scalar is not None:
                declared.append(scalar.group(1))
            elif line == "license:":
                if index + 1 >= len(front_matter):
                    raise ValueError("Hugging Face dataset card license list is empty")
                item = re.fullmatch(
                    r"\s*-\s+([A-Za-z0-9][A-Za-z0-9.-]*)\s*",
                    front_matter[index + 1],
                )
                if item is None:
                    raise ValueError("Hugging Face dataset card license list item is malformed")
                if index + 2 < len(front_matter) and re.fullmatch(
                    r"[A-Za-z0-9_.-]+:\s*.*", front_matter[index + 2]
                ) is None:
                    raise ValueError("Hugging Face dataset card license list is not closed")
                declared.append(item.group(1))
                index += 1
            else:
                raise ValueError("Hugging Face dataset card license entry is malformed")
        index += 1
    if len(declared) != 1:
        raise ValueError("Hugging Face dataset card must contain exactly one license key")
    canonical = _HF_DATASET_CARD_LICENSES.get(declared[0].lower())
    if canonical is None:
        raise ValueError("Hugging Face dataset card license is not on the closed map")
    return canonical


def _bind_hf_dataset_card_license(
    receipt: dict[str, Any],
    entries: list[dict[str, Any]],
    raw_by_path: dict[str, bytes],
    evidence: dict[str, Any],
    license_spdx: str | list[str],
) -> None:
    if (
        receipt.get("source") != "huggingface"
        or receipt.get("connector") != {"name": "hf_fetch", "version": "v1"}
    ):
        raise ValueError("Hugging Face dataset card evidence requires the closed hf_fetch connector")
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"kind", "card_path", "card_sha256", "declared_spdx"}
        or evidence.get("kind") != "hf_dataset_card"
        or evidence.get("card_path") != "README.md"
        or not isinstance(evidence.get("card_sha256"), str)
        or _HEX.fullmatch(evidence["card_sha256"]) is None
    ):
        raise ValueError("Hugging Face dataset card evidence is malformed")
    matches = [
        entry for entry in entries
        if entry["path"] == "README.md" and entry["sha256"] == evidence["card_sha256"]
    ]
    if len(matches) != 1 or "README.md" not in raw_by_path:
        raise ValueError("Hugging Face dataset card is not bound to the exact reopened README.md")
    card_license = _hf_dataset_card_license(raw_by_path["README.md"])
    if (
        isinstance(license_spdx, list)
        or card_license != license_spdx
        or evidence.get("declared_spdx") != license_spdx
    ):
        raise ValueError("Hugging Face dataset card, connector, and declared SPDX licenses differ")


def _bind_multi_file_license_artifact(entries: list[dict[str, Any]], evidence: dict[str, Any]) -> None:
    if not isinstance(evidence, dict) or evidence.get("kind") != "spdx_repo_license":
        raise ValueError("multi-file conjunctive license requires pinned repository LICENSE evidence")
    license_sha256 = evidence.get("license_sha256")
    matches = [
        entry for entry in entries
        if PurePosixPath(entry["path"]).name.upper().startswith("LICENSE")
        and entry["sha256"] == license_sha256
    ]
    if len(matches) != 1:
        raise ValueError("multi-file conjunctive license is not bound to exactly one reopened LICENSE artifact")

def _root(rows: Iterable[dict[str, Any]], split: str) -> str:
    digest=hashlib.sha256(f"ember-text-lab-corpus-v1\0{split}\0".encode())
    for row in sorted((x for x in rows if x["split"] == split), key=lambda x:(x["domain"],x["source_id"])):
        digest.update(row["domain"].encode()+b"\0"+row["source_id"].encode()+b"\0"+bytes.fromhex(row["content_sha256"]))
    return digest.hexdigest()

def _validate(
    rows: list[dict[str, Any]],
    frozen: set[str],
    *,
    require_domain_floor: bool = True,
) -> None:
    if not rows: raise ValueError("text corpus source set is empty")
    seen=set(); by_domain={domain:0 for domain in DOMAINS}
    for row in rows:
        if not isinstance(row,dict) or set(row) != {"source_id","domain","license_spdx","content_sha256","l4_receipt","split"}: raise ValueError("source row schema is invalid")
        domain=row["domain"]; content=row["content_sha256"]; receipt=row["l4_receipt"]
        if domain not in by_domain or row["split"] not in {"train","heldout"}: raise ValueError("source domain or split is invalid")
        license_spdx = row["license_spdx"]
        if isinstance(license_spdx, list):
            if (
                not license_spdx
                or license_spdx != sorted(set(license_spdx))
                or any(not isinstance(item, str) or item not in LICENSES for item in license_spdx)
            ):
                raise ValueError("source license conjunction is not a closed sorted allow-set")
        elif not isinstance(license_spdx, str) or license_spdx not in LICENSES:
            raise ValueError("source license is not permitted")
        if not isinstance(content,str) or len(content)!=64 or content.lower()!=content: raise ValueError("source content hash is invalid")
        if content in seen: raise ValueError("duplicate source content is forbidden")
        if content in frozen: raise ValueError("source contaminates frozen eval")
        # v2 receipt shape (hardening 2026-07-20): license_spdx must echo the row's declared
        # license, evidence_sha256 is checked for FORMAT here (this shared, unforked check has
        # no evidence dict to re-derive it from); the VERIFIED path additionally RE-DERIVES the
        # whole receipt from the row's license_evidence (validate_authority_index tail) - this
        # check alone is not a truth check, only a shape check, by design.
        evidence_digest = receipt.get("evidence_sha256") if isinstance(receipt, dict) else None
        generator = receipt.get("generator") if isinstance(receipt, dict) else None
        expected_schema = {
            "local-normalizer-v1": "ember-text-source-receipt-v2",
            "local-tree-root-v1": "ember-text-source-receipt-v3",
            "pdf-text-extraction-v1": "ember-text-source-receipt-v3",
        }.get(generator)
        if isinstance(license_spdx, list) and generator != "local-tree-root-v1":
            raise ValueError("source L4 provenance receipt is invalid")
        if not isinstance(receipt,dict) or not isinstance(evidence_digest,str) or _HEX.fullmatch(evidence_digest) is None or expected_schema is None or receipt != {"schema_version":expected_schema,"result":"VERIFIED","source_sha256":content,"generator":generator,"verifier":"local-license-provenance-v1","model_mediated":False,"borrowed_labels":False,"license_spdx":license_spdx,"evidence_sha256":evidence_digest}: raise ValueError("source L4 provenance receipt is invalid")
        seen.add(content); by_domain[domain]+=1
    if require_domain_floor and any(count < 2 for count in by_domain.values()): raise ValueError("each charter domain requires two independent sources")

def build_manifest(entries: Iterable[dict[str, Any]], *, frozen_eval_hashes: set[str]) -> dict[str, Any]:
    rows=[dict(x) for x in entries]; _validate(rows,frozen_eval_hashes)
    return {"schema_version":"ember-text-lab-corpus-manifest-v1","result":"PREFLIGHT_ONLY","boundary":"NO_ACQUISITION_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM","domains":list(DOMAINS),"sources":sorted(rows,key=lambda x:(x["domain"],x["source_id"])),"frozen_eval_hashes":sorted(frozen_eval_hashes),"train_root_sha256":_root(rows,"train"),"heldout_root_sha256":_root(rows,"heldout")}

def validate_manifest(manifest: dict[str, Any], *, frozen_eval_hashes: set[str]) -> dict[str,str]:
    if not isinstance(manifest,dict) or manifest.get("schema_version")!="ember-text-lab-corpus-manifest-v1" or manifest.get("result")!="PREFLIGHT_ONLY": raise ValueError("text corpus manifest is not preflight-only")
    rows=manifest.get("sources")
    if manifest.get("domains") != list(DOMAINS) or not isinstance(rows,list) or set(manifest.get("frozen_eval_hashes",[])) != frozen_eval_hashes: raise ValueError("text corpus manifest binding is invalid")
    _validate(rows,frozen_eval_hashes)
    if manifest.get("train_root_sha256") != _root(rows,"train") or manifest.get("heldout_root_sha256") != _root(rows,"heldout"): raise ValueError("text corpus split root does not match")
    return {"result":"PREFLIGHT_ONLY","train_root_sha256":manifest["train_root_sha256"],"heldout_root_sha256":manifest["heldout_root_sha256"]}

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_AUTHORITY_INDEX = "data/ember-restart-3b/text-lab-authority-index-v1.json"
_AUTHORITY_INDEX_SCHEMA_V1 = "ember-text-lab-authority-index-v1"
_AUTHORITY_INDEX_SCHEMA_V2 = "ember-text-lab-authority-index-v2"
_UNRESOLVED_FIELDS = {"source_id", "domain", "split", "admission", "required_evidence", "allowed_license_spdx"}
_ADMITTED_FIELDS = _UNRESOLVED_FIELDS | {"content_sha256", "license_spdx", "l4_receipt", "license_evidence"}
_PARTITION_ADMITTED_FIELDS = _UNRESOLVED_FIELDS | {
    "content_sha256", "license_partition_receipt", "license_partition_sha256", "l4_receipt",
}
_ADMITTED_ROW_FIELDS = ("source_id", "domain", "license_spdx", "content_sha256", "l4_receipt", "split")
_FROZEN_EVAL_HASHES_PATH = "data/ember-restart-3b/text-lab-frozen-eval-hashes-v1.json"


def _frozen_eval_hashes(root: Path) -> set[str]:
    """D5: load the on-disk frozen-eval registry; absent file -> empty set (never an error)."""
    path = (root / _FROZEN_EVAL_HASHES_PATH)
    if not path.is_file():
        return set()
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict) or payload.get("schema_version") != "ember-text-lab-frozen-eval-hashes-v1" or not isinstance(payload.get("hashes"), list):
        raise ValueError("frozen eval hash registry is malformed")
    hashes = payload["hashes"]
    if not all(isinstance(value, str) and _HEX.fullmatch(value) for value in hashes):
        raise ValueError("frozen eval hash registry is malformed")
    return set(hashes)

def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _authority_split_root(rows: Iterable[dict[str, Any]], split: str) -> str:
    digest = hashlib.sha256(f"ember-text-lab-candidate-descriptor-v2\0{split}\0".encode("utf-8"))
    fields = ("domain", "split", "source_id", "admission", "required_evidence", "allowed_license_spdx")
    for row in sorted((item for item in rows if item.get("split") == split), key=lambda item: (item.get("domain", ""), item.get("source_id", ""))):
        descriptor = {field: row.get(field) for field in fields}
        encoded = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()

def _path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("authority path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("authority path is not exact repository-relative")
    path = (root / relative).resolve()
    if not path.is_file() or root.resolve() not in path.parents:
        raise ValueError("authority path is absent or escapes root")
    return path

def _external_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("external authority path is invalid")
    relative = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        relative.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in relative.parts
        or relative.as_posix() != value
    ):
        raise ValueError("external authority path is not exact root-relative")
    unresolved_root = root.absolute()
    try:
        root_metadata = unresolved_root.lstat()
    except OSError as exc:
        raise ValueError("external authority root is absent") from exc
    root_attributes = getattr(root_metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(root_metadata.st_mode) or (reparse_flag and root_attributes & reparse_flag):
        raise ValueError("external authority root is invalid or reparsed")
    root = unresolved_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("external authority root is invalid or reparsed")
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ValueError("external authority path is absent") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (reparse_flag and attributes & reparse_flag):
            raise ValueError("external authority path contains a reparse point")
    resolved = candidate.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("external authority path is absent, non-regular, or escapes root")
    return resolved


def _partition_receipt_path(authority_root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("partition authority path is invalid")
    windows = PureWindowsPath(value)
    candidate = Path(value)
    if not (candidate.is_absolute() or windows.is_absolute() or windows.drive):
        return _external_path(authority_root, value)
    if not candidate.is_absolute():
        raise ValueError("partition authority absolute path is invalid on this host")
    candidate = candidate.absolute()
    for current in (candidate, *candidate.parents):
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ValueError("partition authority path is absent") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (reparse_flag and attributes & reparse_flag):
            raise ValueError("partition authority path contains a reparse point")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("partition authority path is absent or non-regular")
    return resolved

def _bound_json(root: Path, binding: object, *, external_root: Path | None = None) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "schema"}:
        raise ValueError("authority artifact binding is invalid")
    expected = binding["sha256"]
    if not isinstance(expected, str) or _HEX.fullmatch(expected) is None:
        raise ValueError("authority hash is invalid")
    payload_path = _external_path(external_root, binding["path"]) if external_root is not None else _path(root, binding["path"])
    payload = payload_path.read_bytes()
    if _sha_bytes(payload) != expected:
        raise ValueError("authority bytes do not match the bound hash")
    value = json.loads(payload)
    if not isinstance(value, dict): raise ValueError("authority JSON must be an object")
    schema = binding["schema"]
    if not isinstance(schema, dict): raise ValueError("authority schema binding is invalid")
    schema_bytes = _path(root, schema.get("path")).read_bytes()
    if _sha_bytes(schema_bytes) != schema.get("sha256"): raise ValueError("authority schema bytes are not bound")
    schema_value=json.loads(schema_bytes)
    if schema_value.get("$schema") != "https://json-schema.org/draft/2020-12/schema": raise ValueError("authority schema is not Draft 2020-12")
    errors=sorted(Draft202012Validator(schema_value).iter_errors(value),key=str)
    if errors: raise ValueError("authority schema rejects bytes: "+errors[0].message)
    return payload,value


def _validate_partition_authority_row(repo_root: Path, authority_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    """Reopen the exact partition receipt and every source/file/blob join it binds."""
    if not isinstance(row, dict) or set(row) != _PARTITION_ADMITTED_FIELDS:
        raise ValueError("partition authority row is not a closed alternative")
    content = row.get("content_sha256")
    receipt_sha = row.get("license_partition_sha256")
    if not isinstance(content, str) or _HEX.fullmatch(content) is None:
        raise ValueError("partition authority content root is invalid")
    if not isinstance(receipt_sha, str) or _HEX.fullmatch(receipt_sha) is None:
        raise ValueError("partition authority receipt hash is invalid")
    receipt_path = _partition_receipt_path(Path(authority_root), row.get("license_partition_receipt"))
    receipt_bytes = receipt_path.read_bytes()
    if _sha_bytes(receipt_bytes) != receipt_sha:
        raise ValueError("partition receipt bytes do not match the bound hash")
    producer_path = _path(repo_root.resolve(), "tools/ember-restart-3b/mint_github_license_partition.py")
    spec = importlib.util.spec_from_file_location("_ember_github_license_partition_reopener", producer_path)
    if spec is None or spec.loader is None:
        raise ValueError("partition receipt reopener is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    receipt = module.validate_partition_receipt(receipt_path)
    if receipt.get("producer_sha256") != _sha_bytes(producer_path.read_bytes()):
        raise ValueError("partition receipt producer bytes changed")
    if any(receipt.get(field) != row.get(field) for field in ("source_id", "split", "domain")):
        raise ValueError("partition receipt identity does not match the admitted row")
    if receipt.get("partition_root_sha256") != content:
        raise ValueError("partition receipt root does not match row content identity")
    repositories = receipt.get("repositories")
    if not isinstance(repositories, list) or any(
        repository.get("declared_spdx") not in row.get("allowed_license_spdx", [])
        or any(item.get("declared_spdx") != repository.get("declared_spdx") for item in repository.get("files", []))
        for repository in repositories
        if isinstance(repository, dict)
    ):
        raise ValueError("partition receipt contains a disallowed or mismatched SPDX value")
    expected_l4 = {
        "schema_version": "ember-text-source-partition-receipt-v1",
        "result": "VERIFIED",
        "source_sha256": content,
        "generator": "github-license-partition-v1",
        "verifier": "github-license-partition-reopen-v1",
        "model_mediated": False,
        "borrowed_labels": False,
        "license_partition_sha256": receipt_sha,
    }
    if row.get("l4_receipt") != expected_l4:
        raise ValueError("partition authority L4 receipt is invalid")
    return receipt

def _commit(root: Path) -> str:
    value=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],text=True,capture_output=True,check=False).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}",value) is None: raise ValueError("exact source commit is unavailable")
    return value

def _protected_identifier_sets(root: Path, protected: list[object]) -> dict[str, set[str]]:
    if not protected:
        raise ValueError("protected evaluation registry is empty")
    expected = {"benchmark_id", "custody_manifest_path", "custody_manifest_sha256", "custody_state", "evidence", "protected_identifiers"}
    result = {"origin_id": set(), "snapshot_sha256": set(), "chunk_sha256": set(), "content_sha256": set()}
    seen: set[str] = set()
    for entry in protected:
        if not isinstance(entry, dict) or set(entry) != expected or not isinstance(entry["benchmark_id"], str) or entry["benchmark_id"] in seen:
            raise ValueError("protected evaluation registry entry is invalid")
        seen.add(entry["benchmark_id"])
        path = _path(root, entry["custody_manifest_path"])
        payload = path.read_bytes()
        if _sha_bytes(payload) != entry["custody_manifest_sha256"]:
            raise ValueError("protected custody manifest bytes changed")
        manifest = json.loads(payload)
        evidence = entry["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {"upstream_tree_git_sha1", "license_sha256", "answer_dictionary_sha256", "eligible_id_set_sha256", "evaluator_sha256"}:
            raise ValueError("protected custody evidence is invalid")
        split = manifest.get("split", {}) if isinstance(manifest, dict) else {}
        evaluator = manifest.get("evaluator", {}) if isinstance(manifest, dict) else {}
        observed = {
            "upstream_tree_git_sha1": manifest.get("upstream_tree_git_sha1"),
            "license_sha256": manifest.get("license_sha256"),
            "answer_dictionary_sha256": split.get("answer_dictionary_sha256") if isinstance(split, dict) else None,
            "eligible_id_set_sha256": split.get("eligible_id_set_sha256") if isinstance(split, dict) else None,
            "evaluator_sha256": evaluator.get("sha256") if isinstance(evaluator, dict) else None,
        }
        if manifest.get("benchmark_id") != entry["benchmark_id"] or observed != evidence:
            raise ValueError("protected custody evidence does not match its manifest")
        identifiers = entry["protected_identifiers"]
        if not isinstance(identifiers, list):
            raise ValueError("protected identifiers are invalid")
        for identifier in identifiers:
            if not isinstance(identifier, dict) or set(identifier) != {"kind", "value"} or identifier["kind"] not in result or not isinstance(identifier["value"], str):
                raise ValueError("protected identifier is invalid")
            result[identifier["kind"]].add(identifier["value"])
    return result

def validate_authority_index(
    repo_root: Path,
    *,
    index_relative: str = _AUTHORITY_INDEX,
    external_authority_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the non-acquired, exact-byte text authority before shared-text use.

    v1 (`ember-text-lab-authority-index-v1`) is the original, unconditional-refusal schema:
    behavior here is BYTE-IDENTICAL to before this function grew a v2 branch — it can never
    return VERIFIED. v2 (`ember-text-lab-authority-index-v2`) additionally accepts candidate
    rows with `admission=="ADMITTED"` (carrying content_sha256/license_spdx/l4_receipt) and,
    ONLY when all 44 slots are ADMITTED and every admitted-row check (reusing `_validate`,
    never forked) passes, returns VERIFIED. Any single unadmitted slot or failed check on the
    v2 path falls through to the SAME NOT_ADMITTED_SOURCE_EVIDENCE_MISSING terminal v1 returns.
    """
    root=repo_root.resolve()
    authority_root = external_authority_root if external_authority_root is not None else None
    index_path = _external_path(authority_root, index_relative) if authority_root is not None else _path(root, index_relative)
    index_bytes=index_path.read_bytes(); index=json.loads(index_bytes)
    if not isinstance(index,dict) or set(index)!={"schema_version","result","boundary","registry","receipt_bundle","corpus","input_identity"}: raise ValueError("text authority index is not closed")
    if index["schema_version"] not in (_AUTHORITY_INDEX_SCHEMA_V1, _AUTHORITY_INDEX_SCHEMA_V2) or index["result"]!="PREFLIGHT_ONLY": raise ValueError("text authority index is not preflight-only")
    is_v2 = index["schema_version"] == _AUTHORITY_INDEX_SCHEMA_V2
    registry_bytes,registry=_bound_json(root,index["registry"]); bundle_bytes,bundle=_bound_json(root,index["receipt_bundle"], external_root=authority_root); corpus_bytes,corpus=_bound_json(root,index["corpus"], external_root=authority_root); _,identity=_bound_json(root,index["input_identity"], external_root=authority_root)
    if corpus.get("registry_sha256")!=_sha_bytes(registry_bytes) or corpus.get("receipt_bundle_sha256")!=_sha_bytes(bundle_bytes): raise ValueError("corpus does not bind external authority")
    if identity.get("corpus_sha256")!=_sha_bytes(corpus_bytes) or not isinstance(identity.get("source_base_commit"),str) or re.fullmatch(r"[0-9a-f]{40}",identity["source_base_commit"]) is None: raise ValueError("input identity does not bind exact authority")
    base_check = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", identity["source_base_commit"], "HEAD"], capture_output=True, check=False)
    if base_check.returncode != 0: raise ValueError("input identity source-base commit is not a live ancestor")
    code_files = identity.get("code_files")
    expected_code = {"text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py", "train": "tools/ember-restart-3b/train.py", "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py"}
    if not isinstance(code_files, dict) or set(code_files) != set(expected_code): raise ValueError("input identity code binding is invalid")
    for name, relative in expected_code.items():
        if code_files[name] != _sha_bytes(_path(root, relative).read_bytes()): raise ValueError("input identity code bytes changed")

    rows = corpus.get("sources"); candidates = bundle.get("candidates"); protected = registry.get("protected")
    ok_bundle_results = {"UNRESOLVED_CANDIDATE", "RESOLVED"} if is_v2 else {"UNRESOLVED_CANDIDATE"}
    if bundle.get("result") not in ok_bundle_results:
        raise ValueError("unresolved candidate bundle result is invalid")
    if not isinstance(rows, list) or not isinstance(candidates, list) or not isinstance(protected, list):
        raise ValueError("authority payload is incomplete")
    protected_identifiers = _protected_identifier_sets(root, protected)
    candidate_map = {item.get("source_id"): item for item in candidates if isinstance(item, dict)}
    if len(candidate_map) != len(candidates):
        raise ValueError("candidate source mapping is ambiguous")
    by_domain: dict[tuple[str, str], int] = {}
    seen: set[str] = set()
    admitted_rows: list[dict[str, Any]] = []
    admitted_evidence_rows: list[dict[str, Any]] = []
    partition_rows: list[dict[str, Any]] = []
    admitted_content_hashes: list[str] = []
    all_admitted = True
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("source_id"), str) or row["source_id"] in seen:
            raise ValueError("candidate descriptor is invalid or duplicated")
        admission = row.get("admission")
        row_is_admitted = is_v2 and admission == "ADMITTED"
        if row_is_admitted:
            if set(row) not in (_ADMITTED_FIELDS, _PARTITION_ADMITTED_FIELDS):
                raise ValueError("candidate descriptor is invalid or duplicated")
        else:
            if set(row) != _UNRESOLVED_FIELDS: raise ValueError("candidate descriptor is invalid or duplicated")
            all_admitted = False
        if not row["source_id"].startswith("candidate-") or row.get("domain") not in DOMAINS or row.get("split") not in {"train", "heldout"}:
            raise ValueError("candidate slot, domain, or split is invalid")
        ok_admission = {"UNRESOLVED_CANDIDATE", "ADMITTED"} if is_v2 else {"UNRESOLVED_CANDIDATE"}
        if admission not in ok_admission or row.get("required_evidence") != _UNRESOLVED_EVIDENCE or row.get("allowed_license_spdx") != sorted(LICENSES):
            raise ValueError("candidate descriptor has unverified authority claims")
        if candidate_map.get(row["source_id"]) != row:
            raise ValueError("candidate bundle does not bind exact descriptor bytes")
        seen.add(row["source_id"])
        by_domain[(row["domain"], row["split"])] = by_domain.get((row["domain"], row["split"]), 0) + 1
        if row_is_admitted:
            admitted_content_hashes.append(row["content_sha256"])
            if set(row) == _PARTITION_ADMITTED_FIELDS:
                partition_rows.append(row)
            else:
                admitted_rows.append({field: row[field] for field in _ADMITTED_ROW_FIELDS})
                admitted_evidence_rows.append({
                    "content_sha256": row["content_sha256"], "license_spdx": row["license_spdx"],
                    "license_evidence": row["license_evidence"], "l4_receipt": row["l4_receipt"],
                })
    if len(rows) != 44 or {row.get("domain") for row in rows} != set(DOMAINS):
        raise ValueError("authority corpus lacks eleven-domain source matrix")
    for domain in DOMAINS:
        if by_domain.get((domain, "train")) != 2 or by_domain.get((domain, "heldout")) != 2:
            raise ValueError("domain requires two train and two heldout candidate slots")
    if corpus.get("train_root_sha256") != _authority_split_root(rows, "train") or corpus.get("heldout_root_sha256") != _authority_split_root(rows, "heldout"):
        raise ValueError("authority corpus split root does not match")

    # A partial v2 successor still makes row-local `admission: ADMITTED` claims even though
    # the corpus as a whole remains NOT_ADMITTED. Validate those admitted rows now, before
    # the terminal partial return: exact L4 literal, duplicate content, protected-eval
    # exclusion, and evidence re-derivation cannot be deferred until all 44 slots resolve.
    if admitted_rows:
        _validate(
            admitted_rows,
            protected_identifiers["content_sha256"],
            require_domain_floor=False,
        )
        for evidence_row in admitted_evidence_rows:
            recomputed = local_license_provenance_v1(
                content_sha256=evidence_row["content_sha256"],
                license_spdx=evidence_row["license_spdx"],
                evidence=evidence_row["license_evidence"],
                generator=evidence_row["l4_receipt"].get("generator", ""),
            )
            if recomputed != evidence_row["l4_receipt"]:
                raise ValueError("source license evidence does not re-derive the claimed receipt")
    partition_authority_root = authority_root if authority_root is not None else root
    for partition_row in partition_rows:
        _validate_partition_authority_row(root, partition_authority_root, partition_row)
    if (
        len(set(admitted_content_hashes)) != len(admitted_content_hashes)
        or any(value in protected_identifiers["content_sha256"] for value in admitted_content_hashes)
    ):
        raise ValueError("admitted source content is duplicated or protected")

    base_receipt = {
        "authority_index_sha256": _sha_bytes(index_bytes),
        "registry_sha256": _sha_bytes(registry_bytes),
        "receipt_bundle_sha256": _sha_bytes(bundle_bytes),
        "corpus_sha256": _sha_bytes(corpus_bytes),
        "input_identity_sha256": _sha_bytes((
            _external_path(authority_root, index["input_identity"]["path"])
            if authority_root is not None
            else _path(root, index["input_identity"]["path"])
        ).read_bytes()),
        "train_root_sha256": corpus["train_root_sha256"],
        "heldout_root_sha256": corpus["heldout_root_sha256"],
        "domain_count": 11,
        "train_source_count": sum(x["split"] == "train" for x in rows),
        "heldout_source_count": sum(x["split"] == "heldout" for x in rows),
        "source_base_commit": identity["source_base_commit"],
        "code_files": code_files,
    }
    if not (is_v2 and all_admitted and bundle.get("result") == "RESOLVED"):
        return {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING", **base_receipt}

    # D2 VERIFIED path: all 44 slots ADMITTED on a v2 index + RESOLVED bundle. Reuse the
    # manifest-layer `_validate` verbatim (license set-membership, content-hash format,
    # no-dup-content, frozen-eval exclusion, exact l4_receipt literal) — never forked.
    #
    # Hardening 2026-07-20 (adversarial review, state/ember02-resolver-review-findings.md):
    # the frozen-eval registry must be PRESENT and POPULATED to reach VERIFIED — D5's loader
    # silently treats an absent file as "no protected content" for the manifest layer's own
    # callers, but that would let VERIFIED be reached with ZERO heldout-contamination
    # protection wired in (Finding 3). Absent/empty is a hard refusal here, never a fallback.
    frozen_path = root / _FROZEN_EVAL_HASHES_PATH
    if not frozen_path.is_file():
        raise ValueError("frozen eval hash registry is required for VERIFIED and is absent")
    frozen_hashes = _frozen_eval_hashes(root)
    if not frozen_hashes:
        raise ValueError("frozen eval hash registry is required for VERIFIED and is empty")
    _validate(admitted_rows, frozen_hashes, require_domain_floor=not partition_rows)
    if any(value in frozen_hashes for value in admitted_content_hashes):
        raise ValueError("source contaminates frozen eval")

    return {"result": "VERIFIED", **base_receipt}
