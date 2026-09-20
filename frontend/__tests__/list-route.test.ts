import { beforeEach, describe, expect, it, vi } from "vitest";

const { backendFetch, getToken, clearToken } = vi.hoisted(() => ({
  backendFetch: vi.fn(),
  getToken: vi.fn(),
  clearToken: vi.fn(),
}));

vi.mock("@/lib/server/backend", () => ({
  backendFetch,
  readJson: async (response: Response) => response.json(),
  backendErrorMessage: () => "Niste prijavljeni.",
  jsonError: (message: string, status: number) => Response.json({ message }, { status }),
  unavailableResponse: () => Response.json({ message: "unavailable" }, { status: 503 }),
}));
vi.mock("@/lib/server/session", () => ({
  getToken,
  clearToken,
  isSameOrigin: () => true,
}));

import { GET, POST } from "@/app/api/backend/seznami/route";

describe("saved-list route", () => {
  beforeEach(() => {
    backendFetch.mockReset();
    getToken.mockReset();
    clearToken.mockReset();
  });

  it("authenticates before parsing a POST body", async () => {
    getToken.mockResolvedValue(null);
    const response = await POST(new Request("http://localhost/api/backend/seznami", {
      method: "POST",
      body: "not json",
    }));
    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("rejects duplicate, excessive, and oversized list items", async () => {
    getToken.mockResolvedValue("token");
    const request = (items: unknown[]) => POST(new Request("http://localhost/api/backend/seznami", {
      method: "POST",
      body: JSON.stringify({ ime: "Tedenski", items }),
    }));

    expect((await request([
      { izdelek_id: 1, kolicina: 1 },
      { izdelek_id: 1, kolicina: 2 },
    ])).status).toBe(400);
    expect((await request([{ izdelek_id: 1, kolicina: 10_001 }])).status).toBe(400);
    expect((await request(Array.from({ length: 101 }, (_, index) => ({
      izdelek_id: index + 1,
      kolicina: 1,
    })))).status).toBe(400);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("clears the session cookie when the backend rejects it", async () => {
    getToken.mockResolvedValue("expired-token");
    backendFetch.mockResolvedValue(Response.json({ detail: "expired" }, { status: 401 }));

    const response = await GET();
    expect(response.status).toBe(401);
    expect(clearToken).toHaveBeenCalledOnce();
  });
});
