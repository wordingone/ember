// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// agent-identity.ts — product identity constants for the Ember CLI.
// L1 leaf: no intra-ember dependencies.

/** The product name used in branding, configuration, and telemetry. */
export const PRODUCT_NAME = 'ember';

/** The CLI binary name on Windows. */
export const CLI_BINARY_WIN = 'ember.exe';

/** The CLI binary name on Unix-like systems. */
export const CLI_BINARY_UNIX = 'ember';

/** The configuration directory name placed in the user's home directory. */
export const CONFIG_DIR_NAME = '.ember';

/** The current CLI version string. */
export const VERSION = '0.1.0';

/** Fallback port number when no port is explicitly configured. */
export const PORT_FALLBACK = 20_000;

/**
 * Feature flags that are active in the current beta build.
 * An empty array means no experimental features are enabled by default.
 */
export const ACTIVE_BETA_FLAGS: string[] = [];
