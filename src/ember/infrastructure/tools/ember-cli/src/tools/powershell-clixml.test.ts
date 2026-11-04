// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Visible-window test: a PowerShell call showed "#< CLIXML <Objs ...Preparing modules..." as stderr.
import { test, expect } from "bun:test";
import { stripClixml } from "./powershell-tool.ts";

test("progress records are dropped", () => {
  const raw = '#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04"><Obj S="progress" RefId="0"><TN RefId="0"><T>System.Object</T></TN><MS><PR N="Record"><AV>Preparing modules for first use.</AV></PR></MS></Obj></Objs>';
  expect(stripClixml(raw)).toBe("");
});

test("error records keep their text", () => {
  const raw = '#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="x"><S S="Error">Cannot find path &apos;C:\\nope&apos;_x000D__x000A_</S></Objs>';
  expect(stripClixml(raw)).toBe("Cannot find path 'C:\\nope'");
});

test("plain stderr is untouched", () => {
  expect(stripClixml("boom")).toBe("boom");
});
