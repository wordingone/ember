// Generic reactive store primitive and React bindings for AppState.
// The pure Store<T> (createStore, onChangeAppState) has no React dependency
// and is fully tested. The React hooks (useAppState, useSetAppState,
// useAppStateStore, AppStateProvider) are thin wrappers that require React at
// runtime; they are exported for TUI consumers.

import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
  createElement,
} from "react";
import type { AppState } from "./app-state.ts";

// ---- Pure store primitive ----

/** Generic reactive store. */
export interface Store<T> {
  /** Returns the current state snapshot. */
  getState: () => T;
  /** Applies an immutable update and synchronously notifies all subscribers. */
  setState: (updater: (current: T) => T) => void;
  /** Registers a change listener. Returns an unsubscribe function. */
  subscribe: (listener: (state: T) => void) => () => void;
  /** Removes all listeners and marks the store as destroyed. */
  destroy: () => void;
}

/**
 * Creates a reactive store initialized with `initialState`.
 * setState is synchronous: all subscribers are called before it returns.
 */
export function createStore<T>(initialState: T): Store<T> {
  let current: T = initialState;
  let destroyed = false;
  const listeners = new Set<(state: T) => void>();

  return {
    getState(): T {
      return current;
    },

    setState(updater: (current: T) => T): void {
      if (destroyed) return;
      current = updater(current);
      for (const listener of listeners) {
        listener(current);
      }
    },

    subscribe(listener: (state: T) => void): () => void {
      if (destroyed) return () => {};
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    destroy(): void {
      destroyed = true;
      listeners.clear();
    },
  };
}

/**
 * Registers a callback that fires when the selected slice of state changes
 * (shallow equality via ===).
 * Returns an unsubscribe function.
 */
export function onChangeAppState<T, V>(
  store: Store<T>,
  selector: (state: T) => V,
  callback: (newValue: V, prevValue: V) => void,
): () => void {
  let prev: V = selector(store.getState());

  return store.subscribe((state) => {
    const next = selector(state);
    if (next !== prev) {
      const old = prev;
      prev = next;
      callback(next, old);
    }
  });
}

// ---- React bindings (require React at runtime) ----

/** The React context that holds the AppState store instance. */
const AppStateContext = createContext<Store<AppState> | null>(null);

function getAppStateStore(ctx: Store<AppState> | null): Store<AppState> {
  if (ctx === null) {
    throw new Error("useAppState* hooks must be used within AppStateProvider");
  }
  return ctx;
}

/**
 * React context provider. Wraps the application tree and provides the AppState
 * store to all descendant components.
 * Required at the root of the TUI component tree.
 */
export function AppStateProvider({
  store,
  children,
}: {
  store: Store<AppState>;
  children: ReactNode;
}): ReactNode {
  return createElement(AppStateContext.Provider, { value: store }, children);
}

/**
 * React hook returning the current AppState.
 * Re-renders the component on every AppState change.
 */
export function useAppState(): AppState {
  const store = useContext(AppStateContext);
  const s = getAppStateStore(store);
  const [state, setState] = useState<AppState>(() => s.getState());

  useEffect(() => {
    // Sync in case state changed between render and effect
    setState(s.getState());
    return s.subscribe((next) => setState(next));
  }, [s]);

  return state;
}

/**
 * React hook returning the setState function from the AppState store.
 * Does NOT cause re-renders when the updater is called.
 */
export function useSetAppState(): (updater: (current: AppState) => AppState) => void {
  const store = useContext(AppStateContext);
  return getAppStateStore(store).setState.bind(getAppStateStore(store));
}

/**
 * React hook returning the raw Store<AppState> instance.
 * For advanced use cases needing both state and updater without subscribing to
 * all changes.
 */
export function useAppStateStore(): Store<AppState> {
  const store = useContext(AppStateContext);
  return getAppStateStore(store);
}
