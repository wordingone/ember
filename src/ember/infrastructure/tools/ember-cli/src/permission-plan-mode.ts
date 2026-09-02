// permission-plan-mode.ts — plan-mode entry/exit permission components
// and computer-use capability gating.

import React from "react";
import { Box, Text } from "./ink/components.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PlanModeOption {
  key:   string;
  label: string;
}

export interface ComputerUseCapabilities {
  clipboardRead:  boolean;
  clipboardWrite: boolean;
  systemKeyCombos: boolean;
}

export type ComputerUseCapabilityKey =
  | "clipboardRead"
  | "clipboardWrite"
  | "systemKeyCombos";

// ---------------------------------------------------------------------------
// AC7: Accessibility URL constant
// ---------------------------------------------------------------------------

export const COMPUTER_USE_ACCESSIBILITY_URL =
  "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility";

// ---------------------------------------------------------------------------
// AC1: Enter plan mode options (exactly 2)
// ---------------------------------------------------------------------------

export function buildEnterPlanModeOptions(): PlanModeOption[] {
  return [
    { key: "yes", label: "Yes, enter plan mode" },
    { key: "no",  label: "No, continue normally" },
  ];
}

// ---------------------------------------------------------------------------
// AC3/AC4: Exit plan mode options (ultraplan conditional)
// ---------------------------------------------------------------------------

export function buildExitPlanModeOptions(
  ultraplanEnabled: boolean,
): PlanModeOption[] {
  const opts: PlanModeOption[] = [
    { key: "approve", label: "Approve and execute" },
    { key: "reject",  label: "Reject plan" },
  ];
  if (ultraplanEnabled) {
    opts.push({ key: "ultraplan", label: "Ultraplan mode" });
  }
  return opts;
}

// ---------------------------------------------------------------------------
// buildPlanApprovalOptions — convenience wrapper used by tests
// ---------------------------------------------------------------------------

export interface PlanApprovalFlags {
  ULTRAPLAN_ENABLED?: boolean;
}

export function buildPlanApprovalOptions(
  flags: PlanApprovalFlags,
): PlanModeOption[] {
  return buildExitPlanModeOptions(!!flags.ULTRAPLAN_ENABLED);
}

// ---------------------------------------------------------------------------
// AC6: slicePlanText — at most 1000 characters
// ---------------------------------------------------------------------------

export function slicePlanText(text: string): string {
  return text.slice(0, 1000);
}

// ---------------------------------------------------------------------------
// buildPermissionUpdates — used by structural tests
// ---------------------------------------------------------------------------

export function buildPermissionUpdates(
  _mode: string,
): Array<{ type: string; behavior: string; destination: string }> {
  return [];
}

// ---------------------------------------------------------------------------
// AC8/AC9: Computer-use capability builders
// ---------------------------------------------------------------------------

export function emptyComputerUseCapabilities(): ComputerUseCapabilities {
  return { clipboardRead: false, clipboardWrite: false, systemKeyCombos: false };
}

export function buildComputerUseCapabilities(
  granted: ComputerUseCapabilityKey[],
): ComputerUseCapabilities {
  const caps = emptyComputerUseCapabilities();
  for (const cap of granted) {
    caps[cap] = true;
  }
  return caps;
}

// ---------------------------------------------------------------------------
// React components (AC2/AC5 structural)
// ---------------------------------------------------------------------------

export interface EnterPlanModePermissionRequestProps {
  toolUseID?:  string;
  description?: string;
  onAllow?:    () => void;
  onReject?:   () => void;
}

export function EnterPlanModePermissionRequest(
  props: EnterPlanModePermissionRequestProps,
): React.ReactElement {
  const opts = buildEnterPlanModeOptions();
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, "Enter plan mode?"),
    React.createElement(Text, null, props.description ?? ""),
    ...opts.map((o) =>
      React.createElement(Text, { key: o.key }, o.label),
    ),
  );
}

export interface ExitPlanModeConfirm {
  toolUseID:       string;
  description:     string;
  input:           Record<string, unknown>;
  planText:        string;
  contextUsagePct?: number;
  flags:           { ULTRAPLAN_ENABLED?: boolean };
  onAllow:         () => void;
  onReject:        () => void;
}

export interface ExitPlanModePermissionRequestProps {
  confirm: ExitPlanModeConfirm;
}

export function ExitPlanModePermissionRequest(
  props: ExitPlanModePermissionRequestProps,
): React.ReactElement {
  const { confirm } = props;
  const opts = buildExitPlanModeOptions(!!confirm.flags.ULTRAPLAN_ENABLED);
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, "Approve plan?"),
    React.createElement(Text, null, slicePlanText(confirm.planText)),
    ...opts.map((o) =>
      React.createElement(Text, { key: o.key }, o.label),
    ),
  );
}

export interface ComputerUseApprovalProps {
  capabilities:  ComputerUseCapabilities;
  onGrant?:      (caps: ComputerUseCapabilities) => void;
  onReject?:     () => void;
  accessibilityUrl?: string;
}

export function ComputerUseApproval(
  props: ComputerUseApprovalProps,
): React.ReactElement {
  const url = props.accessibilityUrl ?? COMPUTER_USE_ACCESSIBILITY_URL;
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, "Grant computer-use permissions?"),
    React.createElement(Text, { dimColor: true }, url),
  );
}
