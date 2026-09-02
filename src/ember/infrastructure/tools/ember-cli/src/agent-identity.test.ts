// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for agent-identity — verifies all constants match spec exactly.
import { test, expect, describe } from "bun:test";
import {
  PRODUCT_NAME,
  CLI_BINARY_WIN,
  CLI_BINARY_UNIX,
  CONFIG_DIR_NAME,
  ACTIVE_BETA_FLAGS,
  VERSION,
  PORT_FALLBACK,
} from "./agent-identity.ts";

describe("agent-identity — spec values", () => {
  test("PRODUCT_NAME is 'ember'", () => {
    expect(PRODUCT_NAME).toBe("ember");
  });

  test("CLI_BINARY_WIN is 'ember.exe'", () => {
    expect(CLI_BINARY_WIN).toBe("ember.exe");
  });

  test("CLI_BINARY_UNIX is 'ember'", () => {
    expect(CLI_BINARY_UNIX).toBe("ember");
  });

  test("CONFIG_DIR_NAME is '.ember'", () => {
    expect(CONFIG_DIR_NAME).toBe(".ember");
  });

  test("VERSION is '0.1.0'", () => {
    expect(VERSION).toBe("0.1.0");
  });

  test("PORT_FALLBACK is 20,000", () => {
    expect(PORT_FALLBACK).toBe(20_000);
  });

  describe("ACTIVE_BETA_FLAGS", () => {
    // W2-B: emptied — local llama-server does not use provider beta headers.
    test("is empty in local-only mode (W2-B)", () => {
      expect(ACTIVE_BETA_FLAGS).toHaveLength(0);
    });
  });
});
