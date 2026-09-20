import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { BACKEND_TIMEOUT_MS, backendFetch } from "@/lib/server/backend";

describe("backendFetch", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("requires an explicit secure backend origin in production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("BACKEND_URL", "");
    vi.stubGlobal("fetch", vi.fn());

    await expect(backendFetch("/trgovine")).rejects.toThrow("required in production");

    vi.stubEnv("BACKEND_URL", "http://backend.internal:8000");
    await expect(backendFetch("/trgovine")).rejects.toThrow("must use HTTPS");
  });

  it("composes the caller abort signal with its timeout", async () => {
    const caller = new AbortController();
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      }));
    vi.stubGlobal("fetch", fetchMock);

    const pending = backendFetch("/trgovine", { signal: caller.signal });
    const forwardedSignal = fetchMock.mock.calls[0][1]?.signal;
    expect(forwardedSignal).not.toBe(caller.signal);
    expect(forwardedSignal?.aborted).toBe(false);

    caller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(forwardedSignal?.aborted).toBe(true);
  });

  it("aborts a backend request after the fixed timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      })));

    const pending = backendFetch("/cene");
    const rejection = expect(pending).rejects.toMatchObject({ name: "TimeoutError" });
    await vi.advanceTimersByTimeAsync(BACKEND_TIMEOUT_MS);
    await rejection;
  });

  it("keeps the timeout active while reading the response body", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const body = new ReadableStream({
        start(controller) {
          init?.signal?.addEventListener("abort", () => controller.error(init.signal?.reason));
        },
      });
      return Promise.resolve(new Response(body));
    }));

    const pending = backendFetch("/cene");
    const rejection = expect(pending).rejects.toMatchObject({ name: "TimeoutError" });
    await vi.advanceTimersByTimeAsync(BACKEND_TIMEOUT_MS);
    await rejection;
  });
});
