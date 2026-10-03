import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  // Canlı Jetson robot ajanı üzerindeki LiDAR REST API ucu
  const targetUrl = process.env.ROBOT_LIDAR_INTERNAL_URL || "http://127.0.0.1:8080/api/lidar";

  try {
    const upstreamRes = await fetch(targetUrl, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (!upstreamRes.ok) {
      return NextResponse.json(
        { active: false, status: "RADAR_KOPUK", error: "LiDAR servisi yanıt vermiyor" },
        { status: 502 }
      );
    }

    const data = await upstreamRes.json();
    return NextResponse.json(data, {
      status: 200,
      headers: {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch (err: any) {
    return NextResponse.json(
      { active: false, status: "RADAR_BEKLENIYOR", error: `LiDAR proxy hatası: ${err?.message || err}` },
      { status: 502 }
    );
  }
}
