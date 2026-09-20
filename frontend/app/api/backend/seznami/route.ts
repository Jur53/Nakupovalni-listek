import {
  backendErrorMessage,
  backendFetch,
  jsonError,
  readJson,
  unavailableResponse,
} from "@/lib/server/backend";
import { clearToken, getToken, isSameOrigin } from "@/lib/server/session";

const MAX_LIST_BODY_BYTES = 32 * 1024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function authorizedRequest(path: string, init?: RequestInit, existingToken?: string): Promise<Response> {
  const token = existingToken ?? await getToken();
  if (!token) return jsonError("Niste prijavljeni.", 401);

  try {
    const response = await backendFetch(path, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        ...init?.headers,
      },
    });
    const data = await readJson(response);
    if (!response.ok) {
      if (response.status === 401) await clearToken();
      return jsonError(backendErrorMessage(data, response.status), response.status);
    }
    return Response.json(data, {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    return unavailableResponse(error);
  }
}

export async function GET() {
  return authorizedRequest("/seznami");
}

export async function POST(request: Request) {
  if (!isSameOrigin(request)) return jsonError("Nedovoljen izvor zahteve.", 403);

  const token = await getToken();
  if (!token) return jsonError("Niste prijavljeni.", 401);

  const contentLength = request.headers.get("content-length");
  if (contentLength !== null) {
    const length = Number(contentLength);
    if (!Number.isSafeInteger(length) || length < 0 || length > MAX_LIST_BODY_BYTES) {
      return jsonError("Seznam je prevelik.", 413);
    }
  }

  let body: unknown;
  try {
    const text = await request.text();
    if (new TextEncoder().encode(text).byteLength > MAX_LIST_BODY_BYTES) {
      return jsonError("Seznam je prevelik.", 413);
    }
    body = JSON.parse(text);
  } catch {
    return jsonError("Neveljaven seznam.", 400);
  }

  if (!isRecord(body)) return jsonError("Neveljaven seznam.", 400);
  const name = typeof body.ime === "string" ? body.ime.trim() : "";
  const items = body.items;
  const validItems =
    Array.isArray(items) &&
    items.length > 0 &&
    items.length <= 100 &&
    items.every(
      (item) =>
        isRecord(item) &&
        Number.isSafeInteger(item.izdelek_id) &&
        Number(item.izdelek_id) > 0 &&
        Number.isSafeInteger(item.kolicina) &&
        Number(item.kolicina) > 0 &&
        Number(item.kolicina) <= 10_000,
    );
  const uniqueItems = validItems && new Set(items.map((item) => item.izdelek_id)).size === items.length;

  if (!name || name.length > 100 || !validItems || !uniqueItems) {
    return jsonError("Ime in izdelki na seznamu niso veljavni.", 400);
  }

  return authorizedRequest("/seznami", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ime: name, items }),
  }, token);
}
