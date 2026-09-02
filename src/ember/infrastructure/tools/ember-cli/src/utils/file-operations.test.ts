// utils/file-operations.test.ts — issue #475: stripBom is the fix that makes the
// planned-outage marker (and any other PS-written state file) tolerant of Windows
// PowerShell 5.1's `-Encoding utf8` BOM. Pure/no-fs test; the rest of this module is
// already exercised indirectly through its many callers.

import { describe, it, expect } from "bun:test";
import { stripBom } from "./file-operations.ts";

describe("stripBom", () => {
  it("strips a leading UTF-8 BOM (U+FEFF)", () => {
    const withBom = "﻿{\"a\":1}";
    expect(stripBom(withBom)).toBe('{"a":1}');
  });

  it("is a no-op on text without a BOM", () => {
    const clean = '{"a":1}';
    expect(stripBom(clean)).toBe(clean);
  });

  it("is a no-op on an empty string (never throws on charCodeAt(0) of empty)", () => {
    expect(stripBom("")).toBe("");
  });

  it("is idempotent — stripping twice equals stripping once", () => {
    const withBom = "﻿hello";
    expect(stripBom(stripBom(withBom))).toBe(stripBom(withBom));
  });

  it("only strips the FIRST character even if content elsewhere resembles a BOM", () => {
    const text = "a﻿b";
    expect(stripBom(text)).toBe(text); // BOM isn't leading, so untouched
  });
});
