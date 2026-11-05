// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { chooseRuntimeAssets, classifyLoadFailure, parseCudaMajor, type Release } from "./runtime-fetch.ts";

const asset = (name: string) => ({ name, browser_download_url: `https://x/${name}`, size: 1, digest: "sha256:ab" });
const rel = (tag: string, published: string, names: string[]): Release => ({ tag_name: tag, published_at: published, prerelease: true, assets: names.map(asset) });

describe("classifyLoadFailure", () => {
  it("separates an unsupported model from out-of-memory", () => {
    expect(classifyLoadFailure("llama_model_load: error loading model: missing tensor 'blk.64.ssm_conv1d.weight'")).toBe("runtime-too-old");
    expect(classifyLoadFailure("unknown model architecture: 'qwen99'")).toBe("runtime-too-old");
    expect(classifyLoadFailure("ggml_backend_cuda_buffer_type_alloc_buffer: allocating 9000 MiB on device 0: cudaMalloc failed: out of memory")).toBe("out-of-memory");
    expect(classifyLoadFailure("bind failed")).toBe("other");
  });
});

describe("chooseRuntimeAssets", () => {
  const now = Date.parse("2026-11-02T14:00:00Z");
  const names = (b: string) => [
    `llama-${b}-bin-win-cuda-12.4-x64.zip`, `llama-${b}-bin-win-cuda-13.4-x64.zip`, `llama-${b}-bin-win-cuda-13.4-arm64.zip`,
    "cudart-llama-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-13.4-x64.zip",
  ];
  const releases = [rel("b3", "2026-11-02T11:00:00Z", names("b3")), rel("b2", "2026-11-01T09:00:00Z", names("b2"))];

  it("skips releases younger than a day and takes the newest CUDA the driver supports", () => {
    const p = chooseRuntimeAssets(releases, 13, now)!;
    expect(p.release.tag_name).toBe("b2");
    expect(p.llama.name).toBe("llama-b2-bin-win-cuda-13.4-x64.zip");
    expect(p.cudart?.name).toBe("cudart-llama-bin-win-cuda-13.4-x64.zip");
  });

  it("falls back to CUDA 12 on an older driver, and to null when nothing fits", () => {
    expect(chooseRuntimeAssets(releases, 12, now)!.llama.name).toBe("llama-b2-bin-win-cuda-12.4-x64.zip");
    expect(chooseRuntimeAssets(releases, 11, now)).toBeNull();
  });
});

describe("parseCudaMajor", () => {
  it("reads both nvidia-smi header formats and falls back to the driver version", () => {
    expect(parseCudaMajor("| NVIDIA-SMI 610.88   KMD Version: 610.88   CUDA UMD Version: 13.3 |")).toBe(13);
    expect(parseCudaMajor("| NVIDIA-SMI 551.86   Driver Version: 551.86   CUDA Version: 12.4 |")).toBe(12);
    expect(parseCudaMajor("| NVIDIA-SMI 590.10   Driver Version: 590.10 |")).toBe(13);
    expect(parseCudaMajor("nothing")).toBeNull();
  });
});

import { listRuntimeReleases, RELEASE_PAGE_SIZE } from "./runtime-fetch.ts";

describe("listRuntimeReleases", () => {
  // Builds arrive every 30-60 minutes; a burst of 100 within 24 hours is the worst case this must survive.
  const now = Date.parse("2026-11-03T12:00:00Z");
  const names = (b: string) => [`llama-${b}-bin-win-cuda-13.4-x64.zip`, "cudart-llama-bin-win-cuda-13.4-x64.zip"];
  const young = Array.from({ length: RELEASE_PAGE_SIZE }, (_, i) =>
    rel(`b${2000 - i}`, new Date(now - (i + 1) * 10 * 60_000).toISOString(), names(`b${2000 - i}`)));
  const old = [rel("b1000", "2026-11-01T00:00:00Z", names("b1000"))];

  it("keeps paging until a release past the soak window is in hand", async () => {
    const urls: string[] = [];
    const fakeFetch = (async (url: string) => {
      urls.push(url);
      const page = Number(new URL(url).searchParams.get("page"));
      return new Response(JSON.stringify(page === 1 ? young : old), { status: 200 });
    }) as unknown as typeof fetch;
    const releases = await listRuntimeReleases(13, now, fakeFetch);
    expect(urls.length).toBe(2);
    expect(urls[0]).toContain(`per_page=${RELEASE_PAGE_SIZE}`);
    expect(chooseRuntimeAssets(releases, 13, now)?.release.tag_name).toBe("b1000");
  });

  it("stops after one page when that page already holds a usable release", async () => {
    let calls = 0;
    const fakeFetch = (async () => { calls++; return new Response(JSON.stringify([...young.slice(0, 3), ...old]), { status: 200 }); }) as unknown as typeof fetch;
    await listRuntimeReleases(13, now, fakeFetch);
    expect(calls).toBe(1);
  });

  it("names the rate limit when GitHub answers 403", async () => {
    const fakeFetch = (async () => new Response("{}", { status: 403 })) as unknown as typeof fetch;
    await expect(listRuntimeReleases(13, now, fakeFetch)).rejects.toThrow(/rate limited/);
  });
});
