// Tests for state-store — covers AC1–AC5 plus behavioral contract.
import { test, expect, describe, mock } from "bun:test";
import { createStore, onChangeAppState } from "./state-store.ts";

describe("createStore", () => {
  test("AC5: first getState() returns exact initial reference", () => {
    const initial = { count: 0 };
    const store = createStore(initial);
    expect(store.getState()).toBe(initial);
  });

  test("AC1: setState calls updater synchronously and notifies subscribers before returning", () => {
    const store = createStore({ value: 0 });
    const log: number[] = [];

    store.subscribe((s) => log.push(s.value));
    store.setState((s) => ({ ...s, value: 1 }));

    // By the time setState returns, the subscriber has already fired
    expect(log).toEqual([1]);
    expect(store.getState().value).toBe(1);
  });

  test("AC1: multiple setState calls each notify subscribers synchronously", () => {
    const store = createStore({ n: 0 });
    const received: number[] = [];
    store.subscribe((s) => received.push(s.n));

    store.setState((s) => ({ ...s, n: 1 }));
    store.setState((s) => ({ ...s, n: 2 }));
    store.setState((s) => ({ ...s, n: 3 }));

    expect(received).toEqual([1, 2, 3]);
  });

  test("AC2: subscribe returns an unsubscribe function that removes the listener", () => {
    const store = createStore({ x: 0 });
    const calls: number[] = [];
    const unsub = store.subscribe((s) => calls.push(s.x));

    store.setState((s) => ({ ...s, x: 1 }));
    unsub(); // remove listener
    store.setState((s) => ({ ...s, x: 2 }));

    // Only the first setState should have fired after subscribe
    expect(calls).toEqual([1]);
  });

  test("multiple subscribers all receive updates", () => {
    const store = createStore({ v: 0 });
    const a: number[] = [];
    const b: number[] = [];
    store.subscribe((s) => a.push(s.v));
    store.subscribe((s) => b.push(s.v));

    store.setState((s) => ({ ...s, v: 7 }));
    expect(a).toEqual([7]);
    expect(b).toEqual([7]);
  });

  test("destroy removes all listeners", () => {
    const store = createStore({ z: 0 });
    const calls: number[] = [];
    store.subscribe((s) => calls.push(s.z));
    store.destroy();
    store.setState((s) => ({ ...s, z: 99 }));
    expect(calls).toHaveLength(0);
  });

  test("updater must not mutate argument — state remains immutable by contract", () => {
    const store = createStore({ arr: [1, 2, 3] });
    const original = store.getState().arr;
    store.setState((s) => ({ ...s, arr: [...s.arr, 4] }));
    // Original array reference unchanged
    expect(store.getState().arr).not.toBe(original);
    expect(original).toEqual([1, 2, 3]);
  });
});

describe("onChangeAppState", () => {
  test("AC4: only fires when selected slice changes", () => {
    const store = createStore({ isLoading: false, messages: [] as string[] });
    const calls: boolean[] = [];

    onChangeAppState(store, (s) => s.isLoading, (v) => calls.push(v as boolean));

    // Change an unrelated field
    store.setState((s) => ({ ...s, messages: ["hello"] }));
    expect(calls).toHaveLength(0);

    // Change the watched field
    store.setState((s) => ({ ...s, isLoading: true }));
    expect(calls).toEqual([true]);
  });

  test("fires with newValue and prevValue", () => {
    const store = createStore({ count: 0 });
    const changes: Array<[unknown, unknown]> = [];

    onChangeAppState(store, (s) => s.count, (nv, pv) => changes.push([nv, pv]));
    store.setState((s) => ({ ...s, count: 5 }));

    expect(changes).toEqual([[5, 0]]);
  });

  test("uses shallow equality (===) — same reference suppresses callback", () => {
    const obj = { x: 1 };
    const store = createStore({ data: obj });
    const calls: unknown[] = [];

    onChangeAppState(store, (s) => s.data, (v) => calls.push(v));
    // setState but same object reference
    store.setState((s) => ({ ...s, data: s.data }));
    expect(calls).toHaveLength(0);

    // New reference fires
    store.setState((s) => ({ ...s, data: { x: 1 } }));
    expect(calls).toHaveLength(1);
  });

  test("returns unsubscribe function", () => {
    const store = createStore({ n: 0 });
    const calls: unknown[] = [];
    const unsub = onChangeAppState(store, (s) => s.n, (v) => calls.push(v));

    store.setState((s) => ({ ...s, n: 1 }));
    unsub();
    store.setState((s) => ({ ...s, n: 2 }));

    expect(calls).toEqual([1]);
  });
});
