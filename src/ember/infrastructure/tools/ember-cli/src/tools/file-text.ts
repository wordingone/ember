// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// tools/file-text.ts — small helpers shared by Read, Write and Edit (blind-test findings #2379):
//   FO-34  UTF-16 text (PowerShell output, Notepad "Unicode") is text, not "binary"
//   FO-22  a path outside the working directory needs its own approval
//   FO-43  a file name Windows rejects is reported as an invalid name, not as ENOENT
// Pure functions, no tool wiring, so each is unit-testable on any platform.

import { isAbsolute, relative, resolve, sep } from "path";

// ---------------------------------------------------------------------------
// Text encoding (FO-34)
// ---------------------------------------------------------------------------

export type TextEncoding = "utf-8" | "utf-16le" | "utf-16be";

export interface DecodedText {
  text: string;
  encoding: TextEncoding;
  /** True when the file started with a byte-order mark (kept on write-back). */
  bom: boolean;
}

/** Share of NUL bytes, in one byte position of each pair, that marks UTF-16 text without a BOM. */
const UTF16_NUL_SHARE = 0.3;
/** Share of the other position that may be NUL (U+0100, U+0200 ... have a zero low byte). */
const UTF16_OTHER_NUL_SHARE = 0.1;

function utf16BodyToString(body: Uint8Array, encoding: "utf-16le" | "utf-16be"): string {
  const evenLength = body.length - (body.length % 2);
  const copy = Buffer.from(body.subarray(0, evenLength));
  if (encoding === "utf-16be") copy.swap16();
  return copy.toString("utf16le");
}

/** True when the decoded text looks like text: few control characters and no replacement characters. */
function plausiblyText(text: string): boolean {
  if (text.length === 0) return true;
  let odd = 0;
  const sample = text.length > 4096 ? text.slice(0, 4096) : text;
  for (let i = 0; i < sample.length; i++) {
    const c = sample.charCodeAt(i);
    if (c === 0xfffd || (c < 0x20 && c !== 9 && c !== 10 && c !== 13 && c !== 12)) odd++;
  }
  return odd / sample.length < 0.02;
}

/**
 * UTF-16 detection: a byte-order mark (FF FE / FE FF), or, for a file without one, NUL bytes sitting
 * in alternate positions (ASCII-range characters in UTF-16 have a zero high byte) and decoding to
 * something that reads as text. A binary file (NULs in both positions, or decoding to junk) is not UTF-16.
 */
export function detectUtf16(buf: Uint8Array): { encoding: "utf-16le" | "utf-16be"; bom: boolean } | null {
  if (buf.length >= 2) {
    const bomEncoding = buf[0] === 0xff && buf[1] === 0xfe ? "utf-16le"
      : buf[0] === 0xfe && buf[1] === 0xff ? "utf-16be" : null;
    if (bomEncoding) {
      // A binary file can start with these two bytes; it must also decode to text.
      const head = buf.subarray(2, Math.min(buf.length, 8192 + 2));
      return plausiblyText(utf16BodyToString(head, bomEncoding)) ? { encoding: bomEncoding, bom: true } : null;
    }
  }
  const n = Math.min(buf.length, 8192) - (Math.min(buf.length, 8192) % 2);
  if (n < 4) return null;
  let evenNul = 0;
  let oddNul = 0;
  for (let i = 0; i < n; i += 2) {
    if (buf[i] === 0) evenNul++;
    if (buf[i + 1] === 0) oddNul++;
  }
  const pairs = n / 2;
  let encoding: "utf-16le" | "utf-16be" | null = null;
  if (oddNul / pairs >= UTF16_NUL_SHARE && evenNul / pairs < UTF16_OTHER_NUL_SHARE) encoding = "utf-16le";
  else if (evenNul / pairs >= UTF16_NUL_SHARE && oddNul / pairs < UTF16_OTHER_NUL_SHARE) encoding = "utf-16be";
  if (!encoding) return null;
  return plausiblyText(utf16BodyToString(buf.subarray(0, n), encoding)) ? { encoding, bom: false } : null;
}

/** Decodes file bytes as text: UTF-16 (LE/BE, with or without BOM) when detected, else UTF-8. */
export function decodeTextBuffer(buf: Buffer): DecodedText {
  const u16 = detectUtf16(buf);
  if (u16) {
    const body = u16.bom ? buf.subarray(2) : buf;
    return { text: utf16BodyToString(body, u16.encoding), encoding: u16.encoding, bom: u16.bom };
  }
  return { text: buf.toString("utf-8"), encoding: "utf-8", bom: false };
}

/** The inverse of decodeTextBuffer, so Edit and Write keep a UTF-16 file UTF-16. */
export function encodeText(text: string, encoding: TextEncoding, bom: boolean): Buffer {
  if (encoding === "utf-8") return Buffer.from(text, "utf-8");
  const body = Buffer.from(text, "utf16le");
  if (encoding === "utf-16be") body.swap16();
  if (!bom) return body;
  return Buffer.concat([Buffer.from(encoding === "utf-16le" ? [0xff, 0xfe] : [0xfe, 0xff]), body]);
}

// ---------------------------------------------------------------------------
// Read-state key
// ---------------------------------------------------------------------------

/**
 * The key under which Read, Write and Edit record "this file was read in this session". Normalised
 * (slashes, "..") so `A:/x/f.txt` and `A:\x\f.txt` are the same file to all three tools.
 */
export function fileStateKey(filePath: string): string {
  return resolve(filePath);
}

// ---------------------------------------------------------------------------
// Working-directory boundary (FO-22)
// ---------------------------------------------------------------------------

/** True when `filePath` is not inside `cwd` (another folder, or another drive). */
export function isOutsideCwd(filePath: string, cwd: string): boolean {
  const rel = relative(resolve(cwd), resolve(filePath));
  if (rel === "") return false;
  return rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel);
}

/** The approval reason for a write that leaves the working directory. */
export function outsideCwdMessage(filePath: string, cwd: string): string {
  return `${filePath} is outside the working directory (${cwd}).`;
}

// ---------------------------------------------------------------------------
// Invalid file names (FO-43)
// ---------------------------------------------------------------------------

const WINDOWS_FORBIDDEN = /[<>:"|?*]/;
const WINDOWS_RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/i;

/**
 * Why `filePath` cannot be created as a file name, or null when it can. Checks every path segment
 * after the drive/root. On Windows `<`, `>`, `:`, `"`, `|`, `?`, `*`, device names (CON, NUL, ...) and
 * a trailing dot or space are refused; control characters are refused everywhere.
 */
export function invalidFileNameReason(filePath: string, platform: string = process.platform): string | null {
  const rest = filePath.replace(/\\/g, "/").replace(/^[A-Za-z]:/, "");
  for (const segment of rest.split("/")) {
    if (segment === "" || segment === "." || segment === "..") continue;
    if (/[\x00-\x1f]/.test(segment)) {
      return `Invalid file name "${segment}": it contains a control character.`;
    }
    if (platform !== "win32") continue;
    const bad = WINDOWS_FORBIDDEN.exec(segment);
    if (bad) {
      return `Invalid file name "${segment}": Windows does not allow the character ${bad[0]} in a file name (the characters < > : " | ? * are all forbidden). Use a different name.`;
    }
    if (WINDOWS_RESERVED.test(segment)) {
      return `Invalid file name "${segment}": it is a reserved Windows device name. Use a different name.`;
    }
    if (/[. ]$/.test(segment)) {
      return `Invalid file name "${segment}": Windows does not allow a name that ends with a dot or a space.`;
    }
  }
  return null;
}

/** A write failure in plain words (the raw `ENOENT: no such file or directory, open ...` helps nobody). */
export function describeWriteError(e: unknown, filePath: string): string {
  const err = e as { code?: string; message?: string };
  switch (err.code) {
    case "ENOENT":
      return `Cannot write ${filePath}: part of the path does not exist and could not be created, or the file name is not valid.`;
    case "EACCES":
    case "EPERM":
      return `Cannot write ${filePath}: permission denied (the file may be read-only or locked by another program).`;
    case "EISDIR":
      return `Cannot write ${filePath}: it is a directory.`;
    case "ENOTDIR":
      return `Cannot write ${filePath}: a folder in the path is actually a file.`;
    case "ENOSPC":
      return `Cannot write ${filePath}: the disk is full.`;
    case "EBUSY":
      return `Cannot write ${filePath}: the file is in use by another program.`;
    case "EROFS":
      return `Cannot write ${filePath}: the location is read-only.`;
    default:
      return `Failed to write ${filePath}: ${err.message ?? String(e)}`;
  }
}
