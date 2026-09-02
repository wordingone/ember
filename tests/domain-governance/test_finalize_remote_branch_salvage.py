# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT / "tests"))

from test_remote_branch_salvage import capture  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/remote_branch_salvage.py
import importlib.util as _ember_538fc81bfbcace5e_importlib
import sys as _ember_538fc81bfbcace5e_sys
from pathlib import Path as _ember_538fc81bfbcace5e_Path
_ember_538fc81bfbcace5e_path = _ember_538fc81bfbcace5e_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'remote_branch_salvage.py')
if not _ember_538fc81bfbcace5e_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/remote_branch_salvage.py')
_ember_538fc81bfbcace5e_aliases = ('_ember_issue2015_538fc81bfbcace5e', 'remote_branch_salvage', 'scripts.remote_branch_salvage', 'src.ember.governance.scripts.remote_branch_salvage')
_ember_538fc81bfbcace5e_existing = []
for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
    _ember_538fc81bfbcace5e_candidate = _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias)
    if _ember_538fc81bfbcace5e_candidate is not None and all(_ember_538fc81bfbcace5e_candidate is not item for item in _ember_538fc81bfbcace5e_existing):
        _ember_538fc81bfbcace5e_existing.append(_ember_538fc81bfbcace5e_candidate)
if len(_ember_538fc81bfbcace5e_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
if _ember_538fc81bfbcace5e_existing:
    _ember_538fc81bfbcace5e_module = _ember_538fc81bfbcace5e_existing[0]
    _ember_538fc81bfbcace5e_observed = getattr(_ember_538fc81bfbcace5e_module, '__file__', None)
    if _ember_538fc81bfbcace5e_observed is None or _ember_538fc81bfbcace5e_Path(_ember_538fc81bfbcace5e_observed).resolve() != _ember_538fc81bfbcace5e_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/remote_branch_salvage.py')
else:
    _ember_538fc81bfbcace5e_spec = _ember_538fc81bfbcace5e_importlib.spec_from_file_location('_ember_issue2015_538fc81bfbcace5e', _ember_538fc81bfbcace5e_path)
    if _ember_538fc81bfbcace5e_spec is None or _ember_538fc81bfbcace5e_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/remote_branch_salvage.py')
    _ember_538fc81bfbcace5e_module = _ember_538fc81bfbcace5e_importlib.module_from_spec(_ember_538fc81bfbcace5e_spec)
    for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
        _ember_538fc81bfbcace5e_prior = _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias)
        if _ember_538fc81bfbcace5e_prior is not None and _ember_538fc81bfbcace5e_prior is not _ember_538fc81bfbcace5e_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
        _ember_538fc81bfbcace5e_sys.modules[_ember_538fc81bfbcace5e_alias] = _ember_538fc81bfbcace5e_module
    try:
        _ember_538fc81bfbcace5e_spec.loader.exec_module(_ember_538fc81bfbcace5e_module)
    except BaseException:
        for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
            if _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias) is _ember_538fc81bfbcace5e_module:
                _ember_538fc81bfbcace5e_sys.modules.pop(_ember_538fc81bfbcace5e_alias, None)
        raise
for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
    _ember_538fc81bfbcace5e_prior = _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias)
    if _ember_538fc81bfbcace5e_prior is not None and _ember_538fc81bfbcace5e_prior is not _ember_538fc81bfbcace5e_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
    _ember_538fc81bfbcace5e_sys.modules[_ember_538fc81bfbcace5e_alias] = _ember_538fc81bfbcace5e_module
build_packet = getattr(_ember_538fc81bfbcace5e_module, 'build_packet')
build_public_summary = getattr(_ember_538fc81bfbcace5e_module, 'build_public_summary')
# issue2015 exact-local-import-end:src/ember/governance/scripts/remote_branch_salvage.py  # noqa: E402


FINALIZER = ROOT / "scripts" / "finalize_remote_branch_salvage.py"
WORKFLOW = ROOT / ".github" / "workflows" / "remote-branch-salvage-capture.yml"


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def publication_context(*, mutated_refs: list[str] | None = None) -> dict:
    return {
        "schema_version": "ember-remote-branch-publication-context-v1",
        "repository": "wordingone/ember",
        "mode": "GITHUB_ACTIONS_WORKFLOW_ARTIFACT",
        "workflow_ref": "refs/heads/master",
        "workflow_sha": "a" * 40,
        "run_id": "123456789",
        "run_attempt": 1,
        "excluded_refs": [],
        "ref_mutations_performed": mutated_refs or [],
    }


def run_finalizer(tmp_path: Path, context: dict) -> subprocess.CompletedProcess[str]:
    packet = build_packet(capture())
    summary = build_public_summary(packet)
    packet_path = tmp_path / "packet.json"
    summary_path = tmp_path / "summary.json"
    context_path = tmp_path / "publication.json"
    output_path = tmp_path / "receipt.json"
    write_json(packet_path, packet)
    write_json(summary_path, summary)
    write_json(context_path, context)
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(FINALIZER),
            "--packet",
            str(packet_path),
            "--summary",
            str(summary_path),
            "--publication-context",
            str(context_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_finalizer_accepts_master_workflow_artifact_without_ref_mutation(
    tmp_path: Path,
) -> None:
    result = run_finalizer(tmp_path, publication_context())

    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "CANDIDATE_NON_AUTHORIZING_CAPTURE"
    assert receipt["master_sha"] == "a" * 40
    assert receipt["branch_count"] == 2
    assert receipt["excluded_refs"] == []
    assert receipt["ref_mutations_performed"] == []
    assert receipt["deletion_authority"] == "NOT_GRANTED"
    assert receipt["public_mutation_performed"] is False


def test_finalizer_rejects_publication_that_mutates_a_captured_ref(
    tmp_path: Path,
) -> None:
    result = run_finalizer(
        tmp_path,
        publication_context(mutated_refs=["refs/heads/feat/contained"]),
    )

    assert result.returncode == 2
    assert "publication mutated a ref inside the captured population" in result.stdout
    assert not (tmp_path / "receipt.json").exists()


def test_finalizer_rejects_undeclared_population_exclusions(tmp_path: Path) -> None:
    context = publication_context()
    context["excluded_refs"] = ["refs/heads/feat/contained"]

    result = run_finalizer(tmp_path, context)

    assert result.returncode == 2
    assert "certification capture cannot exclude live refs" in result.stdout


def test_finalizer_rejects_ref_drift_inside_the_capture_window(tmp_path: Path) -> None:
    drifted = capture()
    drifted["branches"][1]["ref_stability"]["preexecution_sha"] = "f" * 40
    packet = build_packet(drifted)
    summary = build_public_summary(packet)
    packet_path = tmp_path / "packet.json"
    summary_path = tmp_path / "summary.json"
    context_path = tmp_path / "publication.json"
    output_path = tmp_path / "receipt.json"
    write_json(packet_path, packet)
    write_json(summary_path, summary)
    write_json(context_path, publication_context())

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(FINALIZER),
            "--packet",
            str(packet_path),
            "--summary",
            str(summary_path),
            "--publication-context",
            str(context_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "capture window contains ref drift" in result.stdout


def test_post_merge_capture_workflow_is_manual_read_only_and_artifact_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "\npush:" not in text
    assert "contents: read" in text
    assert "actions/upload-artifact@v4" in text
    assert "git push" not in text
    assert "gh pr comment" not in text
    assert "finalize_remote_branch_salvage.py" in text
    assert "baseline_run_id:" in text
    assert "gh run download" in text
    assert "compare_remote_branch_salvage_captures.py" in text
    assert "BASELINE_RUN_ID: ${{ inputs.baseline_run_id }}" in text
    assert 'baseline_run_id="${BASELINE_RUN_ID}"' in text
    assert "baseline_run_id='${{ inputs.baseline_run_id }}'" not in text
    assert 'actions/runs/${baseline_run_id}' in text
    assert '.conclusion == "success"' in text
    assert '.event == "workflow_dispatch"' in text
    assert '.head_sha == $sha' in text
    assert '.path == $workflow_path' in text
    assert '--expected-first-run-id "${baseline_run_id}"' in text
    assert '--expected-second-run-id "${GITHUB_RUN_ID}"' in text
