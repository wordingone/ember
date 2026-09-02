// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import type { TelemetryState } from "../services/telemetry-watch.ts";

export function telemetryMemoKey(state: TelemetryState): string | null {
  const { lastGovernor, activeRun, lastCheckpoint, runStatus } = state;
  if (!lastGovernor && !activeRun && !lastCheckpoint && !runStatus) return null;
  const parts: string[] = [];
  if (lastGovernor) {
    parts.push(`VRAM ${lastGovernor.vramUsedGib.toFixed(1)}/${lastGovernor.vramTotalGib.toFixed(1)}`);
  }
  if (activeRun) {
    const step = activeRun.totalSteps != null ? `${activeRun.step}/${activeRun.totalSteps}` : String(activeRun.step);
    let run = `train r=${activeRun.runId} step ${step}`;
    if (activeRun.loss != null) run += ` loss ${activeRun.loss.toFixed(2)}`;
    if (activeRun.stepMs != null && activeRun.stepMs > 0) run += ` ${(1000 / activeRun.stepMs).toFixed(2)} step/s`;
    parts.push(run);
  }
  if (lastCheckpoint) {
    parts.push(`ckpt ${lastCheckpoint.step} ${lastCheckpoint.checkpointManifestSha256.slice(0, 12)}`);
  }
  if (runStatus) {
    let status = `model chat ${runStatus.modelChat}`;
    if (runStatus.restoreNotBefore) status += ` restore ${runStatus.restoreNotBefore}`;
    parts.push(status);
  }
  return `⚡ ${parts.join(" · ")}`;
}
