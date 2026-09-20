import { authenticate } from "@/lib/server/auth";

export async function POST(request: Request) {
  return authenticate(request, "register");
}
