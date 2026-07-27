// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { expect, test } from "bun:test";
import React from "react";

import { _deliverKeyEvent, useInput } from "./hooks.ts";
import { mountInk } from "./reconciler.ts";

test("unmount synchronously removes the root's global keyboard handlers", () => {
  let calls = 0;

  function Probe(): React.ReactElement {
    useInput(() => {
      calls += 1;
    });
    return React.createElement(React.Fragment, null);
  }

  const handle = mountInk(React.createElement(Probe), {
    stream: { write() {} },
    stdout: { columns: 80, rows: 24 },
  });

  _deliverKeyEvent("x", {});
  expect(calls).toBe(1);

  handle.unmount();
  _deliverKeyEvent("x", {});
  expect(calls).toBe(1);
});
