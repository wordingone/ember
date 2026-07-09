// services/outage-banner-poller.test.ts — issue #475: pins the pure projection from a raw
// planned-outage.json read to status-bar.ts's OutageBannerState, plus the real-fs read path
// (including the BOM-tolerance fix). The React hook (useOutageBanner) is a thin
// setInterval/useState shell around these; testing the projection + file read directly
// avoids needing a React render cycle.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { projectOutageBanner, readOutageBannerState } from "./outage-banner-poller.ts";

const validMarker = {
  owner: "jun",
  reason: "grow-event window",
  target: "server",
  started: "2026-07-08T00:00:00Z",
  expires: "2026-07-08T01:00:00Z",
  kill_receipt_ref: "ref-1",
};

describe("projectOutageBanner", () => {
  const nowMs = Date.parse("2026-07-08T00:30:00Z"); // inside the marker's window

  it("returns {active:false} for a null raw read (marker absent)", () => {
    expect(projectOutageBanner(null, nowMs)).toEqual({ active: false });
  });

  it("returns {active:false} for unparsable JSON", () => {
    expect(projectOutageBanner("{ not json", nowMs)).toEqual({ active: false });
  });

  it("returns {active:false} for a marker missing a required field", () => {
    const { kill_receipt_ref, ...rest } = validMarker;
    void kill_receipt_ref;
    expect(projectOutageBanner(JSON.stringify(rest), nowMs)).toEqual({ active: false });
  });

  it("projects a fully-valid, unexpired marker to an active banner with its fields", () => {
    const banner = projectOutageBanner(JSON.stringify(validMarker), nowMs);
    expect(banner.active).toBe(true);
    expect(banner.owner).toBe("jun");
    expect(banner.reason).toBe("grow-event window");
    expect(banner.expires).toBe("2026-07-08T01:00:00Z");
  });

  it("returns {active:false} once the marker has expired (never extends silently)", () => {
    const expiredNow = Date.parse("2026-07-08T02:00:00Z");
    expect(projectOutageBanner(JSON.stringify(validMarker), expiredNow)).toEqual({ active: false });
  });

  it("#475: tolerates a leading UTF-8 BOM (PowerShell -Encoding utf8 default)", () => {
    const bomPrefixed = "﻿" + JSON.stringify(validMarker);
    const banner = projectOutageBanner(bomPrefixed, nowMs);
    expect(banner.active).toBe(true);
    expect(banner.owner).toBe("jun");
  });
});

describe("readOutageBannerState — real fs", () => {
  let scratchDir: string;

  beforeEach(() => {
    scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-outage-banner-"));
  });

  afterEach(() => {
    fs.rmSync(scratchDir, { recursive: true, force: true });
  });

  it("returns {active:false} when the marker file does not exist", async () => {
    const markerPath = path.join(scratchDir, "planned-outage.json");
    const banner = await readOutageBannerState(markerPath, Date.now());
    expect(banner).toEqual({ active: false });
  });

  it("returns an active banner for a real unexpired marker file on disk", async () => {
    const markerPath = path.join(scratchDir, "planned-outage.json");
    const future = new Date(Date.now() + 60_000).toISOString();
    fs.writeFileSync(
      markerPath,
      JSON.stringify({ ...validMarker, expires: future }),
      "utf-8",
    );
    const banner = await readOutageBannerState(markerPath, Date.now());
    expect(banner.active).toBe(true);
    expect(banner.owner).toBe("jun");
    expect(banner.expires).toBe(future);
  });

  it("tolerates a real BOM-prefixed file written to disk", async () => {
    const markerPath = path.join(scratchDir, "planned-outage.json");
    const future = new Date(Date.now() + 60_000).toISOString();
    const bomPrefixed = "﻿" + JSON.stringify({ ...validMarker, expires: future });
    fs.writeFileSync(markerPath, bomPrefixed, "utf-8");
    const banner = await readOutageBannerState(markerPath, Date.now());
    expect(banner.active).toBe(true);
  });

  it("disappears the moment the marker file is deleted", async () => {
    const markerPath = path.join(scratchDir, "planned-outage.json");
    const future = new Date(Date.now() + 60_000).toISOString();
    fs.writeFileSync(markerPath, JSON.stringify({ ...validMarker, expires: future }), "utf-8");
    expect((await readOutageBannerState(markerPath, Date.now())).active).toBe(true);

    fs.rmSync(markerPath);
    expect((await readOutageBannerState(markerPath, Date.now())).active).toBe(false);
  });
});
