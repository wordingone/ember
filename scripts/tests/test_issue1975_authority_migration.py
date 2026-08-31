from pathlib import PurePosixPath


def test_issue1975_state_uses_governance_domain_authority_path():
    from scripts import verify_authority_conservation as verifier

    assert verifier.authority_canonical_relative_path("STATE.md") == PurePosixPath(
        "docs/domains/governance/authority/STATE.md"
    )
    assert verifier.authority_canonical_relative_path("INVARIANT.md") == PurePosixPath(
        "docs/domains/governance/authority/INVARIANT.md"
    )
