// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import {
  HARDENING_CELLS,
  runHardeningMatrix,
  validateHardeningMatrixReceipt,
  type HardeningMatrixReceipt,
  type MatrixRunner,
} from "./cli-hardening-matrix.ts";

const COMMIT = "a".repeat(40);
const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "ember-cli-hardening-"));
  roots.push(root);
  const repositoryRoot = join(root, "repo");
  const sourceRoot = join(repositoryRoot, "tools", "ember-cli", "src");
  const receiptPath = join(root, "receipt", "receipt.json");
  const executable = join(root, "bun.exe");
  mkdirSync(sourceRoot, { recursive: true });
  writeFileSync(join(sourceRoot, ".keep"), "", "utf8");
  writeFileSync(executable, "pinned runner bytes", "utf8");
  return { repositoryRoot, sourceRoot, receiptPath, executable };
}

describe("#159 closed CLI hardening matrix", () => {
  test("writes and validates one content-addressed PASS row per closed cell", () => {
    const f = fixture();
    const calls: string[][] = [];
    const runner: MatrixRunner = (_exe, args, cwd) => {
      expect(resolve(cwd)).toBe(resolve(f.sourceRoot));
      calls.push([...args]);
      return { status: 0, stdout: "green\n", stderr: "" };
    };
    const result = runHardeningMatrix({
      ...f,
      sourceCommit: COMMIT,
      runner,
    });

    expect(calls).toHaveLength(HARDENING_CELLS.length);
    expect(result.receipt.matrix.map((row) => row.id)).toEqual(
      HARDENING_CELLS.map((cell) => cell.id),
    );
    expect(result.receipt.overall).toBe("PASS");
    const bytes = readFileSync(f.receiptPath, "utf8");
    expect(JSON.parse(bytes)).toEqual(result.receipt);
    expect(readFileSync(
      join(rootDir(f.receiptPath), `receipt-${result.receiptSha256}.json`),
      "utf8",
    )).toBe(bytes);
  });

  test("persists a FAIL receipt and throws when any cell fails", () => {
    const f = fixture();
    let call = 0;
    const runner: MatrixRunner = () => ({
      status: call++ === 2 ? 1 : 0,
      stdout: "",
      stderr: "bounded failure",
    });

    expect(() => runHardeningMatrix({
      ...f,
      sourceCommit: COMMIT,
      runner,
    })).toThrow("backend-death-and-recovery");
    const receipt = JSON.parse(readFileSync(f.receiptPath, "utf8")) as HardeningMatrixReceipt;
    expect(receipt.overall).toBe("FAIL");
    expect(receipt.matrix[2]?.outcome).toBe("FAIL");
  });

  test("validator rejects row deletion, reordered cells, and false green", () => {
    const f = fixture();
    const result = runHardeningMatrix({
      ...f,
      sourceCommit: COMMIT,
      runner: () => ({ status: 0, stdout: "", stderr: "" }),
    });
    const expectedRunnerSha = result.receipt.runner.sha256;
    const clone = (): HardeningMatrixReceipt =>
      JSON.parse(JSON.stringify(result.receipt)) as HardeningMatrixReceipt;

    const missing = clone();
    missing.matrix.pop();
    expect(() => validateHardeningMatrixReceipt(missing, COMMIT, expectedRunnerSha))
      .toThrow("cell order");

    const reordered = clone();
    [reordered.matrix[0], reordered.matrix[1]] = [reordered.matrix[1]!, reordered.matrix[0]!];
    expect(() => validateHardeningMatrixReceipt(reordered, COMMIT, expectedRunnerSha))
      .toThrow("cell order");

    const falseGreen = clone();
    falseGreen.matrix[0]!.exit_code = 1;
    expect(() => validateHardeningMatrixReceipt(falseGreen, COMMIT, expectedRunnerSha))
      .toThrow("row failed");
  });

  test("rejects a mismatched source commit and runner hash", () => {
    const f = fixture();
    const result = runHardeningMatrix({
      ...f,
      sourceCommit: COMMIT,
      runner: () => ({ status: 0, stdout: "", stderr: "" }),
    });
    expect(() => validateHardeningMatrixReceipt(
      result.receipt,
      "b".repeat(40),
      result.receipt.runner.sha256,
    )).toThrow("identity");
    expect(() => validateHardeningMatrixReceipt(
      result.receipt,
      COMMIT,
      "c".repeat(64),
    )).toThrow("runner binding");
  });
});

function rootDir(path: string): string {
  return resolve(path, "..");
}
