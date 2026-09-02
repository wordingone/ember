// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// #898 diagnostic carrier: the root ClockContext timer and the REPL liveness timer are
// independent one-second render clocks. This test exercises the real mounted App so the
// diagnostic arm can pause only the root clock without substituting a fake scheduler.
import { afterEach, describe, expect, test } from "bun:test";
import React, { useContext, useEffect } from "react";
import { App, ClockContext } from "./components.ts";
import { mountInk } from "./reconciler.ts";

const DISABLE_CLOCK_ENV = "EMBER_DIAGNOSTIC_DISABLE_CLOCK_CONTEXT_TICK";
const originalDisableClock = process.env[DISABLE_CLOCK_ENV];

afterEach(() => {
  if (originalDisableClock === undefined) delete process.env[DISABLE_CLOCK_ENV];
  else process.env[DISABLE_CLOCK_ENV] = originalDisableClock;
});

function ClockObserver({ onValue }: { onValue: (value: number) => void }): React.ReactElement {
  const { now } = useContext(ClockContext);
  useEffect(() => onValue(now), [now, onValue]);
  return React.createElement("text", null, String(now));
}

async function mountedClockValues(disabled: boolean): Promise<number[]> {
  if (disabled) process.env[DISABLE_CLOCK_ENV] = "1";
  else delete process.env[DISABLE_CLOCK_ENV];

  const values: number[] = [];
  const onValue = (value: number): void => { values.push(value); };
  const handle = mountInk(
    React.createElement(App, null, React.createElement(ClockObserver, { onValue })),
    {
      stream: { write: () => true },
      stdout: { columns: 80, rows: 24 },
    },
  );

  try {
    // Let mount effects flush, then cross one complete 1s clock interval with margin.
    await Bun.sleep(30);
    expect(values.length).toBeGreaterThanOrEqual(1);
    await Bun.sleep(1_200);
    return [...values];
  } finally {
    handle.unmount();
    await Bun.sleep(20);
  }
}

describe("App root ClockContext diagnostic arm (#898)", () => {
  test("the default mounted App advances ClockContext on its existing one-second cadence", async () => {
    const values = await mountedClockValues(false);
    expect(values.length).toBeGreaterThanOrEqual(2);
    expect(values.at(-1)).toBeGreaterThan(values[0]!);
  });

  test("the exact diagnostic flag pauses only the mounted App root clock", async () => {
    const values = await mountedClockValues(true);
    expect(values).toEqual([values[0]!]);
  });
});
