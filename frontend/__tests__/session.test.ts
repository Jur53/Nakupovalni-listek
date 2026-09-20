import { beforeEach, describe, expect, it, vi } from "vitest";

const { setCookie } = vi.hoisted(() => ({ setCookie: vi.fn() }));

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: vi.fn(), set: setCookie })),
}));

import { getTokenMaxAge, setToken } from "@/lib/server/session";

function tokenWithPayload(payload: unknown): string {
  return `header.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.signature`;
}

describe("session cookie expiry", () => {
  beforeEach(() => setCookie.mockClear());

  it("matches a JWT expiry that is sooner than the cap", async () => {
    const token = tokenWithPayload({ exp: 1_700_003_600 });
    expect(getTokenMaxAge(token, 1_700_000_000)).toBe(3_600);

    vi.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);
    await setToken(token);
    expect(setCookie).toHaveBeenCalledWith(
      "nakupovalni_access",
      token,
      expect.objectContaining({ maxAge: 3_600 }),
    );
  });

  it("caps long-lived tokens and expires malformed or old tokens immediately", () => {
    expect(getTokenMaxAge(tokenWithPayload({ exp: 2_000_000_000 }), 1_700_000_000)).toBe(604_800);
    expect(getTokenMaxAge("not-a-jwt", 1_700_000_000)).toBe(0);
    expect(getTokenMaxAge(tokenWithPayload({}), 1_700_000_000)).toBe(0);
    expect(getTokenMaxAge(tokenWithPayload({ exp: 1_699_999_999 }), 1_700_000_000)).toBe(0);
  });
});
