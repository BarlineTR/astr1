import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const targetUrl = process.env.ROBOT_STREAM_INTERNAL_URL || "http://127.0.0.1:8080/camera/stream.mjpg";

  try {
    const upstreamRes = await fetch(targetUrl, {
      cache: "no-store",
    });

    if (!upstreamRes.ok || !upstreamRes.body) {
      return new Response("Camera upstream unavailable", { status: 502 });
    }

    const headers = new Headers();
    headers.set("Content-Type", upstreamRes.headers.get("Content-Type") || "multipart/x-mixed-replace; boundary=--frame");
    headers.set("Cache-Control", "no-cache, no-store, must-revalidate");
    headers.set("Pragma", "no-cache");
    headers.set("Expires", "0");
    headers.set("Access-Control-Allow-Origin", "*");

    return new Response(upstreamRes.body, {
      status: 200,
      headers,
    });
  } catch (err: any) {
    return new Response(`Camera proxy error: ${err?.message || err}`, { status: 502 });
  }
}
