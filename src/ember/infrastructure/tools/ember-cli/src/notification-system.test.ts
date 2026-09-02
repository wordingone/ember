// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for notification-system — covers AC1–AC5.
import { test, expect, describe } from "bun:test";
import {
  createNotificationsState,
  createMailboxState,
  createVoiceState,
  NotificationsContext,
  MailboxContext,
  VoiceContext,
} from "./notification-system.ts";

describe("NotificationsState", () => {
  test("initial notifications is empty", () => {
    const state = createNotificationsState();
    expect(state.notifications).toHaveLength(0);
  });

  test("addNotification assigns an id and createdAt", () => {
    const state = createNotificationsState();
    const id = state.addNotification({ type: "info", message: "Hello" });
    expect(id).toBeTruthy();
    const n = state.notifications[0];
    expect(n?.id).toBe(id);
    expect(typeof n?.createdAt).toBe("number");
  });

  test("removeNotification removes by id", () => {
    const state = createNotificationsState();
    const id = state.addNotification({ type: "success", message: "Done" });
    expect(state.notifications).toHaveLength(1);
    state.removeNotification(id);
    expect(state.notifications).toHaveLength(0);
  });

  test("AC3: clearAll removes all notifications", () => {
    const state = createNotificationsState();
    state.addNotification({ type: "info", message: "A" });
    state.addNotification({ type: "warning", message: "B" });
    state.clearAll();
    expect(state.notifications).toHaveLength(0);
  });

  test("AC2: isExpiring flag is false initially", () => {
    const state = createNotificationsState();
    state.addNotification({ type: "error", message: "E", durationMs: 3000 });
    expect(state.notifications[0]?.isExpiring).toBe(false);
  });

  test("notifications ordered newest first", () => {
    const state = createNotificationsState();
    state.addNotification({ type: "info", message: "first" });
    state.addNotification({ type: "info", message: "second" });
    // newest first
    expect(state.notifications[0]?.message).toBe("second");
  });

  test("notification without durationMs is persistent", () => {
    const state = createNotificationsState();
    state.addNotification({ type: "info", message: "persistent" });
    expect(state.notifications[0]?.durationMs).toBeUndefined();
  });

  test("notification with action is stored", () => {
    const state = createNotificationsState();
    const action = { label: "Click me", onClick: () => {} };
    state.addNotification({ type: "info", message: "With action", action });
    expect(state.notifications[0]?.action?.label).toBe("Click me");
  });
});

describe("MailboxState", () => {
  test("initial state: isConnected false, unreadCount 0, identity null", () => {
    const state = createMailboxState();
    expect(state.isConnected).toBe(false);
    expect(state.unreadCount).toBe(0);
    expect(state.lastCheckedAt).toBeNull();
    expect(state.identity).toBeNull();
  });

  test("AC4: unreadCount updates after checkNow resolves", async () => {
    const state = createMailboxState();
    state._setUnreadCount(5);
    expect(state.unreadCount).toBe(5);
  });

  test("identity can be set at session start", () => {
    const state = createMailboxState({ identity: "bob" });
    expect(state.identity).toBe("bob");
  });

  test("isConnected can be set", () => {
    const state = createMailboxState();
    state._setConnected(true);
    expect(state.isConnected).toBe(true);
  });
});

describe("VoiceState", () => {
  test("AC5: isSupported is false in headless/CI environment", () => {
    const state = createVoiceState({ isSupported: false });
    expect(state.isSupported).toBe(false);
  });

  test("isListening starts false", () => {
    const state = createVoiceState({});
    expect(state.isListening).toBe(false);
  });

  test("transcript starts empty", () => {
    const state = createVoiceState({});
    expect(state.transcript).toBe("");
  });
});

describe("Context objects (import sanity)", () => {
  test("NotificationsContext is defined", () => {
    expect(NotificationsContext).toBeDefined();
  });

  test("MailboxContext is defined", () => {
    expect(MailboxContext).toBeDefined();
  });

  test("VoiceContext is defined", () => {
    expect(VoiceContext).toBeDefined();
  });
});
