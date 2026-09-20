import {
  backendErrorMessage,
  backendFetch,
  jsonError,
  readJson,
  unavailableResponse,
} from "@/lib/server/backend";
import { clearToken, getToken } from "@/lib/server/session";

export async function GET() {
  const token = await getToken();
  if (!token) return jsonError("Niste prijavljeni.", 401);

  try {
    const response = await backendFetch("/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await readJson(response);
    if (!response.ok) {
      if (response.status === 401) await clearToken();
      return jsonError(backendErrorMessage(data, response.status), response.status);
    }
    return Response.json(data, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return unavailableResponse(error);
  }
}
