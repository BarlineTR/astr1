"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { waypointEkle, waypointSil } from "@/app/panel/harita/actions";

interface Waypoint {
  id: string;
  name: string;
  x: number;
  y: number;
}

interface SectorInfo {
  distance_m: number | null;
  clear: boolean;
}

interface LidarApiResponse {
  active: boolean;
  status?: string;
  timestamp?: number;
  scan_hz?: number;
  point_count?: number;
  total_samples?: number;
  nearest_obstacle_m?: number | null;
  nearest_obstacle_deg?: number | null;
  nearest_sector?: string;
  robot_yaw_deg?: number;
  head_desired_deg?: number;
  sectors?: {
    front?: SectorInfo;
    left?: SectorInfo;
    right?: SectorInfo;
    back?: SectorInfo;
  };
  points?: Array<[number, number, number, number]>; // [x, y, range_m, deg]
}

export function LidarHarita({
  deviceId,
  noktalar,
}: {
  deviceId: string;
  noktalar: Waypoint[];
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [seciliKonum, setSeciliKonum] = useState<{ x: number; y: number } | null>(null);
  const [noktaAdi, setNoktaAdi] = useState("");
  const [devriyeAktif, setDevriyeAktif] = useState(false);
  const [bekliyor, startTransition] = useTransition();

  // Radar Görünüm Ayarları
  const [canliAkis, setCanliAkis] = useState(true);
  const [maxMesafe, setMaxMesafe] = useState<number>(5); // 3m, 5m, 8m
  const [taramaIsiniGoster, setTaramaIsiniGoster] = useState(true);

  // Canlı LiDAR Verisi Durumu
  const [lidarVerisi, setLidarVerisi] = useState<LidarApiResponse | null>(null);
  const [baglantiHatasi, setBaglantiHatasi] = useState<string | null>(null);

  // Radar tarama açısı (animasyon için)
  const sweepAngleRef = useRef<number>(0);
  const animFrameRef = useRef<number | null>(null);

  // 1. Canlı LiDAR REST Akışı (Polling - ~7-8 Hz)
  useEffect(() => {
    if (!canliAkis) return;
    let iptal = false;

    async function veriCek() {
      try {
        const res = await fetch("/api/lidar", { cache: "no-store" });
        if (iptal) return;
        if (res.ok) {
          const data = (await res.json()) as LidarApiResponse;
          if (data && data.active !== false) {
            setLidarVerisi(data);
            setBaglantiHatasi(null);
          } else {
            setBaglantiHatasi(data?.status || "Lidar verisi bekleniyor");
          }
        } else {
          setBaglantiHatasi("Robot bağlantısı bekleniyor");
        }
      } catch {
        if (!iptal) {
          setBaglantiHatasi("LiDAR servisi çevrimdışı");
        }
      }
    }

    veriCek();
    const interval = setInterval(veriCek, 130);

    return () => {
      iptal = true;
      clearInterval(interval);
    };
  }, [canliAkis]);

  // 2. Radar Çizim Döngüsü (Canvas Render)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let isRunning = true;

    function ciz() {
      if (!canvas || !ctx || !isRunning) return;

      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const radius = Math.min(cx, cy) - 25;
      const scale = radius / maxMesafe; // px / metre

      // Arka Plan
      ctx.fillStyle = "#070a12";
      ctx.fillRect(0, 0, w, h);

      // Radar Taban Halkaları & Izgara
      ctx.strokeStyle = "rgba(30, 41, 59, 0.6)";
      ctx.lineWidth = 1;

      // Çapraz Sektör Çizgileri (Ön/Arka/Sol/Sağ sınırları)
      ctx.beginPath();
      ctx.moveTo(cx - radius, cy);
      ctx.lineTo(cx + radius, cy);
      ctx.moveTo(cx, cy - radius);
      ctx.lineTo(cx, cy + radius);
      // 45 derece çaprazlar
      const diag = radius * 0.7071;
      ctx.moveTo(cx - diag, cy - diag);
      ctx.lineTo(cx + diag, cy + diag);
      ctx.moveTo(cx - diag, cy + diag);
      ctx.lineTo(cx + diag, cy - diag);
      ctx.stroke();

      // Mesafe Halkaları (Her 1 metre)
      for (let r = 1; r <= maxMesafe; r++) {
        const rPx = r * scale;
        ctx.beginPath();
        ctx.arc(cx, cy, rPx, 0, Math.PI * 2);
        ctx.strokeStyle = r === maxMesafe ? "rgba(0, 240, 255, 0.4)" : "rgba(30, 41, 59, 0.8)";
        ctx.setLineDash(r % 2 === 0 ? [] : [3, 3]);
        ctx.stroke();

        // Mesafe Metinleri
        ctx.fillStyle = "#64748b";
        ctx.font = "10px monospace";
        ctx.fillText(`${r}m`, cx + rPx + 4, cy - 4);
      }
      ctx.setLineDash([]);

      // Sektör Etiketleri (ÖN, SAĞ, ARKA, SOL)
      ctx.font = "10px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillStyle = "rgba(148, 163, 184, 0.7)";
      ctx.fillText("▲ ÖN", cx - 12, cy - radius + 14);
      ctx.fillText("▼ ARKA", cx - 16, cy + radius - 6);
      ctx.fillText("SOL ◄", cx - radius + 6, cy - 4);
      ctx.fillText("► SAĞ", cx + radius - 34, cy - 4);

      // Kritik Güvenlik Çemberi (< 0.8 metre - Yarı saydam kırmızı)
      const dangerPx = 0.8 * scale;
      ctx.fillStyle = "rgba(239, 68, 68, 0.06)";
      ctx.beginPath();
      ctx.arc(cx, cy, dangerPx, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(239, 68, 68, 0.35)";
      ctx.setLineDash([2, 4]);
      ctx.stroke();
      ctx.setLineDash([]);

      // 3. Dönen Radar Tarama Işını (Sci-Fi Sweep Animation)
      if (taramaIsiniGoster) {
        sweepAngleRef.current = (sweepAngleRef.current + 0.04) % (Math.PI * 2);
        const sweepAng = sweepAngleRef.current;

        // Tarama kuyruğu (gradient dilim)
        const sweepGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
        sweepGrad.addColorStop(0, "rgba(0, 240, 255, 0.15)");
        sweepGrad.addColorStop(1, "rgba(0, 240, 255, 0.01)");

        ctx.fillStyle = sweepGrad;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, radius, sweepAng - 0.45, sweepAng);
        ctx.closePath();
        ctx.fill();

        // Tarama ön çizgisi
        ctx.strokeStyle = "rgba(0, 240, 255, 0.6)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(sweepAng) * radius, cy + Math.sin(sweepAng) * radius);
        ctx.stroke();
      }

      // 4. Canlı LiDAR Nokta Bulutu (RPLIDAR Point Cloud)
      const points = lidarVerisi?.points || [];
      if (points.length > 0) {
        for (let i = 0; i < points.length; i++) {
          const pt = points[i];
          if (!pt) continue;
          const x = pt[0]; // Robot ileri (ROS X)
          const y = pt[1]; // Robot sol (ROS Y)
          const r = pt[2]; // Mesafe metre

          if (r > maxMesafe + 0.5) continue;

          // Ekran koordinatları (X: ekran yatay = -y, Y: ekran dikey = -x)
          // Robot ileri = Ekran Yukarısı (cy - x*scale)
          // Robot sol = Ekran Solu (cx - y*scale)
          const px = cx - y * scale;
          const py = cy - x * scale;

          // Mesafeye göre dinamik renk kodlaması
          if (r < 0.8) {
            // Kritik yakınlık (Kırmızı Parlama)
            ctx.fillStyle = "#ef4444";
            ctx.shadowColor = "#ef4444";
            ctx.shadowBlur = 6;
          } else if (r < 1.6) {
            // Uyarı bölgesi (Sarı / Amber Parlama)
            ctx.fillStyle = "#f59e0b";
            ctx.shadowColor = "#f59e0b";
            ctx.shadowBlur = 3;
          } else {
            // Güvenli alan (Camgöbeği / Zümrüt Parlama)
            ctx.fillStyle = "#00f0ff";
            ctx.shadowColor = "#00f0ff";
            ctx.shadowBlur = 2;
          }

          ctx.beginPath();
          ctx.arc(px, py, 2.2, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.shadowBlur = 0; // Gölge sıfırla
      }

      // 5. Robot Gövdesi ve Kafa Yönü (Merkez)
      // Robot Gövdesi
      ctx.fillStyle = "#1e293b";
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx, cy, 14, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // Robot Kafa Açısı (Gaze Yönü)
      const headYaw = lidarVerisi?.head_desired_deg || 0;
      const headRad = (-headYaw * Math.PI) / 180; // Derece -> radyan
      const headLen = 22;
      ctx.strokeStyle = "#00f0ff";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.sin(headRad) * headLen, cy - Math.cos(headRad) * headLen);
      ctx.stroke();

      // Kafa Görme Görüş Alanı (FOV Konisi)
      ctx.fillStyle = "rgba(0, 240, 255, 0.12)";
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(
        cx,
        cy,
        50,
        -Math.PI / 2 + headRad - Math.PI / 6,
        -Math.PI / 2 + headRad + Math.PI / 6
      );
      ctx.closePath();
      ctx.fill();

      // Robot İleri Ok İkonu
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.moveTo(cx, cy - 8);
      ctx.lineTo(cx - 4, cy + 4);
      ctx.lineTo(cx + 4, cy + 4);
      ctx.closePath();
      ctx.fill();

      // 6. Kayıtlı Devriye Noktaları
      noktalar.forEach((n) => {
        // n.x (cm), n.y (cm) -> metre
        const mx = n.x / 100;
        const my = n.y / 100;
        const px = cx + mx * scale;
        const py = cy - my * scale;

        // Devriye Noktası İğnesi
        ctx.fillStyle = "#eab308";
        ctx.shadowColor = "#eab308";
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.fillStyle = "#fef08a";
        ctx.font = "bold 11px sans-serif";
        ctx.fillText(`📍 ${n.name}`, px + 8, py + 4);
      });

      // 7. Kullanıcının Tıkladığı Yeni Hedef
      if (seciliKonum) {
        const spx = cx + (seciliKonum.x / 100) * scale;
        const spy = cy - (seciliKonum.y / 100) * scale;
        ctx.strokeStyle = "#ef4444";
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(spx, spy, 10, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = "#f87171";
        ctx.font = "11px sans-serif";
        ctx.fillText("Yeni Nokta", spx + 12, spy + 4);
      }

      animFrameRef.current = requestAnimationFrame(ciz);
    }

    animFrameRef.current = requestAnimationFrame(ciz);

    return () => {
      isRunning = false;
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [lidarVerisi, maxMesafe, taramaIsiniGoster, noktalar, seciliKonum]);

  function handleCanvasClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    const radius = Math.min(cx, cy) - 25;
    const scale = radius / maxMesafe;

    const cmX = Math.round(((clickX - cx) / scale) * 100);
    const cmY = Math.round(((cy - clickY) / scale) * 100);

    setSeciliKonum({ x: cmX, y: cmY });
  }

  function handleEkle(e: React.FormEvent) {
    e.preventDefault();
    if (!seciliKonum || !noktaAdi.trim()) return;

    startTransition(async () => {
      const fd = new FormData();
      fd.set("deviceId", deviceId);
      fd.set("name", noktaAdi.trim());
      fd.set("x", String(seciliKonum.x));
      fd.set("y", String(seciliKonum.y));
      await waypointEkle(fd);
      setSeciliKonum(null);
      setNoktaAdi("");
    });
  }

  const sectors = lidarVerisi?.sectors || {};
  const nearestM = lidarVerisi?.nearest_obstacle_m;
  const statusStr = lidarVerisi?.status || (baglantiHatasi ? "BAĞLANTI BEKLENİYOR" : "CANLI");
  const isDanger = nearestM !== null && nearestM !== undefined && nearestM < 0.6;
  const isWarning = nearestM !== null && nearestM !== undefined && nearestM >= 0.6 && nearestM < 1.2;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {/* ── ÜST MÜŞTERİ KARTLARI (KPI PANELİ) ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
          gap: "1rem",
        }}
      >
        {/* Sensör Durumu */}
        <div
          style={{
            background: "rgba(18, 24, 38, 0.75)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "8px",
            padding: "1rem",
            backdropFilter: "blur(10px)",
          }}
        >
          <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>
            LiDAR Radar Durumu
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.4rem" }}>
            <span
              style={{
                width: "10px",
                height: "10px",
                borderRadius: "50%",
                backgroundColor: lidarVerisi?.active ? "#10b981" : "#ef4444",
                boxShadow: lidarVerisi?.active ? "0 0 8px #10b981" : "none",
              }}
            />
            <strong style={{ fontSize: "1.1rem", color: "#f8fafc" }}>
              {lidarVerisi?.active ? "RPLIDAR Canlı" : (baglantiHatasi || "Bekleniyor")}
            </strong>
          </div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.25rem" }}>
            360° Tarama · {lidarVerisi?.scan_hz || 7.3} FPS
          </div>
        </div>

        {/* Güvenlik Koridoru */}
        <div
          style={{
            background: "rgba(18, 24, 38, 0.75)",
            border: `1px solid ${isDanger ? "rgba(239, 68, 68, 0.4)" : isWarning ? "rgba(245, 158, 11, 0.4)" : "rgba(16, 185, 129, 0.3)"}`,
            borderRadius: "8px",
            padding: "1rem",
            backdropFilter: "blur(10px)",
          }}
        >
          <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>
            Güvenlik Koridoru
          </div>
          <div
            style={{
              fontSize: "1.1rem",
              fontWeight: "bold",
              marginTop: "0.4rem",
              color: isDanger ? "#ef4444" : isWarning ? "#f59e0b" : "#10b981",
            }}
          >
            {isDanger ? "🛑 ÇARPIŞMA RİSKİ" : isWarning ? "⚠️ YAKIN ENGEL" : "🛡️ GÜVENLİ (TEMİZ)"}
          </div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.25rem" }}>
            {statusStr}
          </div>
        </div>

        {/* En Yakın Engel */}
        <div
          style={{
            background: "rgba(18, 24, 38, 0.75)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "8px",
            padding: "1rem",
            backdropFilter: "blur(10px)",
          }}
        >
          <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>
            En Yakın Engel
          </div>
          <div style={{ fontSize: "1.25rem", fontWeight: "bold", color: "#f8fafc", marginTop: "0.4rem" }}>
            {nearestM !== null && nearestM !== undefined ? (
              <>
                <span className="mono">{nearestM} m</span>
                <span style={{ fontSize: "0.85rem", color: "#94a3b8", marginLeft: "0.5rem" }}>
                  ({lidarVerisi?.nearest_sector || "Bilinmiyor"})
                </span>
              </>
            ) : (
              <span style={{ color: "#64748b" }}>Engel Yok</span>
            )}
          </div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.25rem" }}>
            Açı: {lidarVerisi?.nearest_obstacle_deg ?? 0}°
          </div>
        </div>

        {/* Lazer Noktaları */}
        <div
          style={{
            background: "rgba(18, 24, 38, 0.75)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "8px",
            padding: "1rem",
            backdropFilter: "blur(10px)",
          }}
        >
          <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>
            Aktif Lazer Yansıması
          </div>
          <div style={{ fontSize: "1.25rem", fontWeight: "bold", color: "#00f0ff", marginTop: "0.4rem" }}>
            {lidarVerisi?.point_count ?? 0} Nokta
          </div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.25rem" }}>
            Toplam Örnek: {lidarVerisi?.total_samples ?? 1080}
          </div>
        </div>
      </div>

      {/* ── 4-BÖLGE GÜVENLİK KALKANI HUD ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "0.75rem",
          padding: "0.75rem",
          background: "rgba(15, 23, 42, 0.5)",
          borderRadius: "8px",
          border: "1px solid rgba(255, 255, 255, 0.05)",
        }}
      >
        {[
          { label: "ÖN", info: sectors.front },
          { label: "SOL", info: sectors.left },
          { label: "SAĞ", info: sectors.right },
          { label: "ARKA", info: sectors.back },
        ].map((sec) => {
          const isClear = sec.info?.clear ?? true;
          const dist = sec.info?.distance_m;
          return (
            <div
              key={sec.label}
              style={{
                textAlign: "center",
                padding: "0.5rem",
                borderRadius: "6px",
                background: isClear ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.12)",
                border: `1px solid ${isClear ? "rgba(16, 185, 129, 0.25)" : "rgba(239, 68, 68, 0.35)"}`,
              }}
            >
              <div style={{ fontSize: "0.75rem", fontWeight: "bold", color: isClear ? "#10b981" : "#ef4444" }}>
                {sec.label} SEKTÖR
              </div>
              <div style={{ fontSize: "1rem", fontWeight: "bold", color: "#f8fafc", margin: "0.2rem 0" }}>
                {dist !== null && dist !== undefined ? `${dist} m` : "Temiz"}
              </div>
              <div style={{ fontSize: "0.7rem", color: isClear ? "#6ee7b7" : "#fca5a5" }}>
                {isClear ? "✓ Engel Yok" : "⚠ Dikkat"}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── ANA RADAR VE SAĞ KONTROL PANELİ ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "1.5rem" }}>
        <div>
          {/* Radar Başlık & Hızlı Düğmeler */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "0.75rem",
            }}
          >
            <div>
              <h2 style={{ fontSize: "1.1rem", margin: 0, fontWeight: 700 }}>
                2D Lazer Radar ve Çevre Krokisi
              </h2>
              <p style={{ fontSize: "0.8rem", color: "#94a3b8", margin: "0.15rem 0 0" }}>
                RPLIDAR 360° lazer ışınları ile ölçülen gerçek engeller ve oda sınırları
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                className={`btn btn--small ${devriyeAktif ? "btn--alarm" : "btn--primary"}`}
                type="button"
                onClick={() => setDevriyeAktif(!devriyeAktif)}
              >
                {devriyeAktif ? "🛑 Devriyeyi Durdur" : "🚀 Otonom Devriye"}
              </button>
            </div>
          </div>

          {/* Radar Canvas Kapsayıcısı */}
          <div
            style={{
              border: "1px solid rgba(0, 240, 255, 0.25)",
              borderRadius: "10px",
              overflow: "hidden",
              position: "relative",
              boxShadow: "0 8px 32px rgba(0, 0, 0, 0.5), inset 0 0 40px rgba(0, 240, 255, 0.03)",
              background: "#070a12",
            }}
          >
            <canvas
              ref={canvasRef}
              width={720}
              height={540}
              style={{
                display: "block",
                width: "100%",
                height: "auto",
                cursor: "crosshair",
              }}
              onClick={handleCanvasClick}
            />

            {/* Radar Üzeri Bilgi Notu */}
            <div
              style={{
                position: "absolute",
                bottom: "10px",
                left: "12px",
                fontSize: "0.75rem",
                color: "rgba(148, 163, 184, 0.8)",
                pointerEvents: "none",
                display: "flex",
                gap: "1rem",
              }}
            >
              <span>🔴 Kırmızı: &lt; 0.8m Engel</span>
              <span>🟡 Sarı: 0.8m - 1.6m</span>
              <span>🔵 Cyan: Güvenli Alan</span>
            </div>
          </div>

          <p className="controls__note" style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
            💡 <strong>Nasıl Kullanılır:</strong> Radar üzerine tıklayarak yeni bir devriye noktası belirleyebilirsiniz.
            Ortadaki mavi daire robotu, ok işareti ise robotun yüz yönünü gösterir.
          </p>
        </div>

        {/* ── SAĞ PANEL: RADAR AYARLARI & DEVRİYE NOKTALARI ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          {/* Görünüm ve Zoom Ayarları */}
          <div
            className="panel"
            style={{
              background: "rgba(18, 24, 38, 0.75)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "1rem",
            }}
          >
            <h3 style={{ margin: "0 0 0.85rem", fontSize: "0.95rem" }}>Radar Görünüm Ayarları</h3>

            {/* Zoom / Menzil Seçimi */}
            <div style={{ marginBottom: "0.85rem" }}>
              <label style={{ fontSize: "0.8rem", color: "#94a3b8", display: "block", marginBottom: "0.35rem" }}>
                Maksimum Menzil (Ölçek)
              </label>
              <div style={{ display: "flex", gap: "0.4rem" }}>
                {[3, 5, 8].map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={`btn btn--small ${maxMesafe === m ? "btn--primary" : "btn--quiet"}`}
                    style={{ flex: 1 }}
                    onClick={() => setMaxMesafe(m)}
                  >
                    {m} Metre
                  </button>
                ))}
              </div>
            </div>

            {/* Tarama Işını Toggle */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "0.5rem 0",
                borderTop: "1px solid rgba(255, 255, 255, 0.05)",
              }}
            >
              <span style={{ fontSize: "0.85rem" }}>Radar Tarama Işını</span>
              <button
                type="button"
                className={`btn btn--small ${taramaIsiniGoster ? "btn--primary" : "btn--quiet"}`}
                onClick={() => setTaramaIsiniGoster(!taramaIsiniGoster)}
              >
                {taramaIsiniGoster ? "Açık" : "Kapalı"}
              </button>
            </div>

            {/* Canlı Akış Toggle */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "0.5rem 0",
                borderTop: "1px solid rgba(255, 255, 255, 0.05)",
              }}
            >
              <span style={{ fontSize: "0.85rem" }}>Canlı Sensör Akışı</span>
              <button
                type="button"
                className={`btn btn--small ${canliAkis ? "btn--primary" : "btn--quiet"}`}
                onClick={() => setCanliAkis(!canliAkis)}
              >
                {canliAkis ? "Aktif" : "Durduruldu"}
              </button>
            </div>
          </div>

          {/* Devriye Noktaları Formu & Listesi */}
          <div
            className="panel"
            style={{
              background: "rgba(18, 24, 38, 0.75)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "1rem",
            }}
          >
            <h3 style={{ margin: "0 0 0.85rem", fontSize: "0.95rem" }}>Devriye Noktaları</h3>

            {seciliKonum && (
              <form
                onSubmit={handleEkle}
                style={{
                  marginBottom: "1rem",
                  padding: "0.75rem",
                  backgroundColor: "#0f172a",
                  borderRadius: "6px",
                  border: "1px solid rgba(0, 240, 255, 0.3)",
                }}
              >
                <p style={{ margin: "0 0 0.4rem", fontSize: "0.85rem", fontWeight: "bold", color: "#38bdf8" }}>
                  📍 Nokta Seçildi: ({seciliKonum.x} cm, {seciliKonum.y} cm)
                </p>
                <input
                  value={noktaAdi}
                  onChange={(e) => setNoktaAdi(e.target.value)}
                  placeholder="Nokta Adı (Örn: Kapı Önü, Masa 1)"
                  style={{
                    width: "100%",
                    padding: "0.5rem",
                    marginBottom: "0.5rem",
                    borderRadius: "4px",
                    border: "1px solid #334155",
                    background: "#1e293b",
                    color: "#f8fafc",
                  }}
                  required
                />
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button className="btn btn--primary btn--small" type="submit" disabled={bekliyor}>
                    {bekliyor ? "Ekleniyor…" : "Kaydet"}
                  </button>
                  <button
                    className="btn btn--quiet btn--small"
                    type="button"
                    onClick={() => setSeciliKonum(null)}
                  >
                    İptal
                  </button>
                </div>
              </form>
            )}

            {noktalar.length === 0 ? (
              <p style={{ fontSize: "0.85rem", color: "#94a3b8", lineHeight: 1.5 }}>
                Henüz kayıtlı nokta yok. Radar üzerine tıklayarak "Giriş", "Masa 1", "Mutfak" gibi noktalar ekleyebilirsiniz.
              </p>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  padding: 0,
                  margin: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                {noktalar.map((n) => (
                  <li
                    key={n.id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "0.6rem 0.75rem",
                      backgroundColor: "#0f172a",
                      borderRadius: "6px",
                      border: "1px solid rgba(255, 255, 255, 0.05)",
                    }}
                  >
                    <div>
                      <strong style={{ fontSize: "0.9rem", color: "#f8fafc" }}>{n.name}</strong>
                      <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.15rem" }}>
                        X: {n.x} cm · Y: {n.y} cm
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn btn--quiet btn--small"
                      style={{ color: "#ef4444" }}
                      onClick={() => {
                        startTransition(async () => {
                          await waypointSil(n.id, deviceId);
                        });
                      }}
                    >
                      Sil
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
