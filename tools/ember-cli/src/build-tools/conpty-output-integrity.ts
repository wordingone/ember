// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Issue #354: fail closed when Windows ConPTY injects raw NUL bytes after stdout.write.

export interface ConptyOutputIntegrity {
  raw_bytes_utf8: number;
  raw_nul_count: 0;
}

export function requireNulFreeConptyOutput(output: string): ConptyOutputIntegrity {
  let count = 0;
  let firstIndex = -1;
  for (let index = 0; index < output.length; index += 1) {
    if (output.charCodeAt(index) !== 0) continue;
    if (firstIndex < 0) firstIndex = index;
    count += 1;
  }
  if (count > 0) {
    throw new Error(`CONPTY_RAW_NUL_INJECTION count=${count} first_index=${firstIndex}`);
  }
  return { raw_bytes_utf8: Buffer.byteLength(output), raw_nul_count: 0 };
}
