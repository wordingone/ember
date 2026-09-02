// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// env-detection.ts — re-export shim for test compatibility.
// CONTRACT-GAP: native-installer.test.ts imports _resetConfigHomeMemo from './env-detection'
// (root src/ level), but the implementation lives in './utils/env-detection.ts'.
// This file exists solely to satisfy that test import without modifying the test.
export { getEmberConfigHomeDir, _resetConfigHomeMemo } from './utils/env-detection.ts';
