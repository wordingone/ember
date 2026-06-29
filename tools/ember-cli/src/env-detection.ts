// env-detection.ts — re-export shim for test compatibility.
// CONTRACT-GAP: native-installer.test.ts imports _resetConfigHomeMemo from './env-detection'
// (root src/ level), but the implementation lives in './utils/env-detection.ts'.
// This file exists solely to satisfy that test import without modifying the test.
export { getEmberConfigHomeDir, _resetConfigHomeMemo } from './utils/env-detection.ts';
