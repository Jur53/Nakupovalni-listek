import "server-only";

import {
  backendErrorMessage,
  backendFetch,
  jsonError,
  readJson,
  unavailableResponse,
} from "@/lib/server/backend";
import { clearToken, isSameOrigin, setToken } from "@/lib/server/session";

type AuthAction = "login" | "register";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function authenticate(request: Request, action: AuthAction): Promise<Response> {
  if (!isSameOrigin(request)) return jsonError("Nedovoljen izvor zahteve.", 403);

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonError("Vnesite e-poštni naslov in geslo.", 400);
  }

  if (!isRecord(body)) return jsonError("Neveljavni prijavni podatki.", 400);
  const email = typeof body.email === "string" ? body.email.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!email || email.length > 254 || !password || password.length > 128) {
    return jsonError("Neveljavni prijavni podatki.", 400);
  }

  try {
    const response = await backendFetch(`/auth/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await readJson(response);
    if (!response.ok) return jsonError(backendErrorMessage(data, response.status), response.status);

    const token = isRecord(data) && typeof data.access_token === "string" ? data.access_token : "";
    const tokenType = isRecord(data) && typeof data.token_type === "string" ? data.token_type : "";
    if (!token || token.length > 8192 || tokenType.toLowerCase() !== "bearer") {
      return jsonError("Zaledna storitev je vrnila neveljaven odgovor.", 502);
    }

    await setToken(token);
    return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return unavailableResponse(error);
  }
}

export async function logout(request: Request): Promise<Response> {
  if (!isSameOrigin(request)) return jsonError("Nedovoljen izvor zahteve.", 403);
  try {
    await clearToken();
    return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return unavailableResponse(error);
  }
}
