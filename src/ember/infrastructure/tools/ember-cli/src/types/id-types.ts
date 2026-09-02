// types/id-types.ts — branded ID types for agents and sessions.

export type AgentId = string & { readonly _brand: 'AgentId' };

export function asAgentId(s: string): AgentId {
  return s as AgentId;
}

export type SessionId = string & { readonly _brand: 'SessionId' };

export function asSessionId(s: string): SessionId {
  return s as SessionId;
}
