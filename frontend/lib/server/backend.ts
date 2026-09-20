import "server-only";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
export const BACKEND_TIMEOUT_MS = 10_000;

function getBackendOrigin(): string {
  const configured = process.env.BACKEND_URL;
  if (!configured && process.env.NODE_ENV === "production") {
    throw new Error("BACKEND_URL is required in production");
  }
  const url = new URL(configured ?? DEFAULT_BACKEND_URL);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.pathname !== "/" && url.pathname !== "")
  ) {
    throw new Error("Invalid BACKEND_URL");
  }
  const loopback = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]).has(url.hostname);
  if (process.env.NODE_ENV === "production" && url.protocol !== "https:" && !loopback) {
    throw new Error("BACKEND_URL must use HTTPS in production unless it is loopback");
  }
  return url.origin;
}

export async function backendFetch(path: string, init?: RequestInit): Promise<Response> {
  const timeoutController = new AbortController();
  const timeout = setTimeout(() => {
    timeoutController.abort(new DOMException("Backend request timed out", "TimeoutError"));
  }, BACKEND_TIMEOUT_MS);
  const signal = init?.signal
    ? AbortSignal.any([init.signal, timeoutController.signal])
    : timeoutController.signal;

  try {
    const response = await fetch(new URL(path.replace(/^\/+/, ""), `${getBackendOrigin()}/`), {
      ...init,
      cache: "no-store",
      signal,
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });
    const body = response.status === 204 ? null : await response.arrayBuffer();
    return new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  } finally {
    clearTimeout(timeout);
  }
}

export async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function backendErrorMessage(value: unknown, status: number): string {
  if (isRecord(value)) {
    if (typeof value.detail === "string" && value.detail.trim()) return value.detail;
    if (typeof value.message === "string" && value.message.trim()) return value.message;
    if (isRecord(value.detail) && typeof value.detail.message === "string") {
      return value.detail.message;
    }
    if (Array.isArray(value.detail)) {
      const detail = value.detail.find(isRecord);
      if (detail && typeof detail.msg === "string") return detail.msg;
    }
  }
  if (status === 401) return "Napačen e-poštni naslov ali geslo.";
  if (status >= 500) return "Zaledna storitev trenutno ni dosegljiva.";
  return "Zahteve ni bilo mogoče dokončati.";
}

export function jsonError(message: string, status: number): Response {
  return Response.json(
    { message },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

export async function unavailableResponse(error: unknown): Promise<Response> {
  console.error("Backend request failed", error);
  return jsonError("Zaledna storitev trenutno ni dosegljiva.", 503);
}
