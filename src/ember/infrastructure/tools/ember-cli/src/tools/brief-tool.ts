// tools/brief-tool.ts — SendUserMessage tool (alias: Brief).
//
// Sends a markdown message with optional file attachments to the user.
// Only available when KAIROS brief mode is active (EMBER_BRIEF=1 or
// EMBER_KAIROS_BRIEF=1). Attachments are resolved to absolute paths and
// validated for existence; images may be uploaded via the bridge when
// EMBER_BRIDGE_MODE=1 and size is within UPLOAD_SIZE_LIMIT.

import { stat } from "fs/promises";
import { resolve, extname } from "path";
import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Feature flags (all overridable in tests)
// ---------------------------------------------------------------------------

export let isKairosBriefModeActive: () => boolean = () =>
  process.env["EMBER_BRIEF"] === "1" || process.env["EMBER_KAIROS_BRIEF"] === "1";

export let hasKairosBriefEntitlement: () => Promise<boolean> = async () =>
  process.env["EMBER_BRIEF_ENTITLEMENT"] === "1";

export let isBridgeModeActive: () => boolean = () =>
  process.env["EMBER_BRIDGE_MODE"] === "1";

export let uploadAttachment: (path: string, mimeType: string) => Promise<string | null> =
  async (_path, _mimeType) => null;

export function _overrideBriefFeatureFlags(overrides: {
  isKairosBriefModeActive?: () => boolean;
  hasKairosBriefEntitlement?: () => Promise<boolean>;
  isBridgeModeActive?: () => boolean;
  uploadAttachment?: (path: string, mimeType: string) => Promise<string | null>;
}): void {
  if (overrides.isKairosBriefModeActive !== undefined)
    isKairosBriefModeActive = overrides.isKairosBriefModeActive;
  if (overrides.hasKairosBriefEntitlement !== undefined)
    hasKairosBriefEntitlement = overrides.hasKairosBriefEntitlement;
  if (overrides.isBridgeModeActive !== undefined)
    isBridgeModeActive = overrides.isBridgeModeActive;
  if (overrides.uploadAttachment !== undefined)
    uploadAttachment = overrides.uploadAttachment;
}

// ---------------------------------------------------------------------------
// Entitlement cache
// ---------------------------------------------------------------------------

const ENTITLEMENT_CACHE_TTL_MS = 5 * 60 * 1000;

interface EntitlementCacheEntry {
  value: boolean;
  expiresAt: number;
}

let _entitlementCache: EntitlementCacheEntry | null = null;

async function getCachedEntitlement(): Promise<boolean> {
  const now = Date.now();
  if (_entitlementCache && _entitlementCache.expiresAt > now) {
    return _entitlementCache.value;
  }
  const value = await hasKairosBriefEntitlement();
  _entitlementCache = { value, expiresAt: now + ENTITLEMENT_CACHE_TTL_MS };
  return value;
}

// ---------------------------------------------------------------------------
// Attachment resolution
// ---------------------------------------------------------------------------

const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp"]);
const UPLOAD_SIZE_LIMIT = 30 * 1024 * 1024; // 30 MB

const MIME_MAP: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".pdf": "application/pdf",
  ".txt": "text/plain",
  ".json": "application/json",
  ".md": "text/markdown",
};

function isImageByExtension(filePath: string): boolean {
  return IMAGE_EXTENSIONS.has(extname(filePath).toLowerCase());
}

function guessMimeType(filePath: string): string {
  return MIME_MAP[extname(filePath).toLowerCase()] ?? "application/octet-stream";
}

interface ResolvedAttachment {
  path: string;
  size: number;
  isImage: boolean;
  file_uuid?: string;
}

async function resolveAttachments(paths: string[]): Promise<ResolvedAttachment[]> {
  const resolved: ResolvedAttachment[] = [];
  for (const rawPath of paths) {
    const expanded = rawPath.startsWith("~")
      ? rawPath.replace(
          "~",
          process.env["USERPROFILE"] ?? process.env["HOME"] ?? "~",
        )
      : rawPath;
    const absPath = resolve(expanded);

    let fileStats: Awaited<ReturnType<typeof stat>>;
    try {
      fileStats = await stat(absPath);
    } catch {
      throw new Error(`Attachment not found or not accessible: ${absPath}`);
    }

    if (!fileStats.isFile()) {
      throw new Error(`Attachment is not a regular file: ${absPath}`);
    }

    const size = fileStats.size;
    const isImage = isImageByExtension(absPath);
    const attachment: ResolvedAttachment = { path: absPath, size, isImage };

    if (isBridgeModeActive() && size <= UPLOAD_SIZE_LIMIT) {
      const mimeType = guessMimeType(absPath);
      try {
        const uuid = await uploadAttachment(absPath, mimeType);
        if (uuid) attachment.file_uuid = uuid;
      } catch {
        // best-effort upload; continue without uuid
      }
    }

    resolved.push(attachment);
  }
  return resolved;
}

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const BriefToolInputSchema = z
  .object({
    message: z.string(),
    attachments: z.array(z.string()).optional(),
    status: z.enum(["normal", "proactive"]),
  })
  .strict();

type BriefToolInput = z.infer<typeof BriefToolInputSchema>;

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const SendUserMessageTool = buildTool<BriefToolInput, unknown>({
  name: "SendUserMessage",
  inputSchema: BriefToolInputSchema,

  isReadOnly: () => false,
  isEnabled: () => isKairosBriefModeActive(),
  maxResultSizeChars: 100_000,
  userFacingName: () => "",

  checkPermissions: async (_input, _context) => ({
    behavior: "allow" as const,
    updatedInput: _input,
  }),

  call: async (rawArgs: unknown, _context) => {
    const args = rawArgs as BriefToolInput;

    if (!isKairosBriefModeActive()) {
      throw new Error("SendUserMessage is not available outside KAIROS brief mode.");
    }

    const entitled = await getCachedEntitlement();
    if (!entitled) {
      throw new Error("KAIROS brief entitlement is not granted for this session.");
    }

    const resolvedAttachments =
      args.attachments && args.attachments.length > 0
        ? await resolveAttachments(args.attachments)
        : [];

    const sentAt = new Date().toISOString();

    return {
      data: {
        message: args.message,
        attachments: resolvedAttachments.length > 0 ? resolvedAttachments : undefined,
        sentAt,
        status: args.status,
      },
    };
  },

  description: () =>
    "Send a markdown message with optional file attachments to the user in brief/chat mode. Only available when KAIROS brief mode is active.",

  prompt: () =>
    "Use SendUserMessage to deliver results, notifications, or proactive updates when operating in brief/background mode. Set status='proactive' for spontaneous updates; 'normal' for direct responses.",

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
});
