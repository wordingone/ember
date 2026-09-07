from pathlib import PurePosixPath


def test_issue1975_state_uses_governance_domain_authority_path():
    import importlib.util
    from pathlib import Path

    # The verifier moved into the governance domain during the cutover; this test kept
    # importing it from the repository-root `scripts` package, which is not a package and no
    # longer holds the module. Resolved by path, the way the canonical authority test does.
    verifier_path = (
        Path(__file__).resolve().parents[2]
        / "src" / "ember" / "governance" / "scripts" / "verify_authority_conservation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "issue1975_authority_verifier", verifier_path
    )
    assert spec is not None and spec.loader is not None, verifier_path
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    assert verifier.authority_canonical_relative_path("STATE.md") == PurePosixPath(
        "docs/domains/governance/authority/STATE.md"
    )
    # This assertion used to be the contrast case: STATE.md had migrated into the governance
    # domain and everything else still canonicalized under `docs/authority`. The cutover repointed
    # AUTHORITY_DIRECTORY at the domain directory and demoted `docs/authority` to the legacy
    # directory, so the two constants now name the same place and there is no contrast left to
    # draw. Asserting the old literal asserts something that stopped being true.
    #
    # Worth noting rather than fixing here: docs/authority/INVARIANT.md has not itself moved, so
    # the file's canonical path and its actual location differ. Lookups still resolve because
    # authority_candidate_relative_paths includes the legacy directory. Moving the file is a
    # separate change with its own guard surface and is not made under a test repair.
    assert verifier.authority_canonical_relative_path("INVARIANT.md") == PurePosixPath(
        "docs/domains/governance/authority/INVARIANT.md"
    )
