import {
  backendFetch,
  jsonError,
  unavailableResponse,
} from "@/lib/server/backend";
import { isSameOrigin } from "@/lib/server/session";

const MAX_QUERY_BYTES = 2_048;
const MAX_BODY_BYTES = 32 * 1024;
const GET_ENDPOINTS = new Set(["trgovine", "izdelki", "cene"]);
const QUERY_PARAMETERS: Record<string, Set<string>> = {
  trgovine: new Set(["offset", "limit"]),
  izdelki: new Set(["q", "kategorija", "kategorija_id", "trgovina_ids", "offset", "limit"]),
  cene: new Set(["offset", "limit"]),
};

type RouteContext = { params: Promise<{ path: string[] }> };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function endpoint(context: RouteContext): Promise<string | null> {
  const { path } = await context.params;
  return path.length === 1 ? path[0] : null;
}

function methodNotAllowed(allow: "GET" | "POST"): Response {
  return Response.json(
    { message: "Metoda za ta endpoint ni dovoljena." },
    { status: 405, headers: { Allow: allow, "Cache-Control": "no-store" } },
  );
}

function validIntegerParameter(value: string, minimum: number, maximum?: number): boolean {
  if (!/^\d+$/.test(value)) return false;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum && (maximum === undefined || parsed <= maximum);
}

function validateQuery(endpointName: string, url: URL): string | null {
  if (new TextEncoder().encode(url.search).byteLength > MAX_QUERY_BYTES) {
    return "Poizvedba je predolga.";
  }

  const allowed = QUERY_PARAMETERS[endpointName];
  const entries = [...url.searchParams.entries()];
  if (entries.length > 100 || entries.some(([name]) => !allowed.has(name))) {
    return "Poizvedba vsebuje nedovoljene parametre.";
  }

  for (const name of ["offset", "limit"] as const) {
    const values = url.searchParams.getAll(name);
    if (values.length > 1) return "Poizvedba vsebuje podvojene parametre.";
    if (values[0] && !validIntegerParameter(values[0], name === "offset" ? 0 : 1, name === "limit" ? 100 : undefined)) {
      return "Poizvedba vsebuje neveljavne parametre.";
    }
  }

  for (const name of ["q", "kategorija"] as const) {
    const values = url.searchParams.getAll(name);
    if (values.length > 1 || (values[0] && values[0].length > 100)) {
      return "Poizvedba vsebuje neveljavne parametre.";
    }
  }

  const categoryIds = url.searchParams.getAll("kategorija_id");
  if (categoryIds.length > 1 || (categoryIds[0] && !validIntegerParameter(categoryIds[0], 1))) {
    return "Poizvedba vsebuje neveljavno kategorijo.";
  }

  const storeIds = url.searchParams.getAll("trgovina_ids");
  if (
    storeIds.length > 100 ||
    storeIds.some((value) => !validIntegerParameter(value, 1)) ||
    new Set(storeIds).size !== storeIds.length
  ) {
    return "Poizvedba vsebuje neveljavne trgovine.";
  }
  return null;
}

function validComparison(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value) || !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 100) {
    return false;
  }
  const productIds = new Set<number>();
  for (const item of value.items) {
    if (
      !isRecord(item) ||
      !Number.isSafeInteger(item.izdelek_id) ||
      Number(item.izdelek_id) <= 0 ||
      !Number.isSafeInteger(item.kolicina) ||
      Number(item.kolicina) <= 0 ||
      Number(item.kolicina) > 10_000 ||
      productIds.has(Number(item.izdelek_id))
    ) return false;
    productIds.add(Number(item.izdelek_id));
  }

  if (value.trgovina_ids === undefined) return true;
  if (!Array.isArray(value.trgovina_ids) || value.trgovina_ids.length < 1 || value.trgovina_ids.length > 100) {
    return false;
  }
  return value.trgovina_ids.every((id) => Number.isSafeInteger(id) && Number(id) > 0) &&
    new Set(value.trgovina_ids).size === value.trgovina_ids.length;
}

async function forward(path: string, init?: RequestInit): Promise<Response> {
  try {
    const response = await backendFetch(path, init);
    const body = response.status === 204 ? null : await response.arrayBuffer();
    const contentType = response.headers.get("content-type");
    return new Response(body, {
      status: response.status,
      headers: {
        ...(contentType ? { "Content-Type": contentType } : {}),
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    return unavailableResponse(error);
  }
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  const name = await endpoint(context);
  if (!name) return jsonError("Endpoint ne obstaja.", 404);
  if (name === "primerjava") return methodNotAllowed("POST");
  if (!GET_ENDPOINTS.has(name)) return jsonError("Endpoint ne obstaja.", 404);

  const url = new URL(request.url);
  const queryError = validateQuery(name, url);
  if (queryError) return jsonError(queryError, 400);
  return forward(`/${name}${url.search}`);
}

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  const name = await endpoint(context);
  if (!name) return jsonError("Endpoint ne obstaja.", 404);
  if (GET_ENDPOINTS.has(name)) return methodNotAllowed("GET");
  if (name !== "primerjava") return jsonError("Endpoint ne obstaja.", 404);
  if (!isSameOrigin(request)) return jsonError("Nedovoljen izvor zahteve.", 403);

  const contentLength = request.headers.get("content-length");
  if (contentLength !== null) {
    const length = Number(contentLength);
    if (!Number.isSafeInteger(length) || length < 0 || length > MAX_BODY_BYTES) {
      return jsonError("Zahteva je prevelika.", 413);
    }
  }

  try {
    const text = await request.text();
    if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) {
      return jsonError("Zahteva je prevelika.", 413);
    }
    const body: unknown = JSON.parse(text);
    if (!validComparison(body)) return jsonError("Neveljavna primerjava.", 400);
    return forward("/primerjava", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return jsonError("Neveljavna primerjava.", 400);
  }
}
