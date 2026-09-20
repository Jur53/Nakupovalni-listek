import "server-only";

import { cookies } from "next/headers";

const TOKEN_COOKIE = "nakupovalni_access";
const MAX_COOKIE_AGE_SECONDS = 60 * 60 * 24 * 7;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getTokenMaxAge(token: string, nowSeconds = Date.now() / 1000): number {
  const payload = token.split(".")[1];
  if (!payload || payload.length > 16_384) return 0;

  try {
    const decoded = Buffer.from(payload, "base64url").toString("utf8");
    const value: unknown = JSON.parse(decoded);
    if (!isRecord(value) || typeof value.exp !== "number" || !Number.isFinite(value.exp)) {
      return 0;
    }
    return Math.max(0, Math.min(MAX_COOKIE_AGE_SECONDS, Math.floor(value.exp - nowSeconds)));
  } catch {
    return 0;
  }
}

export async function getToken(): Promise<string | null> {
  return (await cookies()).get(TOKEN_COOKIE)?.value ?? null;
}

export async function setToken(token: string): Promise<void> {
  (await cookies()).set(TOKEN_COOKIE, token, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: getTokenMaxAge(token),
    priority: "high",
  });
}

export async function clearToken(): Promise<void> {
  (await cookies()).set(TOKEN_COOKIE, "", {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
}

export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  return origin === null || origin === new URL(request.url).origin;
}
