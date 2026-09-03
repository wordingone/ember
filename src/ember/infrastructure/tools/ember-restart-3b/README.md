<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# ember-restart-3b tool root (canonical location)

This directory is the canonical home of the `ember-restart-3b` tools under the
domain layout. The EMBER-02B workstream scope names this prefix so the
legacy-cutover carrier can move `tools/ember-restart-3b/**` here under the
authority guard; until that carrier lands, the executable tools still live at
`tools/ember-restart-3b/`, and CI resolves each tool at whichever of the two
locations holds it.
