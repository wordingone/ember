// types/session-persistence-types.ts — types for session log entries.

export interface LogOption {
  date: string;
  messages: unknown[];
  fullPath: string;
  value: number;
  created: Date;
  modified: Date;
  firstPrompt: string;
  messageCount: number;
  fileSize: number;
  isSidechain: boolean;
  isLite: boolean;
  sessionId: string;
  projectPath: string;
}
