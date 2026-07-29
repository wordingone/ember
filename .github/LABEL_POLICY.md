<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Label Policy

Version: `ember-label-policy/v1`

`.github/labels.yml` is authoritative. Names are lowercase except canonical
`EMBER-XX` milestone identifiers. Families are orthogonal and use one
accessible color per namespace.

Open issues and pull requests require exactly one applicable `kind:*`, one to
three `area:*`, and exactly one `state:*`. Priority is required after
triage. Severity applies only to defect and model-behavior issues. Capability
labels mean only that work concerns a capability. `affects:EMBER-XX` is a
multi-valued impact facet and never a completion claim.

Every `needs:*` label requires a precise lifecycle comment naming the missing
condition, provider, blocked status, and removal condition. Review labels
require an exact-head review artifact. Merge labels record deliberate authority,
not merely green CI. Resolution labels require a documented disposition.

Unknown, aliased, deprecated, or mutually exclusive labels fail policy.
Automation may change only fields explicitly authorized by the manifest.
Labels never replace milestones, sub-issues, dependencies, closing links, or
acceptance-clause transfer.
