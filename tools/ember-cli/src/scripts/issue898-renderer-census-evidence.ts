// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 renderer/census evidence consumer

import {
  sealIssue898RendererCensusEvidence,
  type Issue898RendererCensusEvidenceInput,
} from "../services/issue898-renderer-census-evidence.ts";

interface EvidenceReceiptSummary {
  schema_version: "ember-issue898-renderer-census-evidence-v1";
  verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION";
  receipt_sha256: string;
}

interface Issue898RendererCensusCliDependencies {
  seal: (input: Issue898RendererCensusEvidenceInput) => EvidenceReceiptSummary;
  writeLine: (line: string) => void;
}

const FLAG_TO_FIELD = new Map<string, keyof Omit<Issue898RendererCensusEvidenceInput, "cockpitPid">>([
  ["--soak-receipt", "soakReceiptPath"],
  ["--polls", "pollsPath"],
  ["--renderer", "rendererPath"],
  ["--output", "outputPath"],
  ["--source-commit", "sourceCommit"],
  ["--cockpit-process-start-token", "cockpitProcessStartToken"],
  ["--receipt-written-at", "receiptWrittenAt"],
]);

export function parseIssue898RendererCensusArgs(
  argv: readonly string[],
): Issue898RendererCensusEvidenceInput {
  if (argv.length % 2 !== 0) throw new Error("ISSUE898_RENDERER_CENSUS_ARGS_INVALID");
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index]!;
    const value = argv[index + 1]!;
    if ((flag !== "--cockpit-pid" && !FLAG_TO_FIELD.has(flag))
      || values.has(flag)
      || value.length === 0) {
      throw new Error("ISSUE898_RENDERER_CENSUS_ARGS_INVALID");
    }
    values.set(flag, value);
  }
  if (values.size !== FLAG_TO_FIELD.size + 1) {
    throw new Error("ISSUE898_RENDERER_CENSUS_ARGS_INVALID");
  }

  const cockpitPidText = values.get("--cockpit-pid")!;
  if (!/^[1-9][0-9]*$/.test(cockpitPidText)) {
    throw new Error("ISSUE898_RENDERER_CENSUS_COCKPIT_PID_INVALID");
  }
  const cockpitPid = Number(cockpitPidText);
  if (!Number.isSafeInteger(cockpitPid)) {
    throw new Error("ISSUE898_RENDERER_CENSUS_COCKPIT_PID_INVALID");
  }

  return {
    soakReceiptPath: values.get("--soak-receipt")!,
    pollsPath: values.get("--polls")!,
    rendererPath: values.get("--renderer")!,
    outputPath: values.get("--output")!,
    sourceCommit: values.get("--source-commit")!,
    cockpitPid,
    cockpitProcessStartToken: values.get("--cockpit-process-start-token")!,
    receiptWrittenAt: values.get("--receipt-written-at")!,
  };
}

export function runIssue898RendererCensusCli(
  argv: readonly string[],
  dependencies: Issue898RendererCensusCliDependencies = {
    seal: sealIssue898RendererCensusEvidence,
    writeLine: console.log,
  },
): EvidenceReceiptSummary {
  const input = parseIssue898RendererCensusArgs(argv);
  const receipt = dependencies.seal(input);
  dependencies.writeLine(JSON.stringify({
    schema_version: receipt.schema_version,
    verdict: receipt.verdict,
    output_path: input.outputPath,
    receipt_sha256: receipt.receipt_sha256,
  }));
  return receipt;
}

if (import.meta.main) {
  try {
    runIssue898RendererCensusCli(Bun.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
