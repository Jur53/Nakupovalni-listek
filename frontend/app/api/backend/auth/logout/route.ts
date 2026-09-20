import { logout } from "@/lib/server/auth";

export async function POST(request: Request) {
  return logout(request);
}
