# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ember-restart-3b" / "mint_github_license_partition.py"
K_REFUSAL_SCRIPT = ROOT / "tools" / "ember-restart-3b" / "mint_github_partition_refusal.py"
EVIDENCE = "GitHub Search API per-repo `license.spdx_id` (LICENSE-file detection), filtered to allow-set"
ALLOW = ["Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0", "MIT", "ODC-By-1.0", "PDDL-1.0"]


def _load():
    spec = importlib.util.spec_from_file_location("mint_github_license_partition", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_k_refusal():
    spec = importlib.util.spec_from_file_location("mint_github_partition_refusal", K_REFUSAL_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _archive(path: Path, *, root: str, revision: str | None, payload: bytes, link: bool = False) -> None:
    kwargs = {"format": tarfile.PAX_FORMAT}
    if revision is not None:
        kwargs["pax_headers"] = {"comment": revision}
    with tarfile.open(path, "w:gz", **kwargs) as archive:
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        member = tarfile.TarInfo(f"{root}/src/main.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
        license_member = tarfile.TarInfo(f"{root}/LICENSE")
        license_raw = b"fixture license text\n"
        license_member.size = len(license_raw)
        archive.addfile(license_member, io.BytesIO(license_raw))
        if link:
            linked = tarfile.TarInfo(f"{root}/latest.txt")
            linked.type = tarfile.SYMTYPE
            linked.linkname = "src/main.txt"
            archive.addfile(linked)


def _connector(tmp_path: Path, *, absent_pax: bool = False, second_license: str = "MIT") -> tuple[Path, str]:
    custody = tmp_path / "custody"
    custody.mkdir()
    rows = [
        ("alpha/repo", "Apache-2.0", "a" * 40, b"alpha bytes\n", True),
        ("beta/repo", second_license, None if absent_pax else "b" * 40, b"beta bytes\n", False),
    ]
    selected = []
    files = []
    for full_name, license_spdx, revision, payload, link in rows:
        filename = full_name.replace("/", "-") + ".tar.gz"
        path = custody / filename
        _archive(path, root=full_name.split("/")[1] + "-main", revision=revision, payload=payload, link=link)
        raw = path.read_bytes()
        files.append({"path": filename, "bytes": len(raw), "sha256": _sha(raw)})
        selected.append(
            {
                "declared_size_bytes": len(payload),
                "full_name": full_name,
                "license": license_spdx,
                "stars": 10 if full_name.startswith("alpha") else 9,
                "url": f"https://github.com/{full_name}",
            }
        )
    receipt = {
        "canonical_url": "https://github.com/search?q=topic%3Atesting&s=stars&o=desc",
        "connector": {"name": "github_fetch", "version": "v1"},
        "dest_root": str(custody),
        "fetched_at": "2026-08-15T00:00:00Z",
        "files": files,
        "l3_statement": "fetch-only; no external model authored/filtered/ranked/scored/selected any token",
        "license": "mixed (see notes)",
        "license_evidence": EVIDENCE,
        "notes": json.dumps(
            {
                "allowed_licenses": ALLOW,
                "budget_bytes": 1000,
                "candidates_considered": 2,
                "excluded_for_license": 0,
                "selected": selected,
            },
            sort_keys=True,
        ),
        "revision": None,
        "schema": "corpus-connector-receipt-v1",
        "sha256_manifest": _sha("\n".join(sorted(row["sha256"] for row in files)).encode()),
        "source": "github",
        "source_id": "topic:testing",
        "total_bytes": sum(row["bytes"] for row in files),
    }
    path = custody / "_manifests" / "receipt.json"
    path.parent.mkdir()
    raw = _canonical(receipt)
    path.write_bytes(raw)
    return path, _sha(raw)


def _mint(module, receipt_path: Path, receipt_sha: str, output: Path):
    return module.mint_partition(
        connector_receipt_path=receipt_path,
        connector_receipt_sha256=receipt_sha,
        output=output,
        source_commit="1" * 40,
        source_id="candidate-software_engineering-train-1",
        connector_slot="H-train-2",
        split="train",
        domain="software_engineering",
        expected_topic="testing",
    )


def test_mixed_repositories_mint_exact_partition_and_record_link_exclusion(tmp_path: Path):
    module = _load()
    receipt_path, receipt_sha = _connector(tmp_path)
    output = tmp_path / "partition"

    receipt = _mint(module, receipt_path, receipt_sha, output)

    assert receipt["schema_version"] == "ember-github-license-partition-receipt-v1"
    assert [row["source_repo"] for row in receipt["repositories"]] == ["alpha/repo", "beta/repo"]
    assert [row["declared_spdx"] for row in receipt["repositories"]] == ["Apache-2.0", "MIT"]
    assert receipt["license_summary"] == ["Apache-2.0", "MIT"]
    assert "license_spdx" not in receipt
    assert [item for item in receipt["repositories"][0]["excluded_members"] if item["type"] == "symlink"] == [
        {"link_target": "src/main.txt", "path": "latest.txt", "type": "symlink"}
    ]
    for repository in receipt["repositories"]:
        assert repository["source_revision"] in {"a" * 40, "b" * 40}
        for item in repository["files"]:
            assert item["source_repo"] == repository["source_repo"]
            assert item["source_revision"] == repository["source_revision"]
            assert item["archive_sha256"] == repository["archive_sha256"]
            assert item["declared_spdx"] == repository["declared_spdx"]
            blob = output / item["blob_path"]
            assert blob.read_bytes()
            assert _sha(blob.read_bytes()) == item["sha256"]
    assert module.validate_partition_receipt(output / "partition-receipt.json") == receipt


def test_connector_operational_logs_are_not_payload(tmp_path: Path):
    module = _load()
    (tmp_path / "payload.tar.gz").write_bytes(b"payload")
    (tmp_path / "_logs").mkdir()
    (tmp_path / "_logs" / "connector.log").write_bytes(b"operational")
    assert module._listed_payload_paths(tmp_path) == {"payload.tar.gz"}


@pytest.mark.parametrize("mutation", ["archive", "receipt", "swap"])
def test_tamper_and_partition_swap_refuse(tmp_path: Path, mutation: str):
    module = _load()
    receipt_path, receipt_sha = _connector(tmp_path)
    output = tmp_path / "partition"
    receipt = _mint(module, receipt_path, receipt_sha, output)
    if mutation == "archive":
        (receipt_path.parent.parent / "alpha-repo.tar.gz").write_bytes(b"changed")
        with pytest.raises(ValueError, match="archive bytes"):
            _mint(module, receipt_path, receipt_sha, tmp_path / "second")
    elif mutation == "receipt":
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
        with pytest.raises(ValueError, match="receipt bytes"):
            _mint(module, receipt_path, receipt_sha, tmp_path / "second")
    else:
        path = output / "partition-receipt.json"
        stored = json.loads(path.read_bytes())
        stored["repositories"][0]["declared_spdx"], stored["repositories"][1]["declared_spdx"] = (
            stored["repositories"][1]["declared_spdx"],
            stored["repositories"][0]["declared_spdx"],
        )
        path.write_bytes(_canonical(stored))
        with pytest.raises(ValueError, match="partition receipt"):
            module.validate_partition_receipt(path)


def test_unlicensed_repository_refuses(tmp_path: Path):
    module = _load()
    receipt_path, receipt_sha = _connector(tmp_path, second_license="NOASSERTION")
    with pytest.raises(ValueError, match="per-repository SPDX"):
        _mint(module, receipt_path, receipt_sha, tmp_path / "partition")


def test_absent_pax_revision_has_dedicated_refusal(tmp_path: Path):
    module = _load()
    receipt_path, receipt_sha = _connector(tmp_path, absent_pax=True)
    with pytest.raises(ValueError, match="archive revision is absent"):
        _mint(module, receipt_path, receipt_sha, tmp_path / "partition")


def test_empty_k_routes_mint_closed_refusal_and_reject_race_or_tamper(tmp_path: Path):
    module = _load_k_refusal()
    k1 = tmp_path / "K-train-1"
    k2 = tmp_path / "K-train-2"
    k1.mkdir()
    k2.mkdir()
    output = tmp_path / "K-route-refusal.json"

    receipt = module.mint_refusal(
        custody_roots=[k1, k2], output=output, source_commit="2" * 40
    )

    assert receipt["schema_version"] == "ember-github-license-partition-refusal-v1"
    assert receipt["result"] == "REFUSED"
    assert receipt["reason"] == "CONNECTOR_RECEIPT_AND_PAYLOAD_ABSENT"
    assert [row["connector_slot"] for row in receipt["routes"]] == ["K-train-1", "K-train-2"]
    assert all(row["child_count"] == 0 for row in receipt["routes"])
    assert all(row["connector_receipt_present"] is False for row in receipt["routes"])
    assert module.validate_refusal(output) == receipt

    raced = k1 / "late-payload.tar.gz"
    raced.write_bytes(b"raced")
    with pytest.raises(ValueError, match="K custody is not empty"):
        module.validate_refusal(output)
    raced.unlink()

    stored = json.loads(output.read_bytes())
    stored["routes"][0]["custody_path"] = str(k2)
    output.write_bytes(_canonical(stored) + b"\n")
    with pytest.raises(ValueError, match="K custody identity"):
        module.validate_refusal(output)
