// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// model-config.ts
// Feature capability queries for model variants available in Ember.
// L1 leaf: no intra-ember dependencies.

// ---- Capability queries ----

/**
 * A capability declaration bound to a served model's exact
 * `modelConfigSha256` (see `entrypoints/model-seat.ts::SelectedModelContract`).
 * `modelConfigSha256` is `null` when no owned identity is selected (e.g. a
 * REFERENCE_ONLY or OFFLINE seat) — never a hardcoded model-name literal.
 */
export interface ModelCapabilityDeclaration {
  modelConfigSha256: string | null;
  structuredOutputs: boolean;
}

/**
 * Returns true when the model supports Inline Streaming Prefill (ISP).
 * ISP is a cloud-only feature; the local model always returns false.
 */
export function modelSupportsISP(_modelId: string): boolean {
  return false;
}

/**
 * Returns true when the model supports cloud context management
 * (automatic context window compression on the server side).
 * Cloud-only; always false for local.
 */
export function modelSupportsContextManagement(_modelId: string): boolean {
  return false;
}

/**
 * Returns true when the served model supports structured JSON outputs.
 *
 * Never inferred from a model-id string literal. Honored ONLY when the
 * caller supplies an exact capability declaration bound to the served
 * model's `modelConfigSha256` — an owned identity without such a
 * declaration (or without a `modelConfigSha256` to bind it to) defaults to
 * false.
 */
export function modelSupportsStructuredOutputs(
  declaration: ModelCapabilityDeclaration | null | undefined,
): boolean {
  if (declaration == null) return false;
  if (
    typeof declaration.modelConfigSha256 !== 'string' ||
    declaration.modelConfigSha256.trim() === ''
  ) {
    return false;
  }
  return declaration.structuredOutputs === true;
}

/**
 * Returns the sorted, deduplicated list of beta header values to include
 * when calling the model API with the given feature flags enabled.
 *
 * The local model never requires provider beta headers, so this always
 * returns an empty array regardless of `features`.
 */
export function getAllModelBetas(
  _modelId: string,
  _features: {
    ispEnabled?: boolean;
    tokenEfficientTools?: boolean;
    extendedContext?: boolean;
    [key: string]: boolean | undefined;
  },
): string[] {
  return [];
}
