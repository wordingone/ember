# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
python src\ember\governance\scripts\ember_gate_goal_mode_parity_adapter.py @Args
