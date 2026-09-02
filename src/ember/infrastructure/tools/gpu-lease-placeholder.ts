/**
 * gpu-lease-placeholder.ts — Static placeholder pane renderer for GPU leases.
 *
 * Reads state/gpu-lease.json and renders a minimal informative text panel
 * for display when the cockpit is deliberately down during GPU training leases.
 * Zero GPU/VRAM use; purely file I/O and text formatting.
 *
 * Exit codes:
 *   0 = rendered successfully (with lease) or no lease file present
 *   1 = malformed JSON or missing required fields (fail-closed)
 */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

interface GPULease {
  purpose: string;
  holder: string;
  since: string;
  expected_end: string;
  receipts_path?: string;
}

function loadLease(repoRoot: string): GPULease | null {
  const leasePath = join(repoRoot, 'state', 'gpu-lease.json');

  if (!existsSync(leasePath)) {
    return null;
  }

  try {
    const content = readFileSync(leasePath, 'utf8');
    const lease = JSON.parse(content) as unknown;

    // Validate required fields
    if (typeof lease !== 'object' || lease === null) {
      throw new Error('Lease JSON is not an object');
    }

    const leaseObj = lease as Record<string, unknown>;
    const requiredFields = ['purpose', 'holder', 'since', 'expected_end'];

    for (const field of requiredFields) {
      if (typeof leaseObj[field] !== 'string') {
        throw new Error(`Missing or non-string field: ${field}`);
      }
    }

    // Validate ISO 8601 timestamps
    const sinceDate = new Date(leaseObj.since as string);
    const endDate = new Date(leaseObj.expected_end as string);

    if (isNaN(sinceDate.getTime()) || isNaN(endDate.getTime())) {
      throw new Error('Invalid ISO 8601 timestamp in since or expected_end');
    }

    return {
      purpose: leaseObj.purpose as string,
      holder: leaseObj.holder as string,
      since: leaseObj.since as string,
      expected_end: leaseObj.expected_end as string,
      receipts_path:
        typeof leaseObj.receipts_path === 'string' ? (leaseObj.receipts_path as string) : undefined,
    };
  } catch (error) {
    // Fail closed on any JSON or validation error
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Error loading GPU lease: ${message}`);
    process.exit(1);
  }
}

function formatTimestamp(isoString: string): string {
  try {
    const date = new Date(isoString);
    // Format as "2026-07-07 12:34 UTC"
    return date.toISOString().replace('T', ' ').replace('.000Z', ' UTC').replace('Z', ' UTC');
  } catch {
    return isoString;
  }
}

function padLine(content: string, totalWidth: number = 80): string {
  // totalWidth includes the two border chars (║ ║)
  const innerWidth = totalWidth - 4; // Account for "║  " and "  ║"
  const padded = content.padEnd(innerWidth);
  return `║  ${padded}  ║`;
}

function renderPlaceholder(lease: GPULease): string {
  const lines: string[] = [];
  const boxWidth = 80;

  // Header
  lines.push('╔════════════════════════════════════════════════════════════════════════════════╗');
  lines.push('║                                                                                ║');
  lines.push('║  EMBER — GPU LEASE ACTIVE                                                     ║');
  lines.push('║                                                                                ║');
  lines.push('╠════════════════════════════════════════════════════════════════════════════════╣');

  // Content
  lines.push('║                                                                                ║');
  lines.push(padLine(`Leased to:    ${lease.holder}`));
  lines.push(padLine(`Purpose:      ${lease.purpose}`));
  lines.push('║                                                                                ║');
  lines.push(padLine(`Since:        ${formatTimestamp(lease.since)}`));
  lines.push(padLine(`Returns ~     ${formatTimestamp(lease.expected_end)}`));

  if (lease.receipts_path) {
    lines.push('║                                                                                ║');
    lines.push(padLine(`Receipts:     ${lease.receipts_path}`));
  }

  lines.push('║                                                                                ║');
  lines.push(
    padLine('The cockpit will return automatically when this lease expires.')
  );
  lines.push('║                                                                                ║');
  lines.push('╚════════════════════════════════════════════════════════════════════════════════╝');

  return lines.join('\n');
}

async function main() {
  // Get repository root (assume we're invoked from repo root or with an arg)
  const repoRoot = process.argv[2] || process.cwd();

  const lease = loadLease(repoRoot);

  if (lease === null) {
    console.log('no lease');
    process.exit(0);
  }

  const panel = renderPlaceholder(lease);
  console.log(panel);
  process.exit(0);
}

main().catch((error) => {
  console.error(`Unexpected error: ${error}`);
  process.exit(1);
});
