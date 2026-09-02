// services/syntax-highlight.ts — Synchronous ANSI syntax highlighting via highlight.js.
// Populates the shared highlightCache in markdown-and-code.ts on cache miss.
// Gate: EMBER_SYNTAX_HIGHLIGHT env var must be truthy to pay the highlight cost.

import hljs from "highlight.js";
import { highlightCache, hashPair } from "./highlight-cache.ts";

// ---------------------------------------------------------------------------
// ANSI SGR codes — terminator (reset) and per-token colour map
// ---------------------------------------------------------------------------

const RESET = "\x1b[0m";

const HLJS_CLASS_ANSI: Record<string, string> = {
  "hljs-keyword":     "\x1b[1;36m", // bold cyan
  "hljs-string":      "\x1b[33m",   // yellow
  "hljs-comment":     "\x1b[2;37m", // dim white
  "hljs-number":      "\x1b[35m",   // magenta
  "hljs-function":    "\x1b[34m",   // blue
  "hljs-title":       "\x1b[1;34m", // bold blue  (function/class names)
  "hljs-title function_": "\x1b[1;34m",
  "hljs-title class_":    "\x1b[1;32m", // bold green
  "hljs-built_in":    "\x1b[36m",   // cyan
  "hljs-type":        "\x1b[32m",   // green
  "hljs-attr":        "\x1b[34m",   // blue
  "hljs-literal":     "\x1b[35m",   // magenta
  "hljs-meta":        "\x1b[2m",    // dim
  "hljs-meta keyword": "\x1b[1;33m",
  "hljs-tag":         "\x1b[36m",   // cyan
  "hljs-name":        "\x1b[34m",   // blue
  "hljs-addition":    "\x1b[32m",   // green
  "hljs-deletion":    "\x1b[31m",   // red
  "hljs-operator":    "\x1b[33m",   // yellow
  "hljs-punctuation": "",           // terminal default
  "hljs-variable":    "",           // terminal default
  "hljs-params":      "",           // terminal default
  "hljs-subst":       "",           // terminal default
  "hljs-section":     "\x1b[1;33m", // bold yellow
};

// ---------------------------------------------------------------------------
// htmlToAnsi — convert hljs HTML output to ANSI-escaped string
// Handles nested spans correctly by re-applying parent colour on </span>.
// ---------------------------------------------------------------------------

export function htmlToAnsi(html: string): string {
  // Stack tracks the ANSI code for each open <span>, so closing one re-applies
  // the parent's colour rather than going all-the-way to RESET.
  const colourStack: string[] = [];
  let out = "";
  let i = 0;

  while (i < html.length) {
    if (html[i] !== "<" && html[i] !== "&") {
      out += html[i++];
      continue;
    }

    // HTML entity
    if (html[i] === "&") {
      const entity = html.slice(i).match(/^&([^;]{1,8});/);
      if (entity) {
        const decode: Record<string, string> = {
          lt: "<", gt: ">", amp: "&", quot: '"', "#39": "'", apos: "'",
        };
        out += decode[entity[1]!] ?? entity[0];
        i += entity[0].length;
        continue;
      }
      out += html[i++];
      continue;
    }

    // Opening <span class="...">
    const openSpan = html.slice(i).match(/^<span class="([^"]+)">/);
    if (openSpan) {
      const classes = (openSpan[1] ?? "").split(/\s+/);
      let ansi = "";
      for (const cls of classes) {
        const resolved = HLJS_CLASS_ANSI[cls];
        if (resolved !== undefined) { ansi = resolved; break; }
      }
      colourStack.push(ansi);
      if (ansi) out += ansi;
      i += openSpan[0].length;
      continue;
    }

    // Closing </span>
    if (html.slice(i, i + 7) === "</span>") {
      colourStack.pop();
      // Re-apply the nearest ancestor colour (or RESET if none).
      const parent = colourStack.length > 0 ? colourStack[colourStack.length - 1]! : "";
      out += parent || RESET;
      i += 7;
      continue;
    }

    // Any other tag — swallow it
    const endTag = html.indexOf(">", i);
    i = endTag >= 0 ? endTag + 1 : html.length;
  }

  // Close any unclosed spans
  if (colourStack.length > 0) out += RESET;
  return out;
}

// ---------------------------------------------------------------------------
// populateHighlight — run hljs and write the ANSI result into the shared cache.
// Returns the ANSI string (or plain code on failure / unknown language).
// ---------------------------------------------------------------------------

export function populateHighlight(language: string, code: string): string {
  const key = hashPair(language, code);

  // Fast path — already in cache
  const cached = highlightCache.get(key);
  if (cached !== undefined) return cached;

  let result: string;
  try {
    // hljs.getLanguage returns undefined for unknown language names.
    const supported = language ? hljs.getLanguage(language) : null;
    if (!supported) {
      // Auto-detect from the code when language is absent or unknown.
      const auto = hljs.highlightAuto(code, [
        "python", "typescript", "javascript", "bash", "sh",
        "json", "yaml", "toml", "rust", "go", "c", "cpp",
        "java", "css", "html", "xml", "sql", "markdown",
      ]);
      result = htmlToAnsi(auto.value) + RESET;
    } else {
      const out = hljs.highlight(code, { language, ignoreIllegals: true });
      result = htmlToAnsi(out.value) + RESET;
    }
  } catch {
    // Fallback: plain text, still cached so we don't retry
    result = code;
  }

  highlightCache.set(key, result);
  return result;
}
