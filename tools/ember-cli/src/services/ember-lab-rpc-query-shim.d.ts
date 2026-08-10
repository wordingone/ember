// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/ember-lab-rpc-query-shim.d.ts — ambient module declaration for the query-suffixed
// dynamic-import specifiers used by ember-lab-rpc-*-child.test.ts (e.g.
// "./ember-lab-rpc.ts?access-denied-regression"). Those child-process test files import
// ember-lab-rpc.ts with a unique `?<name>-regression` query string so Bun's module loader treats
// each import as a fresh, uncached module instance -- necessary because each child process calls
// `mock.module("node:net", ...)` first and then needs its OWN import of ember-lab-rpc.ts to
// re-resolve against the mock rather than a real "node:net" that some earlier import may have
// already cached. This is a real, working Bun runtime behavior (bun test passes with these
// imports); tsc's module resolver has no notion of query-string specifiers on a relative path and
// reports TS2307 ("Cannot find module") for every one of them.
//
// This is a resolution-only shim: it re-exports ember-lab-rpc.ts's real surface unchanged, so
// every one of these query-suffixed imports keeps full type-checking against the real
// `callEmberLab` signature -- nothing here loosens or fakes a type, it only tells tsc that a
// specifier matching this pattern points at the same module as the unsuffixed import.
declare module "./ember-lab-rpc.ts?*" {
  export {
    configuredEmberLabPipe,
    callEmberLab,
    identifyEmberLabRuntime,
    pingEmberLab,
    handshakeConfiguredEmberLab,
  } from "./ember-lab-rpc.ts";
  export type {
    EmberLabPingOptions,
    EmberLabRequestOptions,
    EmberLabRuntimeIdentity,
  } from "./ember-lab-rpc.ts";
}
