// tools/builtin-tools.ts — Registry of all built-in tools.
// De-transpiled from bundle. Aggregates and exports all tool implementations.
// bundle=Y

import { AskUserQuestionTool } from "./ask-user-question.ts";
import { bashTool } from "./bash-tool.ts";
import { SendUserMessageTool } from "./brief-tool.ts";
import { editTool } from "./file-edit.ts";
import { readTool } from "./file-read.ts";
import { writeTool } from "./file-write.ts";
import { notebookEditTool } from "./notebook-edit.ts";
import { EnterPlanModeTool, ExitPlanModeTool } from "./plan-mode-tools.ts";
import { powerShellTool } from "./powershell-tool.ts";
import { CronCreateTool, CronDeleteTool, CronListTool } from "./schedule-cron.ts";
import { globTool, grepTool } from "./search-tools.ts";
import { TodoWriteTool } from "./todo-write.ts";
import { EnterWorktreeTool, ExitWorktreeTool } from "./worktree-tools.ts";
import { RemoteTriggerTool } from "./remote-trigger.ts";
import { GOAL_TOOLS } from "./goal-tools.ts";

// Registry of all built-in tools, in bundle-defined order
export const BUILTIN_TOOLS = [
  bashTool,
  readTool,
  editTool,
  writeTool,
  globTool,
  grepTool,
  notebookEditTool,
  powerShellTool,
  AskUserQuestionTool,
  EnterPlanModeTool,
  ExitPlanModeTool,
  CronCreateTool,
  CronDeleteTool,
  CronListTool,
  TodoWriteTool,
  EnterWorktreeTool,
  ExitWorktreeTool,
  SendUserMessageTool,
  RemoteTriggerTool,
  ...GOAL_TOOLS,
];
