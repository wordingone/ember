// tools/schedule-cron.ts — Cron scheduling tools: CronCreate, CronDelete, CronList.
//
// Schedules prompt-enqueue jobs against a standard 5-field cron expression.
// Jobs live in an in-memory store (_cronStore) for the session lifetime.
// Durable jobs (durable:true) are advisory-flagged; actual durable backing is
// provided by the runtime when EMBER_DURABLE_CRON=1.

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------------

export const isKairosCronEnabled = (): boolean =>
  process.env["EMBER_KAIROS_CRON"] === "1";

const isDurableCronEnabled = (): boolean =>
  process.env["EMBER_DURABLE_CRON"] === "1";

// ---------------------------------------------------------------------------
// Cron validation helpers
// ---------------------------------------------------------------------------

/** [min, max] inclusive for each cron field: minute hour dom month dow */
const CRON_FIELD_RANGES: [number, number][] = [
  [0, 59],
  [0, 23],
  [1, 31],
  [1, 12],
  [0, 7],
];

function isValidCronField(field: string, min: number, max: number): boolean {
  if (field === "*") return true;
  if (/^\*\/\d+$/.test(field)) {
    const step = parseInt(field.slice(2), 10);
    return step >= 1;
  }
  if (/^\d+-\d+$/.test(field)) {
    const [lo, hi] = field.split("-").map(Number);
    return lo >= min && hi <= max && lo <= hi;
  }
  if (/^[\d,]+$/.test(field)) {
    return field.split(",").every((v) => {
      const n = parseInt(v, 10);
      return n >= min && n <= max;
    });
  }
  if (/^\d+$/.test(field)) {
    const n = parseInt(field, 10);
    return n >= min && n <= max;
  }
  if (/^\d+-\d+\/\d+$/.test(field)) {
    const [range, stepStr] = field.split("/");
    const [lo, hi] = range.split("-").map(Number);
    const s = parseInt(stepStr, 10);
    return lo >= min && hi <= max && lo <= hi && s >= 1;
  }
  return false;
}

/** Returns null if valid, or an error string describing the first invalid field. */
function validateCronExpression(expr: string): string | null {
  const fields = expr.trim().split(/\s+/);
  if (fields.length !== 5) {
    return `Cron expression must have exactly 5 fields; got ${fields.length}.`;
  }
  const fieldNames = ["minute", "hour", "day-of-month", "month", "day-of-week"];
  for (let i = 0; i < 5; i++) {
    const [min, max] = CRON_FIELD_RANGES[i];
    if (!isValidCronField(fields[i], min, max)) {
      return `Invalid cron ${fieldNames[i]} field: "${fields[i]}"`;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Human-readable schedule description
// ---------------------------------------------------------------------------

const MONTH_NAMES: string[] = [
  "",
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const DOW_NAMES: string[] = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

function formatHour12(hour: number, minute: number): string {
  const ampm = hour < 12 ? "am" : "pm";
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return minute === 0
    ? `${h12}${ampm}`
    : `${h12}:${minute.toString().padStart(2, "0")}${ampm}`;
}

function humanizeCronExpression(expr: string, recurring = true): string {
  const fields = expr.trim().split(/\s+/);
  const [min, hr, dom, mon, dow] = fields;

  if (/^\*\/(\d+)$/.test(min) && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    const n = parseInt(min.slice(2), 10);
    const unit = n === 1 ? "minute" : "minutes";
    return `every ${n} ${unit}`;
  }
  if (min === "*" && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    return "every minute";
  }
  if (/^\d+$/.test(min) && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    const m = parseInt(min, 10);
    return m === 0 ? "every hour" : `every hour at :${m.toString().padStart(2, "0")}`;
  }
  if (/^\d+$/.test(min) && /^\d+$/.test(hr) && dom === "*" && mon === "*" && dow === "1-5") {
    const m = parseInt(min, 10);
    const h = parseInt(hr, 10);
    return `weekdays at ${formatHour12(h, m)} local`;
  }
  if (/^\d+$/.test(min) && /^\d+$/.test(hr) && dom === "*" && mon === "*" && dow === "*") {
    const m = parseInt(min, 10);
    const h = parseInt(hr, 10);
    return `daily at ${formatHour12(h, m)} local`;
  }
  if (
    /^\d+$/.test(min) &&
    /^\d+$/.test(hr) &&
    /^\d+$/.test(dom) &&
    /^\d+$/.test(mon) &&
    dow === "*"
  ) {
    const m = parseInt(min, 10);
    const h = parseInt(hr, 10);
    const d = parseInt(dom, 10);
    const mo = parseInt(mon, 10);
    const monthName = MONTH_NAMES[mo] ?? `M${mo}`;
    const suffix = recurring ? "" : " once";
    return `${monthName} ${d} at ${formatHour12(h, m)} local${suffix}`;
  }
  if (/^\d+$/.test(min) && /^\d+$/.test(hr) && dom === "*" && mon === "*" && /^\d+$/.test(dow)) {
    const m = parseInt(min, 10);
    const h = parseInt(hr, 10);
    const d = parseInt(dow, 10);
    const dayName = DOW_NAMES[d % 7] ?? `DOW${d}`;
    return `${dayName} at ${formatHour12(h, m)} local`;
  }
  return expr;
}

// ---------------------------------------------------------------------------
// Job store
// ---------------------------------------------------------------------------

interface CronJob {
  id: string;
  cron: string;
  prompt: string;
  recurring: boolean;
  durable: boolean;
  humanSchedule: string;
  createdAt: number;
  agentId: string | undefined;
}

const MAX_CRON_JOBS = 50;
const DEFAULT_MAX_AGE_DAYS = 14;

let _cronStore: Map<string, CronJob> = new Map();
let _idCounter = 0;

function generateJobId(): string {
  _idCounter++;
  return `cron_${Date.now()}_${_idCounter}`;
}

function isTeamLead(context: ToolUseContext): boolean {
  return !context.agentId;
}

// Test hook — allows resetting the store in unit tests.
export function _resetCronStore(): void {
  _cronStore = new Map();
  _idCounter = 0;
}

// ---------------------------------------------------------------------------
// CronCreate
// ---------------------------------------------------------------------------

const CronCreateInputSchema = z
  .object({
    cron: z.string(),
    prompt: z.string(),
    recurring: z.boolean().optional(),
    durable: z.boolean().optional(),
  })
  .strict();

type CronCreateInput = z.infer<typeof CronCreateInputSchema>;

export const CronCreateTool = buildTool<CronCreateInput, unknown>({
  name: "CronCreate",
  inputSchema: CronCreateInputSchema,

  isEnabled: () => isKairosCronEnabled(),

  validateInput: (rawInput: unknown) => {
    const input = rawInput as CronCreateInput;
    const validationError = validateCronExpression(input.cron);
    if (validationError) {
      return { result: false as const, message: validationError, errorCode: "INVALID_CRON" };
    }
    return { result: true as const };
  },

  call: async (rawArgs: unknown, context: ToolUseContext) => {
    const args = rawArgs as CronCreateInput;
    const validationError = validateCronExpression(args.cron);
    if (validationError) {
      throw new Error(validationError);
    }
    if (_cronStore.size >= MAX_CRON_JOBS) {
      throw new Error(`Maximum of ${MAX_CRON_JOBS} active cron jobs reached.`);
    }
    const recurring = args.recurring ?? true;
    const requestedDurable = args.durable ?? false;
    if (!isTeamLead(context) && requestedDurable) {
      throw new Error("Teammate agents cannot create durable cron jobs.");
    }
    const durable = requestedDurable && isDurableCronEnabled();
    const id = generateJobId();
    const humanSchedule = humanizeCronExpression(args.cron, recurring);
    const job: CronJob = {
      id,
      cron: args.cron,
      prompt: args.prompt,
      recurring,
      durable,
      humanSchedule,
      createdAt: Date.now(),
      agentId: context.agentId,
    };
    _cronStore.set(id, job);

    let message: string;
    if (!recurring) {
      message = `Job ${id} scheduled to run once at ${humanSchedule}.`;
    } else if (durable) {
      message = `Job ${id} scheduled to run ${humanSchedule}. It will persist across sessions and auto-expire after ${DEFAULT_MAX_AGE_DAYS} days.`;
    } else {
      message = `Job ${id} scheduled to run ${humanSchedule}. It will only run for the current session.`;
    }

    return {
      data: {
        id,
        humanSchedule,
        recurring,
        durable: durable ? true : undefined,
        message,
      },
    };
  },

  description: () =>
    "Schedule a cron job to enqueue a prompt at a specified cadence. Use standard 5-field cron expressions in local time.",

  prompt: () =>
    "Use CronCreate to schedule recurring or one-shot prompts. Examples: '*/5 * * * *' (every 5 min), '0 9 * * *' (daily 9am). Set recurring:false for one-shot jobs.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});

// ---------------------------------------------------------------------------
// CronDelete
// ---------------------------------------------------------------------------

const CronDeleteInputSchema = z.object({ id: z.string() }).strict();
type CronDeleteInput = z.infer<typeof CronDeleteInputSchema>;

export const CronDeleteTool = buildTool<CronDeleteInput, unknown>({
  name: "CronDelete",
  inputSchema: CronDeleteInputSchema,

  isEnabled: () => isKairosCronEnabled(),

  call: async (rawArgs: unknown, context: ToolUseContext) => {
    const args = rawArgs as CronDeleteInput;
    const job = _cronStore.get(args.id);
    if (!job) {
      throw new Error(`Cron job not found: ${args.id}`);
    }
    if (!isTeamLead(context) && job.agentId !== context.agentId) {
      throw new Error(
        `Teammate agent ${context.agentId} cannot delete job ${args.id} owned by ${job.agentId}.`,
      );
    }
    _cronStore.delete(args.id);
    return {
      data: {
        id: args.id,
        message: `Cancelled job ${args.id}.`,
      },
    };
  },

  description: () => "Cancel a scheduled cron job by its ID.",

  prompt: () =>
    "Use CronDelete to cancel a job you created with CronCreate. You can only delete your own jobs in multi-agent sessions.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});

// ---------------------------------------------------------------------------
// CronList
// ---------------------------------------------------------------------------

const CronListInputSchema = z.object({}).strict();
type CronListInput = z.infer<typeof CronListInputSchema>;

export const CronListTool = buildTool<CronListInput, unknown>({
  name: "CronList",
  inputSchema: CronListInputSchema,

  isReadOnly: () => true,
  isConcurrencySafe: () => true,
  isEnabled: () => isKairosCronEnabled(),

  call: async (_rawArgs: unknown, context: ToolUseContext) => {
    const isLead = isTeamLead(context);
    const visibleJobs = Array.from(_cronStore.values()).filter((job) => {
      if (!isLead && job.agentId !== context.agentId) return false;
      return true;
    });
    const jobs = visibleJobs.map((job) => ({
      id: job.id,
      cron: job.cron,
      humanSchedule: job.humanSchedule,
      prompt: job.prompt.length > 80 ? job.prompt.slice(0, 77) + "..." : job.prompt,
      ...(job.recurring ? {} : { recurring: false }),
      ...(job.durable ? { durable: true } : {}),
    }));
    return { data: { jobs } };
  },

  description: () => "List all active cron jobs visible to the current agent.",

  prompt: () => "Use CronList to see all scheduled cron jobs. Teammates only see their own jobs.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});
