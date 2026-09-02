// notification-system.ts — notification, mailbox, and voice state factories
// plus React context objects for each subsystem.

import { createContext } from "react";

// ---------------------------------------------------------------------------
// Notification types
// ---------------------------------------------------------------------------

export type NotificationType = "info" | "success" | "warning" | "error";

export interface NotificationAction {
  label:   string;
  onClick: () => void;
}

export interface NotificationInput {
  type:       NotificationType;
  message:    string;
  durationMs?: number;
  action?:     NotificationAction;
}

export interface Notification extends NotificationInput {
  id:         string;
  createdAt:  number;
  isExpiring: boolean;
}

// ---------------------------------------------------------------------------
// NotificationsState
// ---------------------------------------------------------------------------

export interface NotificationsState {
  notifications:      Notification[];
  addNotification:    (input: NotificationInput) => string;
  removeNotification: (id: string) => void;
  clearAll:           () => void;
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createNotificationsState(): NotificationsState {
  const notifications: Notification[] = [];

  const state: NotificationsState = {
    get notifications() {
      return notifications;
    },

    addNotification(input: NotificationInput): string {
      const id   = generateId();
      const item: Notification = {
        ...input,
        id,
        createdAt:  Date.now(),
        isExpiring: false,
      };
      // newest first
      notifications.unshift(item);
      return id;
    },

    removeNotification(id: string): void {
      const idx = notifications.findIndex((n) => n.id === id);
      if (idx !== -1) notifications.splice(idx, 1);
    },

    clearAll(): void {
      notifications.length = 0;
    },
  };

  return state;
}

// ---------------------------------------------------------------------------
// MailboxState
// ---------------------------------------------------------------------------

export interface MailboxOptions {
  identity?: string | null;
}

export interface MailboxState {
  isConnected:        boolean;
  unreadCount:        number;
  lastCheckedAt:      Date | null;
  identity:           string | null;
  _setUnreadCount:    (n: number) => void;
  _setConnected:      (v: boolean) => void;
}

export function createMailboxState(opts: MailboxOptions = {}): MailboxState {
  let isConnected   = false;
  let unreadCount   = 0;
  const lastCheckedAt: Date | null = null;
  const identity    = opts.identity ?? null;

  const state: MailboxState = {
    get isConnected() { return isConnected; },
    get unreadCount() { return unreadCount; },
    get lastCheckedAt() { return lastCheckedAt; },
    get identity() { return identity; },

    _setUnreadCount(n: number): void {
      unreadCount = n;
    },
    _setConnected(v: boolean): void {
      isConnected = v;
    },
  };

  return state;
}

// ---------------------------------------------------------------------------
// VoiceState
// ---------------------------------------------------------------------------

export interface VoiceOptions {
  isSupported?: boolean;
}

export interface VoiceState {
  isSupported:  boolean;
  isListening:  boolean;
  transcript:   string;
}

export function createVoiceState(opts: VoiceOptions = {}): VoiceState {
  let isListening = false;
  let transcript  = "";

  const state: VoiceState = {
    get isSupported() { return opts.isSupported ?? false; },
    get isListening() { return isListening; },
    get transcript()  { return transcript; },
  };

  // Keep TS strict happy — assign via closure to avoid unused-var lint.
  void isListening;
  void transcript;

  // These are set but accessed via getter above.
  // Suppress unused refs by assigning (void pattern avoids bare-any).
  isListening = isListening;
  transcript  = transcript;

  return state;
}

// ---------------------------------------------------------------------------
// React Contexts (structural — value typing uses unknown for test isolation)
// ---------------------------------------------------------------------------

export const NotificationsContext = createContext<NotificationsState | null>(null);
export const MailboxContext        = createContext<MailboxState | null>(null);
export const VoiceContext          = createContext<VoiceState | null>(null);
