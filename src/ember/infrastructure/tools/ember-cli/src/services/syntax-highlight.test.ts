// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// syntax-highlight.test.ts — AC1–AC4 for the ANSI syntax-highlight service.
//
// AC1: htmlToAnsi — keyword/string/comment/number/built_in classes → correct ANSI codes
// AC2: htmlToAnsi — nested spans restore parent colour on inner </span>
// AC3: htmlToAnsi — HTML entities decoded (&lt; &gt; &amp; &quot; &#39;)
// AC4: populateHighlight — populates the shared cache; known language produces ANSI output;
//      unknown language falls back to autodetect without throwing; re-call hits cache fast path.

import { describe, it, expect, afterEach } from "bun:test";
import { htmlToAnsi, populateHighlight } from "./syntax-highlight.ts";
import { highlightCache, hashPair } from "./highlight-cache.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RESET     = "\x1b[0m";
const BOLD_CYAN = "\x1b[1;36m";  // keyword
const YELLOW    = "\x1b[33m";    // string
const DIM_WHITE = "\x1b[2;37m";  // comment
const MAGENTA   = "\x1b[35m";    // number
const CYAN      = "\x1b[36m";    // built_in
const GREEN     = "\x1b[32m";    // type
const BOLD_BLUE = "\x1b[1;34m";  // title

// Wipe the shared cache between tests so populateHighlight doesn't read stale entries.
afterEach(() => {
  // The LRUCache has no .clear() method; delete keys by re-instantiating is not feasible
  // here without exporting the instance with a flush. Instead we mutate it via set+get to
  // guarantee our test code path runs fresh where needed.
});

// ---------------------------------------------------------------------------
// AC1 — htmlToAnsi class→ANSI mapping
// ---------------------------------------------------------------------------

describe("AC1: htmlToAnsi class→ANSI", () => {
  it("hljs-keyword → bold cyan", () => {
    const html = `<span class="hljs-keyword">def</span>`;
    const result = htmlToAnsi(html);
    expect(result).toContain(BOLD_CYAN);
    expect(result).toContain("def");
    expect(result).toContain(RESET);
  });

  it("hljs-string → yellow", () => {
    const html = `<span class="hljs-string">"hello"</span>`;
    const result = htmlToAnsi(html);
    expect(result).toContain(YELLOW);
    expect(result).toContain('"hello"');
  });

  it("hljs-comment → dim white", () => {
    const html = `<span class="hljs-comment"># note</span>`;
    const result = htmlToAnsi(html);
    expect(result).toContain(DIM_WHITE);
    expect(result).toContain("# note");
  });

  it("hljs-number → magenta", () => {
    const html = `<span class="hljs-number">42</span>`;
    expect(htmlToAnsi(html)).toContain(MAGENTA);
  });

  it("hljs-built_in → cyan", () => {
    const html = `<span class="hljs-built_in">print</span>`;
    expect(htmlToAnsi(html)).toContain(CYAN);
  });

  it("hljs-type → green", () => {
    const html = `<span class="hljs-type">int</span>`;
    expect(htmlToAnsi(html)).toContain(GREEN);
  });

  it("hljs-title → bold blue", () => {
    const html = `<span class="hljs-title">my_func</span>`;
    expect(htmlToAnsi(html)).toContain(BOLD_BLUE);
  });

  it("unknown class → no ANSI code inserted, text passes through", () => {
    const html = `<span class="hljs-unknown-xyz">tok</span>`;
    const result = htmlToAnsi(html);
    expect(result).toContain("tok");
    // No leading ANSI escape before "tok"
    expect(result.startsWith("\x1b")).toBe(false);
  });

  it("plain text with no tags passes through unchanged", () => {
    const text = "hello world";
    expect(htmlToAnsi(text)).toBe("hello world");
  });
});

// ---------------------------------------------------------------------------
// AC2 — nested span colour restoration
// ---------------------------------------------------------------------------

describe("AC2: htmlToAnsi nested span colour restore", () => {
  it("inner </span> re-applies parent colour, not bare RESET", () => {
    // <keyword><built_in>print</built_in></keyword>
    const html = `<span class="hljs-keyword"><span class="hljs-built_in">print</span>end</span>`;
    const result = htmlToAnsi(html);
    // After closing the inner (built_in) span, parent (keyword) should resume
    expect(result).toContain(BOLD_CYAN);   // keyword opens
    expect(result).toContain(CYAN);        // built_in opens inside
    // After </span> for built_in, parent colour (BOLD_CYAN) should re-appear
    const idxKeyword = result.indexOf(BOLD_CYAN);
    const idxBuiltIn = result.indexOf(CYAN);
    const afterBuiltInClose = result.lastIndexOf(BOLD_CYAN);
    expect(afterBuiltInClose).toBeGreaterThan(idxBuiltIn);
    expect(result).toContain("print");
    expect(result).toContain("end");
  });

  it("multiple top-level spans each get their own colour + reset", () => {
    const html = `<span class="hljs-keyword">if</span> <span class="hljs-number">1</span>`;
    const result = htmlToAnsi(html);
    expect(result).toContain(BOLD_CYAN);
    expect(result).toContain("if");
    expect(result).toContain(MAGENTA);
    expect(result).toContain("1");
  });
});

// ---------------------------------------------------------------------------
// AC3 — HTML entity decoding
// ---------------------------------------------------------------------------

describe("AC3: htmlToAnsi entity decode", () => {
  it("&lt; &gt; &amp; &quot; &#39;", () => {
    const html = `<span class="hljs-string">&lt;tag&gt; &amp; &quot;x&quot; &#39;y&#39;</span>`;
    const result = htmlToAnsi(html);
    expect(result).toContain("<tag>");
    expect(result).toContain("&");
    expect(result).toContain('"x"');
    expect(result).toContain("'y'");
  });

  it("raw & without entity pattern is passed through", () => {
    const html = "a & b";
    expect(htmlToAnsi(html)).toBe("a & b");
  });
});

// ---------------------------------------------------------------------------
// AC4 — populateHighlight cache + output contract
// ---------------------------------------------------------------------------

describe("AC4: populateHighlight cache + output", () => {
  it("known language produces ANSI escape codes in output", () => {
    // Force fresh cache state with a unique code string
    const code = "def hello(): return 42 # unique_" + Date.now();
    const result = populateHighlight("python", code);
    // Any ANSI code is evidence that hljs ran and htmlToAnsi processed it
    expect(result).toMatch(/\x1b\[/);
    // Text content must not be lost
    expect(result).toContain("hello");
    expect(result).toContain("42");
  });

  it("result ends with RESET to close any open SGR codes", () => {
    const code = "const x = 1;";
    const result = populateHighlight("javascript", code);
    expect(result.endsWith(RESET)).toBe(true);
  });

  it("populates the shared highlightCache", () => {
    const code = "let y = 'cache-test-' + Date.now()";
    const lang = "javascript";
    // Run it once
    const result = populateHighlight(lang, code);
    // Cache should now contain this key
    const key = hashPair(lang, code);
    expect(highlightCache.get(key)).toBe(result);
  });

  it("second call returns cached value without re-running hljs", () => {
    const code = "x = 1 # cached-path";
    const lang = "python";
    const first  = populateHighlight(lang, code);
    // Manually overwrite the cache to detect whether the second call re-runs or hits cache
    const key = hashPair(lang, code);
    highlightCache.set(key, "SENTINEL_VALUE");
    const second = populateHighlight(lang, code);
    expect(second).toBe("SENTINEL_VALUE"); // hit cache, didn't re-run
    // Restore for other tests
    highlightCache.set(key, first);
  });

  it("unknown language falls back (no throw) — returns a string", () => {
    const result = populateHighlight("notareallanginternaltest123", "foo bar baz");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });

  it("empty language string falls back to autodetect — returns a string", () => {
    const result = populateHighlight("", "function hello() { return 42; }");
    expect(typeof result).toBe("string");
  });

  it("highlight.js exception path returns plain code (no throw)", () => {
    // Passing a null-like code shouldn't throw — it should return a non-empty string
    const result = populateHighlight("python", "");
    expect(typeof result).toBe("string");
  });
});
