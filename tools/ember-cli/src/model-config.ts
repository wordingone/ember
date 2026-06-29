// model-config.ts
// Feature capability queries for model variants available in Ember.
// L1 leaf: no intra-ember dependencies.

/** The local inference model identifier. */
export const LOCAL_MODEL_ID = 'qwen-3.6';

// ---- Internal helpers ----

/** Strips the [1m] multi-instance suffix before capability lookup. */
function canonicalize(modelId: string): string {
  return modelId.replace(/\[1m\]$/, '');
}

// ---- Capability queries ----

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
 * Returns true when the model supports structured JSON outputs.
 * The local model supports this via llama-server grammar constraints.
 */
export function modelSupportsStructuredOutputs(modelId: string): boolean {
  return canonicalize(modelId) === LOCAL_MODEL_ID;
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
