#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministically extract receipt-bound PDFs into canonical UTF-8 custody."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "ember-pdf-text-extraction-receipt-v1"
NORMALIZATION = "ember-pdf-text-nfc-lf-v1"
PYPDF_VERSION = "6.16.1"
PYPDF_WHEEL_SHA256 = "63fec31c4092ae50b6729beedcb469055b60d20c834bde1c402df241f371f644"
PYTHON_MAJOR_MINOR = "3.10"
OUTPUT_NAME = "document.txt"
RECEIPT_NAME = "pdf-text-extraction-receipt.json"
DEFAULT_MAX_PAGES = 4096
DEFAULT_MAX_DECODED_CONTENT_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 512 * 1024 * 1024
EXTRACTOR_SEMANTICS_VERSION = "v2"
_HEX = re.compile(r"^[0-9a-f]{64}$")
_PGF_INVALID_PREFIXES = (
    b"obj @pgfcolorspaces ",
    b"put @resources << /ColorSpace @pgfcolorspaces >>",
    b"put @pgfcolorspaces <<  /pgfprgb [/Pattern /DeviceRGB]  >>",
    b"pagesize width ",
)
_AUDIT_KEYS = {
    "extractor_semantics_version",
    "sanitized_pages",
    "pgf_removed_line_count",
    "surrogate_pair_count",
    "escaped_surrogate_count",
}


class PdfExtractionRefusal(ValueError):
    """The requested extraction cannot satisfy the closed custody contract."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _regular_file(path: Path, label: str) -> Path:
    if _is_reparse_or_symlink(path) or not path.is_file():
        raise PdfExtractionRefusal(f"{label} must be a regular non-reparse file")
    return path


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = _regular_file(path, label).read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PdfExtractionRefusal(f"{label} must be strict UTF-8 JSON") from error
    if not isinstance(parsed, dict):
        raise PdfExtractionRefusal(f"{label} must contain one JSON object")
    return raw, parsed


def normalize_extracted_text(text: str) -> str:
    if not isinstance(text, str):
        raise PdfExtractionRefusal("extracted text must be Unicode")
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.strip("\n") + "\n"


def sanitize_invalid_pgf_content(raw: bytes) -> tuple[bytes, int]:
    """Remove only the four frozen invalid PGF preamble line prefixes."""
    lines = raw.splitlines(keepends=True)
    kept = [line for line in lines if not line.strip().startswith(_PGF_INVALID_PREFIXES)]
    return b"".join(kept), len(lines) - len(kept)


def repair_extracted_surrogates(text: str) -> tuple[str, int, int]:
    """Combine valid UTF-16 pairs and visibly escape only isolated units."""
    output: list[str] = []
    paired = escaped = 0
    index = 0
    while index < len(text):
        codepoint = ord(text[index])
        if 0xD800 <= codepoint <= 0xDBFF and index + 1 < len(text):
            low = ord(text[index + 1])
            if 0xDC00 <= low <= 0xDFFF:
                output.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00))
                paired += 1
                index += 2
                continue
        if 0xD800 <= codepoint <= 0xDFFF:
            output.append(f"\\u{codepoint:04X}")
            escaped += 1
        else:
            output.append(text[index])
        index += 1
    return "".join(output), paired, escaped


def validate_extraction_audit(audit: dict[str, Any], *, page_count: int) -> None:
    if not isinstance(audit, dict) or set(audit) != _AUDIT_KEYS:
        raise PdfExtractionRefusal("PDF extraction v2 audit schema is not closed")
    if audit.get("extractor_semantics_version") != EXTRACTOR_SEMANTICS_VERSION:
        raise PdfExtractionRefusal("PDF extraction semantics identity changed")
    for key in ("pgf_removed_line_count", "surrogate_pair_count", "escaped_surrogate_count"):
        value = audit.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PdfExtractionRefusal("PDF extraction v2 audit count is invalid")
    pages = audit.get("sanitized_pages")
    if not isinstance(pages, list):
        raise PdfExtractionRefusal("PDF extraction sanitizer audit is invalid")
    indexes: list[int] = []
    removed_total = 0
    for row in pages:
        if not isinstance(row, dict) or set(row) != {
            "page_index",
            "removed_line_count",
            "pre_sha256",
            "post_sha256",
        }:
            raise PdfExtractionRefusal("PDF extraction sanitizer page audit is not closed")
        index = row.get("page_index")
        removed = row.get("removed_line_count")
        pre = row.get("pre_sha256")
        post = row.get("post_sha256")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= page_count
            or not isinstance(removed, int)
            or isinstance(removed, bool)
            or removed <= 0
            or not isinstance(pre, str)
            or _HEX.fullmatch(pre) is None
            or not isinstance(post, str)
            or _HEX.fullmatch(post) is None
            or pre == post
        ):
            raise PdfExtractionRefusal("PDF extraction sanitizer page audit is invalid")
        indexes.append(index)
        removed_total += removed
    if indexes != sorted(set(indexes)) or audit.get("pgf_removed_line_count") != removed_total:
        raise PdfExtractionRefusal("PDF extraction sanitizer totals do not rederive")


def require_runtime_contract(*, python_major_minor: str, pypdf_version: str) -> None:
    if python_major_minor != PYTHON_MAJOR_MINOR:
        raise PdfExtractionRefusal(f"PDF extraction requires Python {PYTHON_MAJOR_MINOR}")
    if pypdf_version != PYPDF_VERSION:
        raise PdfExtractionRefusal(f"PDF extraction requires pypdf {PYPDF_VERSION}")


def _load_pypdf() -> Any:
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as error:
        raise PdfExtractionRefusal(f"PDF extraction requires pypdf {PYPDF_VERSION}") from error
    require_runtime_contract(
        python_major_minor=f"{sys.version_info.major}.{sys.version_info.minor}",
        pypdf_version=str(getattr(pypdf, "__version__", "")),
    )
    return pypdf


def _package_tree_sha256(pypdf: Any) -> str:
    package_file = Path(str(pypdf.__file__))
    package_root = package_file.parent
    if _is_reparse_or_symlink(package_root) or not package_root.is_dir():
        raise PdfExtractionRefusal("pypdf package root must be a regular non-reparse directory")
    entries: list[dict[str, Any]] = []
    for candidate in sorted(package_root.rglob("*.py"), key=lambda item: item.relative_to(package_root).as_posix()):
        if _is_reparse_or_symlink(candidate) or not candidate.is_file():
            raise PdfExtractionRefusal("pypdf package tree contains a non-regular Python source")
        raw = candidate.read_bytes()
        entries.append(
            {
                "path": candidate.relative_to(package_root).as_posix(),
                "bytes": len(raw),
                "sha256": _sha256(raw),
            }
        )
    if not entries:
        raise PdfExtractionRefusal("pypdf package tree contains no Python sources")
    return _sha256(_canonical_json(entries))


def _source_pdf(
    connector_receipt: Path,
    connector_receipt_sha256: str,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    if _HEX.fullmatch(connector_receipt_sha256) is None:
        raise PdfExtractionRefusal("connector receipt hash is invalid")
    receipt_bytes, receipt = _read_json(connector_receipt, "connector receipt")
    if _sha256(receipt_bytes) != connector_receipt_sha256:
        raise PdfExtractionRefusal("connector receipt bytes do not match the bound hash")
    if receipt.get("schema") != "corpus-connector-receipt-v1":
        raise PdfExtractionRefusal("connector receipt schema is not corpus-connector-receipt-v1")
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise PdfExtractionRefusal("PDF extraction requires exactly one connector-listed file")
    entry = files[0]
    if set(entry) != {"path", "bytes", "sha256"}:
        raise PdfExtractionRefusal("connector receipt file entry is malformed")
    relative = entry.get("path")
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise PdfExtractionRefusal("connector receipt PDF path is invalid")
    portable = relative.replace("\\", "/")
    pure = PurePosixPath(portable)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise PdfExtractionRefusal("connector receipt PDF path is not contained")
    root_value = receipt.get("dest_root")
    if not isinstance(root_value, str) or not root_value:
        raise PdfExtractionRefusal("connector receipt destination root is missing")
    root = Path(root_value)
    if _is_reparse_or_symlink(root) or not root.is_dir():
        raise PdfExtractionRefusal("connector receipt destination root is not a regular directory")
    pdf_path = root.joinpath(*pure.parts)
    _regular_file(pdf_path, "source PDF")
    try:
        pdf_path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise PdfExtractionRefusal("source PDF is outside connector custody") from error
    pdf_bytes = pdf_path.read_bytes()
    recorded_bytes = entry.get("bytes")
    recorded_sha256 = entry.get("sha256")
    if (
        not isinstance(recorded_bytes, int)
        or isinstance(recorded_bytes, bool)
        or recorded_bytes != len(pdf_bytes)
        or not isinstance(recorded_sha256, str)
        or _HEX.fullmatch(recorded_sha256) is None
        or recorded_sha256 != _sha256(pdf_bytes)
    ):
        raise PdfExtractionRefusal("source PDF bytes do not match the connector receipt")
    if receipt.get("total_bytes") != len(pdf_bytes):
        raise PdfExtractionRefusal("source PDF byte count does not match connector total_bytes")
    if receipt.get("sha256_manifest") != _sha256(recorded_sha256.encode("utf-8")):
        raise PdfExtractionRefusal("source PDF manifest hash does not rederive")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise PdfExtractionRefusal("source PDF magic is invalid")
    return receipt, pdf_path, entry


def _extract_pdf(
    pdf_path: Path,
    *,
    max_pages: int,
    max_decoded_content_bytes: int,
    max_output_bytes: int,
) -> tuple[bytes, int, int, dict[str, Any]]:
    for label, value in (
        ("max_pages", max_pages),
        ("max_decoded_content_bytes", max_decoded_content_bytes),
        ("max_output_bytes", max_output_bytes),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise PdfExtractionRefusal(f"{label} must be a positive integer")
    pypdf = _load_pypdf()
    try:
        reader = pypdf.PdfReader(str(pdf_path), strict=False)
    except Exception as error:
        raise PdfExtractionRefusal("source PDF could not be parsed by the pinned extractor") from error
    page_count = len(reader.pages)
    if page_count <= 0 or page_count > max_pages:
        raise PdfExtractionRefusal("source PDF page count exceeds the closed bound")
    decoded_total = 0
    page_text: list[str] = []
    sanitized_pages: list[dict[str, Any]] = []
    for page_index, page in enumerate(reader.pages):
        try:
            contents = page.get_contents()
            decoded = b"" if contents is None else contents.get_data()
        except Exception as error:
            raise PdfExtractionRefusal("source PDF decoded content could not be reopened") from error
        decoded_total += len(decoded)
        if decoded_total > max_decoded_content_bytes:
            raise PdfExtractionRefusal("source PDF decoded content exceeds the closed bound")
        try:
            page_text.append(page.extract_text() or "")
        except Exception as initial_error:
            sanitized, removed_lines = sanitize_invalid_pgf_content(decoded)
            if removed_lines == 0:
                raise PdfExtractionRefusal("source PDF text extraction failed without fallback") from initial_error
            original = None
            contents_name = None
            try:
                from pypdf.generic import DecodedStreamObject, NameObject

                contents_name = NameObject("/Contents")
                original = page.raw_get(contents_name)
                replacement = DecodedStreamObject()
                replacement.set_data(sanitized)
                page[contents_name] = replacement
                page_text.append(page.extract_text() or "")
            except Exception as sanitized_error:
                raise PdfExtractionRefusal(
                    "source PDF text extraction failed after exact-prefix PGF repair"
                ) from sanitized_error
            finally:
                if original is not None and contents_name is not None:
                    page[contents_name] = original
            sanitized_pages.append({
                "page_index": page_index,
                "removed_line_count": removed_lines,
                "pre_sha256": _sha256(decoded),
                "post_sha256": _sha256(sanitized),
            })
    repaired_text, surrogate_pair_count, escaped_surrogate_count = repair_extracted_surrogates(
        "\n".join(page_text)
    )
    output = normalize_extracted_text(repaired_text).encode("utf-8")
    if not output.strip():
        raise PdfExtractionRefusal("source PDF extraction produced empty text")
    if len(output) > max_output_bytes:
        raise PdfExtractionRefusal("extracted output byte count exceeds the closed bound")
    audit = {
        "extractor_semantics_version": EXTRACTOR_SEMANTICS_VERSION,
        "sanitized_pages": sanitized_pages,
        "pgf_removed_line_count": sum(row["removed_line_count"] for row in sanitized_pages),
        "surrogate_pair_count": surrogate_pair_count,
        "escaped_surrogate_count": escaped_surrogate_count,
    }
    validate_extraction_audit(audit, page_count=page_count)
    return output, page_count, decoded_total, audit


def _producer_sha256() -> str:
    return _sha256(_regular_file(Path(__file__), "PDF extraction producer").read_bytes())


def _receipt_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    return payload


def _validate_receipt_shape(receipt: dict[str, Any]) -> None:
    if set(receipt) != {
        "schema",
        "result",
        "claim_boundary",
        "source",
        "extractor",
        "output",
        "receipt_sha256",
    }:
        raise PdfExtractionRefusal("PDF extraction receipt schema is not closed")
    if receipt.get("schema") != SCHEMA or receipt.get("result") != "VERIFIED":
        raise PdfExtractionRefusal("PDF extraction receipt result is invalid")
    claimed = receipt.get("receipt_sha256")
    if not isinstance(claimed, str) or claimed != _sha256(_canonical_json(_receipt_payload(receipt))):
        raise PdfExtractionRefusal("PDF extraction receipt self-hash does not rederive")


def produce_pdf_text_receipt(
    *,
    connector_receipt: Path,
    connector_receipt_sha256: str,
    output_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_decoded_content_bytes: int = DEFAULT_MAX_DECODED_CONTENT_BYTES,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    if output_dir.exists() or output_dir.is_symlink():
        raise PdfExtractionRefusal("output directory already exists")
    parent = output_dir.parent
    if _is_reparse_or_symlink(parent) or not parent.is_dir():
        raise PdfExtractionRefusal("output parent must be a regular non-reparse directory")
    source, pdf_path, entry = _source_pdf(Path(connector_receipt), connector_receipt_sha256)
    output_bytes, pages, decoded_content_bytes, audit = _extract_pdf(
        pdf_path,
        max_pages=max_pages,
        max_decoded_content_bytes=max_decoded_content_bytes,
        max_output_bytes=max_output_bytes,
    )
    pypdf = _load_pypdf()
    extractor = {
        "normalization": NORMALIZATION,
        "extractor_semantics_version": EXTRACTOR_SEMANTICS_VERSION,
        "reader_strict": False,
        "producer_sha256": _producer_sha256(),
        "pypdf_version": PYPDF_VERSION,
        "pypdf_package_tree_sha256": _package_tree_sha256(pypdf),
        "pypdf_wheel_sha256": PYPDF_WHEEL_SHA256,
        "python_major_minor": PYTHON_MAJOR_MINOR,
        "python_version": sys.version,
        "max_pages": max_pages,
        "max_decoded_content_bytes": max_decoded_content_bytes,
        "max_output_bytes": max_output_bytes,
        "zero_fallback": True,
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "result": "VERIFIED",
        "claim_boundary": "deterministic PDF-to-UTF-8 transform only; no admission, acquisition, training, result, capability, or issue-closure credit",
        "source": {
            "connector_receipt_sha256": connector_receipt_sha256,
            "connector": source.get("connector"),
            "source_id": source.get("source_id"),
            "canonical_url": source.get("canonical_url"),
            "revision": source.get("revision"),
            "license": source.get("license"),
            "pdf_path": entry["path"].replace("\\", "/"),
            "pdf_bytes": entry["bytes"],
            "pdf_sha256": entry["sha256"],
        },
        "extractor": extractor,
        "output": {
            "path": OUTPUT_NAME,
            "bytes": len(output_bytes),
            "sha256": _sha256(output_bytes),
            "pages": pages,
            "decoded_content_bytes": decoded_content_bytes,
            **audit,
        },
    }
    receipt["receipt_sha256"] = _sha256(_canonical_json(receipt))
    output_dir.mkdir(exist_ok=False)
    try:
        text_tmp = output_dir / f".{OUTPUT_NAME}.tmp"
        receipt_tmp = output_dir / f".{RECEIPT_NAME}.tmp"
        text_tmp.write_bytes(output_bytes)
        os.replace(text_tmp, output_dir / OUTPUT_NAME)
        receipt_bytes = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        receipt_tmp.write_bytes(receipt_bytes)
        os.replace(receipt_tmp, output_dir / RECEIPT_NAME)
    except BaseException:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
    return verify_pdf_text_receipt(
        receipt_path=output_dir / RECEIPT_NAME,
        connector_receipt=Path(connector_receipt),
        connector_receipt_sha256=connector_receipt_sha256,
    )


def verify_pdf_text_receipt(
    *,
    receipt_path: Path,
    connector_receipt: Path,
    connector_receipt_sha256: str,
) -> dict[str, Any]:
    _, receipt = _read_json(Path(receipt_path), "PDF extraction receipt")
    _validate_receipt_shape(receipt)
    output_dir = Path(receipt_path).parent
    if _is_reparse_or_symlink(output_dir) or not output_dir.is_dir():
        raise PdfExtractionRefusal("PDF extraction output directory is not regular")
    actual_names = {item.name for item in output_dir.iterdir()}
    if actual_names != {OUTPUT_NAME, RECEIPT_NAME}:
        raise PdfExtractionRefusal("PDF extraction output custody contains missing or extra paths")
    source, pdf_path, entry = _source_pdf(Path(connector_receipt), connector_receipt_sha256)
    source_claim = receipt.get("source")
    expected_source = {
        "connector_receipt_sha256": connector_receipt_sha256,
        "connector": source.get("connector"),
        "source_id": source.get("source_id"),
        "canonical_url": source.get("canonical_url"),
        "revision": source.get("revision"),
        "license": source.get("license"),
        "pdf_path": entry["path"].replace("\\", "/"),
        "pdf_bytes": entry["bytes"],
        "pdf_sha256": entry["sha256"],
    }
    if source_claim != expected_source:
        raise PdfExtractionRefusal("PDF extraction source identity does not match custody")
    extractor = receipt.get("extractor")
    if not isinstance(extractor, dict) or set(extractor) != {
        "normalization",
        "extractor_semantics_version",
        "reader_strict",
        "producer_sha256",
        "pypdf_version",
        "pypdf_package_tree_sha256",
        "pypdf_wheel_sha256",
        "python_major_minor",
        "python_version",
        "max_pages",
        "max_decoded_content_bytes",
        "max_output_bytes",
        "zero_fallback",
    }:
        raise PdfExtractionRefusal("PDF extraction extractor identity is not closed")
    pypdf = _load_pypdf()
    expected_extractor = dict(extractor)
    if (
        extractor.get("normalization") != NORMALIZATION
        or extractor.get("extractor_semantics_version") != EXTRACTOR_SEMANTICS_VERSION
        or extractor.get("reader_strict") is not False
        or extractor.get("producer_sha256") != _producer_sha256()
        or extractor.get("pypdf_version") != PYPDF_VERSION
        or extractor.get("pypdf_package_tree_sha256") != _package_tree_sha256(pypdf)
        or extractor.get("pypdf_wheel_sha256") != PYPDF_WHEEL_SHA256
        or extractor.get("python_major_minor") != PYTHON_MAJOR_MINOR
        or extractor.get("python_version") != sys.version
        or extractor.get("zero_fallback") is not True
    ):
        raise PdfExtractionRefusal("PDF extraction extractor identity changed")
    output_bytes, pages, decoded_content_bytes, audit = _extract_pdf(
        pdf_path,
        max_pages=expected_extractor["max_pages"],
        max_decoded_content_bytes=expected_extractor["max_decoded_content_bytes"],
        max_output_bytes=expected_extractor["max_output_bytes"],
    )
    stored_output = _regular_file(output_dir / OUTPUT_NAME, "PDF extraction output").read_bytes()
    output_claim = receipt.get("output")
    expected_output = {
        "path": OUTPUT_NAME,
        "bytes": len(output_bytes),
        "sha256": _sha256(output_bytes),
        "pages": pages,
        "decoded_content_bytes": decoded_content_bytes,
        **audit,
    }
    if output_claim != expected_output or stored_output != output_bytes:
        raise PdfExtractionRefusal("PDF extraction output does not match independent re-extraction")
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connector-receipt", type=Path, required=True)
    parser.add_argument("--connector-receipt-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--max-decoded-content-bytes", type=int, default=DEFAULT_MAX_DECODED_CONTENT_BYTES)
    parser.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    parser.add_argument("--verify", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify:
        receipt = verify_pdf_text_receipt(
            receipt_path=args.output_dir / RECEIPT_NAME,
            connector_receipt=args.connector_receipt,
            connector_receipt_sha256=args.connector_receipt_sha256,
        )
    else:
        receipt = produce_pdf_text_receipt(
            connector_receipt=args.connector_receipt,
            connector_receipt_sha256=args.connector_receipt_sha256,
            output_dir=args.output_dir,
            max_pages=args.max_pages,
            max_decoded_content_bytes=args.max_decoded_content_bytes,
            max_output_bytes=args.max_output_bytes,
        )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
