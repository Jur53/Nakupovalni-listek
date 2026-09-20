import { beforeEach, describe, expect, it, vi } from "vitest";

const { backendFetch } = vi.hoisted(() => ({ backendFetch: vi.fn() }));

vi.mock("@/lib/server/backend", () => ({
  backendFetch,
  jsonError: (message: string, status: number) => Response.json({ message }, { status }),
  unavailableResponse: () => Response.json({ message: "unavailable" }, { status: 503 }),
}));
vi.mock("@/lib/server/session", () => ({
  isSameOrigin: (request: Request) => {
    const origin = request.headers.get("origin");
    return origin === null || origin === new URL(request.url).origin;
  },
}));

import { GET, POST } from "@/app/api/backend/[...path]/route";

const context = (path: string[]) => ({ params: Promise.resolve({ path }) });

describe("public backend proxy route", () => {
  beforeEach(() => backendFetch.mockReset());

  it("forwards only whitelisted GET routes and propagates backend status", async () => {
    backendFetch.mockResolvedValue(Response.json({ detail: "missing" }, { status: 404 }));
    const response = await GET(
      new Request("http://localhost/api/backend/izdelki?q=mleko&kategorija_id=12&limit=24"),
      context(["izdelki"]),
    );

    expect(backendFetch).toHaveBeenCalledWith("/izdelki?q=mleko&kategorija_id=12&limit=24", undefined);
    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({ detail: "missing" });

    const blocked = await GET(
      new Request("http://localhost/api/backend/auth/me"),
      context(["auth", "me"]),
    );
    expect(blocked.status).toBe(404);
  });

  it("rejects unsupported methods, query parameters, and oversized searches", async () => {
    const wrongMethod = await GET(
      new Request("http://localhost/api/backend/primerjava"),
      context(["primerjava"]),
    );
    expect(wrongMethod.status).toBe(405);
    expect(wrongMethod.headers.get("allow")).toBe("POST");

    const badQuery = await GET(
      new Request("http://localhost/api/backend/trgovine?admin=true"),
      context(["trgovine"]),
    );
    expect(badQuery.status).toBe(400);

    const longSearch = await GET(
      new Request(`http://localhost/api/backend/izdelki?q=${"x".repeat(101)}`),
      context(["izdelki"]),
    );
    expect(longSearch.status).toBe(400);

    const invalidCategory = await GET(
      new Request("http://localhost/api/backend/izdelki?kategorija_id=neveljavna"),
      context(["izdelki"]),
    );
    expect(invalidCategory.status).toBe(400);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("requires same-origin valid bounded comparison posts", async () => {
    const body = JSON.stringify({
      items: [{ izdelek_id: 7, kolicina: 2 }],
      trgovina_ids: [1, 2],
    });
    const crossOrigin = await POST(
      new Request("http://localhost/api/backend/primerjava", {
        method: "POST",
        headers: { origin: "https://attacker.example" },
        body,
      }),
      context(["primerjava"]),
    );
    expect(crossOrigin.status).toBe(403);

    const oversized = await POST(
      new Request("http://localhost/api/backend/primerjava", {
        method: "POST",
        headers: { origin: "http://localhost", "content-length": "40000" },
        body,
      }),
      context(["primerjava"]),
    );
    expect(oversized.status).toBe(413);

    const duplicate = await POST(
      new Request("http://localhost/api/backend/primerjava", {
        method: "POST",
        headers: { origin: "http://localhost" },
        body: JSON.stringify({ items: [
          { izdelek_id: 7, kolicina: 1 },
          { izdelek_id: 7, kolicina: 2 },
        ] }),
      }),
      context(["primerjava"]),
    );
    expect(duplicate.status).toBe(400);

    backendFetch.mockResolvedValue(Response.json({ ok: true }, { status: 201 }));
    const valid = await POST(
      new Request("http://localhost/api/backend/primerjava", {
        method: "POST",
        headers: { origin: "http://localhost" },
        body,
      }),
      context(["primerjava"]),
    );
    expect(valid.status).toBe(201);
    expect(backendFetch).toHaveBeenCalledWith("/primerjava", expect.objectContaining({
      method: "POST",
      body,
    }));
  });
});
