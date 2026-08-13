# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Foreign-repository RED-first tests for R1 WARM-100 entry source-identity binding.

Issue #1296's P1 defect: ``contract.py r1-entry`` mints a green
``ember-r1-warm100-entry-v1`` receipt for ANY git repository whose HEAD matches
the claimed ``source_commit`` and whose tree is clean -- including a completely
foreign, attacker-authored repository. This suite proves that with real git
repositories only (precedent: ``scripts/ember_totality/tree_provenance_test.py``)
-- no mocked git, no monkeypatched identity checks, no renamed ``origin``.

Keeps ``test_contract.py``'s live-repo suite intact; this file owns the
synthetic multi-repository fixtures instead.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ember_restart.contract import R1_ENTRY_PINNED_FILES, R1_ENTRY_SOURCE_FILES

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "ember_restart" / "contract.py"
WORKTREE_LIFECYCLE = REPO_ROOT / "scripts" / "worktree_lifecycle.py"


def _load_test_contract_helpers():
    """File-path load of test_contract.py's manifest scaffolding helpers.

    A dotted ``tests.ember_restart.test_contract`` import is not reliable
    here: an unrelated installed package can occupy the top-level ``tests``
    name and shadow this repository's ``tests/`` directory before Python's
    namespace-package merge ever runs. File-path loading (precedent:
    certified_train_launch.py:464-478's load_closure_module) sidesteps
    dotted-name resolution entirely.
    """
    module_path = Path(__file__).resolve().parent / "test_contract.py"
    spec = importlib.util.spec_from_file_location(
        "_r1_source_binding_test_contract_helpers", module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_test_contract = _load_test_contract_helpers()
_candidate_manifest = _test_contract._candidate_manifest
_write_json = _test_contract._write_json

GOVERNED_RELATIVE_PATHS = sorted(set(R1_ENTRY_SOURCE_FILES.values()) | set(R1_ENTRY_PINNED_FILES.values()))


def _git(root: Path, *args: str) -> str:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "issue1296-test",
            "GIT_AUTHOR_EMAIL": "issue1296@example.invalid",
            "GIT_COMMITTER_NAME": "issue1296-test",
            "GIT_COMMITTER_EMAIL": "issue1296@example.invalid",
        }
    )
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


def _seed_governed_files(repo: Path, *, variant: str) -> None:
    """Write real (non-placeholder) bytes at all 7 governed paths, plus markers."""
    for relative in GOVERNED_RELATIVE_PATHS:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{variant} bytes at {relative}\n", encoding="utf-8")
    (repo / "GOAL.md").write_text(f"{variant} goal marker\n", encoding="utf-8")
    ember_cli_dir = repo / "tools" / "ember-cli"
    ember_cli_dir.mkdir(parents=True, exist_ok=True)
    (ember_cli_dir / "README.md").write_text("marker\n", encoding="utf-8")


def _source_paths(root: Path) -> dict[str, Path]:
    return {
        "prereg_path": root / R1_ENTRY_PINNED_FILES["prereg_sha256"],
        "config_path": root / R1_ENTRY_PINNED_FILES["config_sha256"],
        "fixed_prior_path": root / R1_ENTRY_PINNED_FILES["fixed_prior_manifest_sha256"],
    }


def _manifest_at(tmp_path: Path, source_commit: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = source_commit
    _write_json(manifest_path, manifest)
    return manifest_path


@pytest.fixture
def governed_remote(tmp_path: Path) -> Path:
    """A bare remote carrying one real, governed-shaped commit on master."""
    remote = tmp_path / "governed.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "master", str(seed)], check=True, capture_output=True)
    _seed_governed_files(seed, variant="governed")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "governed seed")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "master")
    return remote


@pytest.fixture
def canonical(tmp_path: Path, governed_remote: Path) -> Path:
    """The synthetic canonical checkout: a real clone of governed_remote."""
    root = tmp_path / "canonical"
    subprocess.run(["git", "clone", str(governed_remote), str(root)], check=True, capture_output=True)
    return root


@pytest.fixture
def foreign(tmp_path: Path) -> Path:
    """A genuinely unrelated repository: independent history, different bytes."""
    root = tmp_path / "foreign"
    subprocess.run(["git", "init", "-b", "master", str(root)], check=True, capture_output=True)
    _seed_governed_files(root, variant="foreign-attacker")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "foreign seed")
    return root


@pytest.fixture
def managed_worktree(tmp_path: Path, canonical: Path) -> Path:
    """A worktree of ``canonical`` registered by the real lifecycle tool."""
    env = dict(os.environ)
    env["EMBER_WORKTREE_ROOT"] = str(tmp_path / "wt-root")
    result = subprocess.run(
        [
            sys.executable,
            str(WORKTREE_LIFECYCLE),
            "--repo",
            str(canonical),
            "create",
            "--path",
            "r1-binding-managed",
            "--branch",
            "issue1296-managed-test",
            "--owner",
            "issue1296-test",
            "--purpose",
            "r1-binding-test",
            "--expires",
            "2099-01-01",
            "--allow-c-drive",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    return Path(payload["path"])


def test_foreign_repo_is_refused(tmp_path: Path, foreign: Path):
    """Variant 1 (the RED test): a genuinely unrelated repository is refused.

    On master today this mints a green receipt binding attacker-authored
    bytes -- the P1 defect made concrete. Post-fix it must raise ValueError
    on the canonical-object-store binding, before any network/ancestry work.
    """
    from scripts.ember_restart.contract import build_r1_warm100_entry

    foreign_head = _git(foreign, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, foreign_head)

    with pytest.raises(ValueError, match="object store"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=foreign_head,
            source_root=foreign,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            **_source_paths(foreign),
        )


def test_origin_url_spoof_is_refused(tmp_path: Path, foreign: Path):
    """Variant 2: renaming ``origin`` to the canonical URL changes nothing.

    The config cell and the object store are independent (spec B3); the
    binding never reads ``foreign``'s configured ``origin``.
    """
    from scripts.ember_restart.contract import build_r1_warm100_entry

    _git(foreign, "remote", "add", "origin", "https://github.com/wordingone/ember.git")
    foreign_head = _git(foreign, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, foreign_head)

    with pytest.raises(ValueError, match="object store"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=foreign_head,
            source_root=foreign,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            **_source_paths(foreign),
        )


def test_ancestry_severed_clone_is_refused_by_default_anchor(tmp_path: Path, governed_remote: Path):
    """Variant 3a: a real clone of governed_remote, checked against the real
    (default) canonical anchor, fails on object-store identity -- it is its
    own clone, sharing nothing with the anchor's common dir."""
    from scripts.ember_restart.contract import build_r1_warm100_entry

    severed = tmp_path / "severed"
    subprocess.run(["git", "clone", str(governed_remote), str(severed)], check=True, capture_output=True)
    (severed / "local-only.txt").write_text("unpublished\n", encoding="utf-8")
    _git(severed, "add", "-A")
    _git(severed, "commit", "-m", "unpublished local commit")
    severed_head = _git(severed, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, severed_head)

    with pytest.raises(ValueError, match="object store"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=severed_head,
            source_root=severed,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            **_source_paths(severed),
        )


def test_ancestry_severed_clone_is_refused_by_unpublished_ancestry(tmp_path: Path, governed_remote: Path):
    """Variant 3b: isolating the commit leg. ``canonical_root=severed`` makes
    severed its own anchor (object-store identity trivially holds), so the
    refusal must come from B2: the new commit was never pushed to
    governed_remote and is therefore not published ancestry."""
    from scripts.ember_restart.contract import build_r1_warm100_entry

    severed = tmp_path / "severed"
    subprocess.run(["git", "clone", str(governed_remote), str(severed)], check=True, capture_output=True)
    (severed / "local-only.txt").write_text("unpublished\n", encoding="utf-8")
    _git(severed, "add", "-A")
    _git(severed, "commit", "-m", "unpublished local commit")
    severed_head = _git(severed, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, severed_head)

    with pytest.raises(ValueError, match="publish"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=severed_head,
            source_root=severed,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            canonical_root=severed,
            governed_remote=str(governed_remote),
            **_source_paths(severed),
        )


def test_unmanaged_worktree_is_refused(tmp_path: Path, canonical: Path, managed_worktree: Path):
    """Variant 4: an ad-hoc ``git worktree add`` (bypassing the lifecycle
    tool) under the synthetic canonical shares its common dir but is absent
    from the registry -- refused at the managed-worktree-membership leg.

    Depends on the ``managed_worktree`` fixture only to guarantee the
    registry file exists (a real lifecycle ``create`` already ran against
    ``canonical``), isolating "registered but not this worktree" from
    variant 7's "no registry at all".
    """
    from scripts.ember_restart.contract import build_r1_warm100_entry

    ad_hoc = tmp_path / "ad-hoc-worktree"
    _git(canonical, "worktree", "add", "-b", "ad-hoc-branch", str(ad_hoc), "HEAD")
    ad_hoc_head = _git(ad_hoc, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, ad_hoc_head)

    with pytest.raises(ValueError, match="managed-worktree"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=ad_hoc_head,
            source_root=ad_hoc,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            canonical_root=canonical,
            **_source_paths(ad_hoc),
        )


def test_unpublished_commit_from_right_root_is_refused(tmp_path: Path, canonical: Path, governed_remote: Path):
    """Variant 5: right root (the synthetic canonical itself), wrong commit
    -- HEAD equals source_commit, tree clean, root canonical, but the tip
    was never pushed. Fails only the B2 ancestry leg."""
    from scripts.ember_restart.contract import build_r1_warm100_entry

    (canonical / "local-only.txt").write_text("unpublished\n", encoding="utf-8")
    _git(canonical, "add", "-A")
    _git(canonical, "commit", "-m", "unpublished local commit")
    new_head = _git(canonical, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, new_head)

    with pytest.raises(ValueError, match="publish"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=new_head,
            source_root=canonical,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            canonical_root=canonical,
            governed_remote=str(governed_remote),
            **_source_paths(canonical),
        )


def test_receipt_tampering_of_source_binding_is_refused(tmp_path: Path, canonical: Path, governed_remote: Path):
    """Variant 6: flipping ancestry, swapping remote_master_sha, or dropping
    the source_binding block must all be refused on reopen (closed-key set
    or self-hash), extending the mutation loop of test_contract.py:582-594."""
    from scripts.ember_restart.contract import build_r1_warm100_entry, validate_r1_warm100_entry

    head = _git(canonical, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, head)
    payload = build_r1_warm100_entry(
        manifest_path,
        source_commit=head,
        source_root=canonical,
        trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
        canonical_root=canonical,
        governed_remote=str(governed_remote),
        **_source_paths(canonical),
    )
    assert payload["source_binding"]["worktree_identity"] == "MAIN"

    for mutate in (
        lambda candidate: candidate["source_binding"].update({"ancestry": "ANCESTOR" if candidate["source_binding"]["ancestry"] == "EQUAL" else "EQUAL"}),
        lambda candidate: candidate["source_binding"].update({"remote_master_sha": "0" * 40}),
        lambda candidate: candidate["source_binding"].update({"worktree_identity": "MANAGED"}),
        lambda candidate: candidate.pop("source_binding"),
    ):
        tampered = json.loads(json.dumps(payload))
        mutate(tampered)
        try:
            validate_r1_warm100_entry(
                tampered,
                source_root=canonical,
                manifest_path=manifest_path,
                canonical_root=canonical,
                governed_remote=str(governed_remote),
            )
        except ValueError:
            continue
        raise AssertionError("tampered source_binding was accepted")


def test_missing_registry_refuses(tmp_path: Path, canonical: Path, managed_worktree: Path):
    """Variant 7: the synthetic registry state file is deleted; minting from
    the (now orphaned) managed worktree fails closed -- a missing authority
    is a refusal, never an implicit pass."""
    from scripts.ember_restart.contract import build_r1_warm100_entry

    state_file = canonical / ".git" / "ember-worktree-lifecycle.json"
    assert state_file.exists()
    state_file.unlink()

    head = _git(managed_worktree, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, head)

    with pytest.raises(ValueError, match="registry"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=head,
            source_root=managed_worktree,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            canonical_root=canonical,
            **_source_paths(managed_worktree),
        )


def test_positive_control_main_and_managed_worktree_mint_green(
    tmp_path: Path, canonical: Path, managed_worktree: Path, governed_remote: Path
):
    """Variant 8: the synthetic canonical MAIN checkout and its
    lifecycle-managed worktree both mint a green, round-trippable receipt at
    published master."""
    from scripts.ember_restart.contract import build_r1_warm100_entry, validate_r1_warm100_entry

    main_head = _git(canonical, "rev-parse", "HEAD")
    main_manifest = _manifest_at(tmp_path / "main-manifest", main_head)
    main_payload = build_r1_warm100_entry(
        main_manifest,
        source_commit=main_head,
        source_root=canonical,
        trusted_verifier_registry=main_manifest.parent / "trusted-verifiers.json",
        canonical_root=canonical,
        governed_remote=str(governed_remote),
        **_source_paths(canonical),
    )
    assert main_payload["source_binding"] == {
        "canonical_common_dir_bound": True,
        "worktree_identity": "MAIN",
        "governed_remote": str(governed_remote),
        "remote_master_sha": main_head,
        "ancestry": "EQUAL",
    }
    assert validate_r1_warm100_entry(
        main_payload,
        source_root=canonical,
        manifest_path=main_manifest,
        canonical_root=canonical,
        governed_remote=str(governed_remote),
    )

    managed_head = _git(managed_worktree, "rev-parse", "HEAD")
    managed_manifest = _manifest_at(tmp_path / "managed-manifest", managed_head)
    managed_payload = build_r1_warm100_entry(
        managed_manifest,
        source_commit=managed_head,
        source_root=managed_worktree,
        trusted_verifier_registry=managed_manifest.parent / "trusted-verifiers.json",
        canonical_root=canonical,
        governed_remote=str(governed_remote),
        **_source_paths(managed_worktree),
    )
    assert managed_payload["source_binding"] == {
        "canonical_common_dir_bound": True,
        "worktree_identity": "MANAGED",
        "governed_remote": str(governed_remote),
        "remote_master_sha": managed_head,
        "ancestry": "EQUAL",
    }
    assert validate_r1_warm100_entry(
        managed_payload,
        source_root=managed_worktree,
        manifest_path=managed_manifest,
        canonical_root=canonical,
        governed_remote=str(governed_remote),
    )


def test_self_invocation_from_ad_hoc_worktree_is_refused(
    tmp_path: Path, canonical: Path, managed_worktree: Path
):
    """Variant 9 (Q1 finding, 2026-08-12 review): the exact geometry the
    CLI's production shape produces when an operator stands inside an
    ad-hoc `git worktree add` and runs ITS OWN copy of the validator --
    canonical_root self-anchors to wherever the executing bytes live (the
    CLI never exposes --canonical-root), which is the ad-hoc worktree
    itself, so canonical_root == source_root trivially. The prior MAIN
    check compared source_toplevel to canonical_toplevel and returned MAIN
    on that equality alone, skipping the registry entirely -- exactly the
    "ad-hoc worktree refused" guarantee this module claims to enforce.
    Depends on managed_worktree only to guarantee canonical's registry file
    exists (precedent: test_unmanaged_worktree_is_refused).
    """
    from scripts.ember_restart.contract import build_r1_warm100_entry

    ad_hoc = tmp_path / "ad-hoc-self-invoke"
    _git(canonical, "worktree", "add", "-b", "ad-hoc-self-invoke-branch", str(ad_hoc), "HEAD")
    ad_hoc_head = _git(ad_hoc, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, ad_hoc_head)

    with pytest.raises(ValueError, match="managed-worktree"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=ad_hoc_head,
            source_root=ad_hoc,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            canonical_root=ad_hoc,
            **_source_paths(ad_hoc),
        )


def test_canonical_on_feature_branch_or_detached_head_binds_correctly(
    tmp_path: Path, canonical: Path, governed_remote: Path
):
    """Variant 11 (review requirement, prompted by a real incident: the
    canonical checkout sat on an unrelated feature branch for several days).
    The canonical checkout's own local branch state must never produce a
    wrong or silently-accepted binding.
    Detached at the published tip mints correctly -- B1's git-shape check
    and B2's remote-contact check are both indifferent to local branch
    state. A named feature branch carrying a genuinely new, unpublished
    commit fails closed on ancestry: spurious refusal is acceptable, silent
    acceptance or binding to the wrong ref is not.
    """
    from scripts.ember_restart.contract import build_r1_warm100_entry

    published_tip = _git(canonical, "rev-parse", "HEAD")
    _git(canonical, "checkout", "--detach", published_tip)
    detached_head = _git(canonical, "rev-parse", "HEAD")
    assert detached_head == published_tip

    manifest_path = _manifest_at(tmp_path / "detached-manifest", detached_head)
    payload = build_r1_warm100_entry(
        manifest_path,
        source_commit=detached_head,
        source_root=canonical,
        trusted_verifier_registry=manifest_path.parent / "trusted-verifiers.json",
        canonical_root=canonical,
        governed_remote=str(governed_remote),
        **_source_paths(canonical),
    )
    assert payload["source_binding"]["worktree_identity"] == "MAIN"
    assert payload["source_binding"]["ancestry"] == "EQUAL"
    assert payload["source_binding"]["remote_master_sha"] == published_tip

    _git(canonical, "checkout", "-b", "feature/six-day-codex-branch")
    (canonical / "local-only.txt").write_text("unpublished feature work\n", encoding="utf-8")
    _git(canonical, "add", "-A")
    _git(canonical, "commit", "-m", "unpublished feature-branch commit")
    feature_head = _git(canonical, "rev-parse", "HEAD")
    assert feature_head != published_tip
    manifest_path_2 = _manifest_at(tmp_path / "feature-manifest", feature_head)

    with pytest.raises(ValueError, match="publish"):
        build_r1_warm100_entry(
            manifest_path_2,
            source_commit=feature_head,
            source_root=canonical,
            trusted_verifier_registry=manifest_path_2.parent / "trusted-verifiers.json",
            canonical_root=canonical,
            governed_remote=str(governed_remote),
            **_source_paths(canonical),
        )


def test_foreign_repo_cli_refusal_is_content_addressed(tmp_path: Path, foreign: Path):
    """CLI twin (production shape, no injection): the CLI's self-anchor is
    whatever checkout is actually executing contract.py, so a foreign
    --source-root is refused with no test-only override needed."""
    foreign_head = _git(foreign, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, foreign_head)
    paths = _source_paths(foreign)

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "r1-entry",
            str(manifest_path),
            "--source-commit",
            foreign_head,
            "--source-root",
            str(foreign),
            "--prereg",
            str(paths["prereg_path"]),
            "--config",
            str(paths["config_path"]),
            "--fixed-prior",
            str(paths["fixed_prior_path"]),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "ember-r1-warm100-entry-refusal-v1"
    assert payload["result"] == "REFUSED"
    assert "object store" in payload["errors"][0]


def _advance_governed_master(tmp_path: Path, governed_remote: Path) -> str:
    """Push one further real commit to governed_remote and return its sha.

    Used to put ``require_published_ancestry`` on the genuine "commit object
    missing locally, a fetch would be needed" leg -- the only leg that ever
    writes into ``source_root``.
    """
    seed = tmp_path / "advance-seed"
    subprocess.run(["git", "clone", str(governed_remote), str(seed)], check=True, capture_output=True)
    (seed / "advance.txt").write_text("advance marker\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "advance governed master")
    _git(seed, "push", "origin", "master")
    return _git(seed, "rev-parse", "HEAD")


def _common_dir_of(root: Path) -> Path:
    raw = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(raw).resolve(strict=True)


def test_census_window_marker_refuses_before_fetch_is_attempted(tmp_path: Path, canonical: Path, governed_remote: Path):
    """Issue #1708: a real ``census-window.lock`` marker at canonical's real
    Git common directory must refuse ``require_published_ancestry`` BEFORE
    the write it is gating, not merely produce some error afterward.

    The ordering proof is a real git-object-store assertion, not a spy or a
    mock: canonical_head's remote master has genuinely advanced past what
    canonical has locally (real ``git push`` from a fresh clone, above), so
    if the fetch this function guards ever actually ran, the new commit
    object would now be present in canonical's own store. It still isn't --
    proof the fetch was never issued, not just that an error came back.
    """
    from scripts.ember_restart import source_authority

    new_master = _advance_governed_master(tmp_path, governed_remote)
    canonical_head = _git(canonical, "rev-parse", "HEAD")
    assert canonical_head != new_master
    missing_before = subprocess.run(
        ["git", "-C", str(canonical), "cat-file", "-e", f"{new_master}^{{commit}}"],
        capture_output=True,
    )
    assert missing_before.returncode != 0

    marker_path = _common_dir_of(canonical) / source_authority.CENSUS_WINDOW_MARKER_NAME
    marker_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="census window declared"):
        source_authority.require_published_ancestry(
            canonical, canonical_head, new_master, governed_remote=str(governed_remote)
        )

    still_missing = subprocess.run(
        ["git", "-C", str(canonical), "cat-file", "-e", f"{new_master}^{{commit}}"],
        capture_output=True,
    )
    assert still_missing.returncode != 0, "the guarded git fetch ran despite the census-window marker"


def test_census_window_env_var_refuses_before_fetch_is_attempted(
    tmp_path: Path, canonical: Path, governed_remote: Path, monkeypatch: pytest.MonkeyPatch
):
    """Issue #1708: the ``EMBER_CENSUS_WINDOW`` environment variable is the
    other declared-window trigger, exercised the same real way -- no marker
    file this time, proving the two triggers are independent paths into the
    same fail-closed refusal, both stopping the write before it happens."""
    from scripts.ember_restart import source_authority

    new_master = _advance_governed_master(tmp_path, governed_remote)
    canonical_head = _git(canonical, "rev-parse", "HEAD")
    assert canonical_head != new_master

    monkeypatch.setenv(source_authority.CENSUS_WINDOW_ENV, "1")

    with pytest.raises(ValueError, match="census window declared"):
        source_authority.require_published_ancestry(
            canonical, canonical_head, new_master, governed_remote=str(governed_remote)
        )

    still_missing = subprocess.run(
        ["git", "-C", str(canonical), "cat-file", "-e", f"{new_master}^{{commit}}"],
        capture_output=True,
    )
    assert still_missing.returncode != 0, "the guarded git fetch ran despite EMBER_CENSUS_WINDOW"


def test_missing_commit_without_census_window_still_fetches_and_resolves(
    tmp_path: Path, canonical: Path, governed_remote: Path
):
    """Sanity control for the two refusal tests above: with no window
    declared, the exact same "commit missing locally" setup still performs
    the real fetch and resolves ancestry -- proving the refusal above comes
    from the census-window gate, not from an accidental break of the
    underlying mechanism."""
    from scripts.ember_restart import source_authority

    new_master = _advance_governed_master(tmp_path, governed_remote)
    canonical_head = _git(canonical, "rev-parse", "HEAD")

    result = source_authority.require_published_ancestry(
        canonical, canonical_head, new_master, governed_remote=str(governed_remote)
    )
    assert result == "ANCESTOR"

    now_present = subprocess.run(
        ["git", "-C", str(canonical), "cat-file", "-e", f"{new_master}^{{commit}}"],
        capture_output=True,
    )
    assert now_present.returncode == 0, "the real fetch should have written the commit object"


def test_identity_before_network_ordering_locked_by_sentinel_remote(tmp_path: Path, foreign: Path):
    """Issue #1707 (F3): ``bind_source_identity`` runs B1 (root identity)
    before B2 (network ancestry) deliberately -- a foreign repo must be
    refused locally, before any network contact. Six of the twelve prior
    tests in this file (plus the CLI foreign-repo-refusal twin) omit
    ``governed_remote`` entirely and stay hermetic ONLY because root binding
    raises before the network leg ever runs; nothing before this test locked
    that ordering as a property in its own right, so a future change that
    swapped B1 and B2 (or ran them concurrently) would pass every existing
    test in this file unnoticed.

    This test closes that gap directly: point ``governed_remote`` at a
    sentinel path that cannot possibly resolve, and prove the foreign-root
    refusal fires without B2 ever needing to run. The sentinel is proven a
    real trap first -- calling ``resolve_governed_master`` against it
    directly raises its own distinct "did not resolve" error -- so a pass
    below can only mean B1 fired first, not that B2 silently no-opped on a
    remote that happened to tolerate being unreachable.
    """
    from scripts.ember_restart.contract import build_r1_warm100_entry
    from scripts.ember_restart.source_authority import resolve_governed_master

    sentinel_remote = str(tmp_path / "sentinel-unreachable-remote-does-not-exist")

    with pytest.raises(ValueError, match="did not resolve"):
        resolve_governed_master(foreign, sentinel_remote)

    foreign_head = _git(foreign, "rev-parse", "HEAD")
    manifest_path = _manifest_at(tmp_path, foreign_head)

    with pytest.raises(ValueError, match="object store"):
        build_r1_warm100_entry(
            manifest_path,
            source_commit=foreign_head,
            source_root=foreign,
            trusted_verifier_registry=tmp_path / "trusted-verifiers.json",
            governed_remote=sentinel_remote,
            **_source_paths(foreign),
        )
