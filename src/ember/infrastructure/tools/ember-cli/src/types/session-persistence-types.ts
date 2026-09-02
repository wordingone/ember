// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
