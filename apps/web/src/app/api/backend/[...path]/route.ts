import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";

const API_BASE = process.env.API_BASE_URL || "http://localhost:8080";
const API_KEY = process.env.INGEST_API_KEY || "";

type Context = {
  params: Promise<{
    path: string[];
  }>;
};

async function proxy(request: Request, context: Context) {
  const session = await getServerSession(authOptions);

  if (!session?.user?.email) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const params = await context.params;
  const path = params.path.join("/");
  const url = new URL(request.url);
  const target = `${API_BASE}/${path}${url.search}`;

  const response = await fetch(target, {
    method: request.method,
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
    body:
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.text(),
    cache: "no-store",
  });

  const text = await response.text();

  return new Response(text, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json",
    },
  });
}

export async function GET(request: Request, context: Context) {
  return proxy(request, context);
}

export async function POST(request: Request, context: Context) {
  return proxy(request, context);
}
