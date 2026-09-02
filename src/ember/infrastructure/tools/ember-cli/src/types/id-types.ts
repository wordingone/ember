// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// types/id-types.ts — branded ID types for agents and sessions.

export type AgentId = string & { readonly _brand: 'AgentId' };

export function asAgentId(s: string): AgentId {
  return s as AgentId;
}

export type SessionId = string & { readonly _brand: 'SessionId' };

export function asSessionId(s: string): SessionId {
  return s as SessionId;
}
