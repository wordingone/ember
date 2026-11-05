// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { test, expect } from "bun:test";
import { isDestructiveCommand } from "./destructive-command.ts";
import { bashTool } from "../tools/bash-tool.ts";

test("bulk deletes and history rewrites are destructive", () => {
  for (const c of [
    "rd /s /q decoy", "rmdir /S build", "del /q *.log", "rm -rf node_modules", "rm -r out",
    "cd x && rm -f a.txt", "Remove-Item -Recurse -Force .\\decoy3", "git reset --hard HEAD~1",
    "git clean -fd", "git push --force origin main", "format d:", "Format-Volume -DriveLetter D",
  ]) expect(isDestructiveCommand(c)).toBe(true);
});

test("ordinary commands are not", () => {
  for (const c of [
    "ls -la", "dir /b", "git status", "mkdir -p a/b", "python -m unittest -v",
    "git push origin main", "python del_file.py --help", "rm notes.txt",
  ]) expect(isDestructiveCommand(c)).toBe(false);
});

test("Bash asks for a destructive command, so 'always allow' and headless runs cannot skip it", async () => {
  const ctx = { getAppState: () => ({}) } as any;
  const p = await bashTool.checkPermissions({ command: "rd /s /q decoy" } as any, ctx);
  expect(p.behavior).toBe("ask");
});
