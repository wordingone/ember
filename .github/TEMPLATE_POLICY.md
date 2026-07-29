<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Template Policy

Version: `ember-template-policy/v1`

GitHub-native issue forms and pull-request templates live under
`.github/ISSUE_TEMPLATE` and `.github/PULL_REQUEST_TEMPLATE`.
`REVIEW_TEMPLATE` and `COMMENT_TEMPLATE` are Ember-defined libraries, not
native GitHub discovery surfaces.

Every template has a machine marker. Required prompts vary by epistemic type:
defects demand reproduction; enhancements demand a baseline and metric;
research demands falsification; experiments demand identities, controls,
stopping and inconclusive rules; governance demands authority and
supersession effects.

Agents and humans select the correct PR template explicitly. The PR structural
validator checks markers and required sections but never treats prose presence
as proof. Any later commit invalidates an earlier exact-head review.

Public templates must not solicit credentials, private model or corpus bytes,
copyrighted data, secrets, or sensitive host paths. Bounded artifacts should be
redacted and content-addressed.
