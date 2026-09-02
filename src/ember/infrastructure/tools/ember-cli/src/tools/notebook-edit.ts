// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/notebook-edit.ts — NotebookEdit tool: replace/insert/delete Jupyter cells.
// De-transpiled from bundle (lines 305898–306150). Operates on .ipynb JSON files.
// bundle=Y

import { readFile, writeFile } from "fs/promises";
import { isAbsolute } from "path";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Notebook types
// ---------------------------------------------------------------------------

interface NotebookCell {
  id: string;
  cell_type: "code" | "markdown" | string;
  source: string | string[];
  metadata: Record<string, unknown>;
  outputs?: unknown[];
  execution_count?: number | null;
}

interface Notebook {
  cells: NotebookCell[];
  metadata?: {
    kernelspec?: { language?: string };
    language_info?: { name?: string };
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateCellId(): string {
  return "cell-" + Math.random().toString(36).slice(2, 10);
}

function cellSourceToString(source: string | string[]): string {
  return Array.isArray(source) ? source.join("") : source;
}

function isDenied3(filePath: string, ctx: ToolUseContext): boolean {
  const state = ctx.getAppState() as Record<string, unknown>;
  const denyPaths = (state["denyPaths"] as string[] | undefined) ?? [];
  return denyPaths.some(
    (d) => filePath === d || filePath.startsWith(d + "/") || filePath.startsWith(d + "\\"),
  );
}

function getLanguage(nb: Notebook): string {
  return (
    nb.metadata?.kernelspec?.language ??
    nb.metadata?.language_info?.name ??
    "unknown"
  );
}

// ---------------------------------------------------------------------------
// Public output type
// ---------------------------------------------------------------------------

export interface NotebookEditOutput {
  new_source: string;
  cell_id?: string;
  cell_type: string;
  language: string;
  edit_mode: string;
  notebook_path: string;
  original_file: string;
  updated_file: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// Core edit implementation
// ---------------------------------------------------------------------------

async function performEdit(
  input: {
    notebook_path: string;
    cell_id?: string;
    new_source: string;
    cell_type?: "code" | "markdown";
    edit_mode?: "replace" | "insert" | "delete";
  },
  ctx: ToolUseContext,
): Promise<NotebookEditOutput> {
  const { notebook_path, cell_id, new_source } = input;
  const editMode = input.edit_mode ?? "replace";
  const requestedCellType = input.cell_type;

  if (!isAbsolute(notebook_path)) {
    return {
      new_source: "",
      cell_type: "code",
      language: "unknown",
      edit_mode: editMode,
      error: `Path must be absolute: ${notebook_path}`,
      notebook_path,
      original_file: "",
      updated_file: "",
    };
  }

  let originalFileContent: string;
  try {
    originalFileContent = await readFile(notebook_path, "utf-8");
  } catch (e) {
    return {
      new_source: "",
      cell_type: "code",
      language: "unknown",
      edit_mode: editMode,
      error: `Failed to read notebook: ${String(e)}`,
      notebook_path,
      original_file: "",
      updated_file: "",
    };
  }

  let nb: Notebook;
  try {
    nb = JSON.parse(originalFileContent) as Notebook;
    if (!nb.cells || !Array.isArray(nb.cells))
      throw new Error("Invalid notebook: no cells array");
  } catch (e) {
    return {
      new_source: "",
      cell_type: "code",
      language: "unknown",
      edit_mode: editMode,
      error: `Invalid notebook JSON: ${String(e)}`,
      notebook_path,
      original_file: originalFileContent,
      updated_file: "",
    };
  }

  const language = getLanguage(nb);

  // --- replace ---
  if (editMode === "replace") {
    if (!cell_id) {
      return {
        new_source: "",
        cell_type: "code",
        language,
        edit_mode: editMode,
        error: "cell_id is required for replace operation",
        notebook_path,
        original_file: originalFileContent,
        updated_file: "",
      };
    }
    const cellIdx = nb.cells.findIndex((c) => c.id === cell_id);
    if (cellIdx < 0) {
      return {
        new_source: "",
        cell_type: "code",
        language,
        edit_mode: editMode,
        error: `Cell not found: ${cell_id}`,
        notebook_path,
        original_file: originalFileContent,
        updated_file: "",
      };
    }
    const cell = nb.cells[cellIdx]!;
    const originalType = cell.cell_type;
    nb.cells[cellIdx] = {
      ...cell,
      source: new_source,
      cell_type: requestedCellType ?? originalType,
    };
    const updatedFileContent = JSON.stringify(nb, null, 1);
    await writeFile(notebook_path, updatedFileContent, "utf-8");
    return {
      new_source,
      cell_id,
      cell_type: requestedCellType ?? originalType,
      language,
      edit_mode: editMode,
      notebook_path,
      original_file: originalFileContent,
      updated_file: updatedFileContent,
    };
  }

  // --- insert ---
  if (editMode === "insert") {
    const newCellType = requestedCellType ?? "code";
    const newCell: NotebookCell = {
      id: generateCellId(),
      cell_type: newCellType,
      source: new_source,
      metadata: {},
      ...(newCellType === "code" ? { outputs: [], execution_count: null } : {}),
    };
    if (cell_id) {
      const idx = nb.cells.findIndex((c) => c.id === cell_id);
      if (idx < 0) {
        return {
          new_source: "",
          cell_type: newCellType,
          language,
          edit_mode: editMode,
          error: `Cell not found: ${cell_id}`,
          notebook_path,
          original_file: originalFileContent,
          updated_file: "",
        };
      }
      nb.cells.splice(idx + 1, 0, newCell);
    } else {
      nb.cells.unshift(newCell);
    }
    const updatedFileContent = JSON.stringify(nb, null, 1);
    await writeFile(notebook_path, updatedFileContent, "utf-8");
    return {
      new_source,
      cell_id: newCell.id,
      cell_type: newCellType,
      language,
      edit_mode: editMode,
      notebook_path,
      original_file: originalFileContent,
      updated_file: updatedFileContent,
    };
  }

  // --- delete ---
  if (editMode === "delete") {
    if (!cell_id) {
      return {
        new_source: "",
        cell_type: "code",
        language,
        edit_mode: editMode,
        error: "cell_id is required for delete operation",
        notebook_path,
        original_file: originalFileContent,
        updated_file: "",
      };
    }
    const idx = nb.cells.findIndex((c) => c.id === cell_id);
    if (idx < 0) {
      return {
        new_source: "",
        cell_type: "code",
        language,
        edit_mode: editMode,
        error: `Cell not found: ${cell_id}`,
        notebook_path,
        original_file: originalFileContent,
        updated_file: "",
      };
    }
    const deletedCell = nb.cells[idx]!;
    nb.cells.splice(idx, 1);
    const updatedFileContent = JSON.stringify(nb, null, 1);
    await writeFile(notebook_path, updatedFileContent, "utf-8");
    return {
      new_source: cellSourceToString(deletedCell.source),
      cell_id,
      cell_type: deletedCell.cell_type,
      language,
      edit_mode: editMode,
      notebook_path,
      original_file: originalFileContent,
      updated_file: updatedFileContent,
    };
  }

  // --- unknown mode ---
  return {
    new_source: "",
    cell_type: "code",
    language,
    edit_mode: editMode,
    error: `Unknown edit_mode: ${editMode}`,
    notebook_path,
    original_file: originalFileContent,
    updated_file: "",
  };
}

// ---------------------------------------------------------------------------
// Schema and input type
// ---------------------------------------------------------------------------

const NotebookEditInputSchema = z.object({
  notebook_path: z.string(),
  cell_id: z.string().optional(),
  new_source: z.string(),
  cell_type: z.enum(["code", "markdown"]).optional(),
  edit_mode: z.enum(["replace", "insert", "delete"]).optional().default("replace"),
});

export type NotebookEditInput = z.infer<typeof NotebookEditInputSchema>;

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const notebookEditTool = Object.assign(
  buildTool<NotebookEditInput, NotebookEditOutput>({
    name: "NotebookEdit",

    inputSchema: NotebookEditInputSchema,

    isReadOnly: () => false,
    isDestructive: () => false,
    isConcurrencySafe: () => false,

    maxResultSizeChars: 1e5,

    description: (_input?: NotebookEditInput, _opts?) =>
      "Replace, insert, or delete a single cell in a Jupyter notebook (.ipynb file).",

    prompt: (_opts?) => `## NotebookEdit tool
Replaces, inserts, or deletes a single cell in a Jupyter notebook (.ipynb file).
- edit_mode: 'replace' (default) — updates cell source; requires cell_id.
- edit_mode: 'insert' — adds new cell after cell_id, or at beginning if cell_id omitted; requires cell_type.
- edit_mode: 'delete' — removes the cell; requires cell_id.
- new_source: required for all modes.
- Always read the notebook with Read before editing.
- notebook_path must be an absolute path.`,

    checkPermissions: async (input: NotebookEditInput, ctx: ToolUseContext) => {
      if (isDenied3(input.notebook_path, ctx)) {
        return { behavior: "deny" as const, updatedInput: input, message: "Denied by session rules" };
      }
      return { behavior: "allow" as const, updatedInput: input };
    },

    call: async (args: NotebookEditInput, ctx: ToolUseContext) => {
      const data = await performEdit(args, ctx);
      return { data };
    },

    mapToolResultToToolResultBlockParam: (content: NotebookEditOutput, toolUseId: string) => ({
      type: "tool_result" as const,
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
      ...(content.error !== undefined ? { is_error: true } : {}),
    }),

    toAutoClassifierInput: (input?: NotebookEditInput) => input?.notebook_path ?? "",
  }),
  { searchHint: "edit Jupyter notebook cells (.ipynb)" } as const,
);
