import { beforeEach, describe, expect, it, vi } from "vitest";

const { clearToken, unavailableResponse } = vi.hoisted(() => ({
  clearToken: vi.fn(),
  unavailableResponse: vi.fn(() => Response.json({ message: "unavailable" }, { status: 503 })),
}));

vi.mock("@/lib/server/backend", () => ({
  backendErrorMessage: vi.fn(),
  backendFetch: vi.fn(),
  readJson: vi.fn(),
  jsonError: (message: string, status: number) => Response.json({ message }, { status }),
  unavailableResponse,
}));
vi.mock("@/lib/server/session", () => ({
  clearToken,
  isSameOrigin: () => true,
  setToken: vi.fn(),
}));

import { logout } from "@/lib/server/auth";

describe("server logout", () => {
  beforeEach(() => {
    clearToken.mockReset();
    unavailableResponse.mockClear();
  });

  it("reports success only after the cookie was cleared", async () => {
    clearToken.mockResolvedValue(undefined);
    const response = await logout(new Request("http://localhost/api/backend/auth/logout", { method: "POST" }));
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true });
  });

  it("reports a failure when clearing the cookie fails", async () => {
    clearToken.mockRejectedValue(new Error("cookie store failed"));
    const response = await logout(new Request("http://localhost/api/backend/auth/logout", { method: "POST" }));
    expect(unavailableResponse).toHaveBeenCalledOnce();
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ message: "unavailable" });
  });
});
