"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { waypointEkle, waypointSil } from "@/app/panel/harita/actions";

interface Waypoint {
  id: string;
  name: string;
  x: number;
  y: number;
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

  // Canvas çizimi: 2D Radar/LiDAR Odası Krokisi
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const scale = 25; // 25 px = 1 metre

    // Arka plan
    ctx.fillStyle = "#09090b";
    ctx.fillRect(0, 0, w, h);

    // Grid (1 metre aralıklı)
    ctx.strokeStyle = "#18181b";
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += scale) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += scale) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // LiDAR Mesafe Halkaları (2m, 4m, 6m, 8m)
    ctx.strokeStyle = "#27272a";
    ctx.setLineDash([4, 4]);
    [2, 4, 6, 8].forEach((r) => {
      ctx.beginPath();
      ctx.arc(cx, cy, r * scale, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "#52525b";
      ctx.font = "10px monospace";
      ctx.fillText(`${r}m`, cx + r * scale + 2, cy - 4);
    });
    ctx.setLineDash([]);

    // Temsili LiDAR Taranan Duvarlar / Engeller (Sanal Oda Krokisi)
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 2;
    ctx.strokeRect(cx - 7 * scale, cy - 5 * scale, 14 * scale, 10 * scale);

    // İç Duvar / Bölme
    ctx.beginPath();
    ctx.moveTo(cx - 1 * scale, cy - 5 * scale);
    ctx.lineTo(cx - 1 * scale, cy - 1 * scale);
    ctx.stroke();

    // Robot Konumu ve Bakış Açısı (Merkez)
    ctx.fillStyle = "#3b82f6";
    ctx.beginPath();
    ctx.arc(cx, cy, 10, 0, Math.PI * 2);
    ctx.fill();

    // Robot Yön Göstergesi (FOV Konisi)
    ctx.fillStyle = "rgba(59, 130, 246, 0.2)";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, 60, -Math.PI / 4, Math.PI / 4);
    ctx.closePath();
    ctx.fill();

    // Robot Merkez Noktası
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, Math.PI * 2);
    ctx.fill();

    // Kayıtlı Devriye Noktaları
    noktalar.forEach((n) => {
      const px = cx + (n.x / 100) * scale;
      const py = cy - (n.y / 100) * scale;

      ctx.fillStyle = "#eab308";
      ctx.beginPath();
      ctx.arc(px, py, 6, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#fef08a";
      ctx.font = "12px sans-serif";
      ctx.fillText(n.name, px + 8, py + 4);
    });

    // Kullanıcının Tıkladığı Yeni Nokta
    if (seciliKonum) {
      const spx = cx + (seciliKonum.x / 100) * scale;
      const spy = cy - (seciliKonum.y / 100) * scale;
      ctx.strokeStyle = "#ef4444";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(spx, spy, 8, 0, Math.PI * 2);
      ctx.stroke();
    }
  }, [noktalar, seciliKonum]);

  function handleCanvasClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    const scale = 25; // 25 px = 1m = 100cm

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

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "1.5rem" }}>
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
          <p className="eyebrow" style={{ margin: 0 }}>LiDAR 2D Ortam Haritası (Occupancy Grid)</p>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              className={`btn btn--small ${devriyeAktif ? "btn--alarm" : "btn--primary"}`}
              type="button"
              onClick={() => setDevriyeAktif(!devriyeAktif)}
            >
              {devriyeAktif ? "🛑 Devriyeyi Durdur" : "🚀 Otonom Devriye Başlat"}
            </button>
          </div>
        </div>

        <div style={{ border: "1px solid var(--color-border, #333)", borderRadius: "8px", overflow: "hidden", position: "relative" }}>
          <canvas
            ref={canvasRef}
            width={640}
            height={480}
            style={{ display: "block", width: "100%", height: "auto", cursor: "crosshair" }}
            onClick={handleCanvasClick}
          />
        </div>
        <p className="controls__note" style={{ marginTop: "0.5rem" }}>
          💡 Kroki üzerine tıklayarak yeni bir devriye noktası belirleyebilir veya robotu yönlendirebilirsiniz. Yeşil çizgiler LiDAR engel algısını, mavi daire robotu temsil eder.
        </p>
      </div>

      <div className="panel" style={{ border: "1px solid var(--color-border, #333)", borderRadius: "8px", padding: "1rem" }}>
        <h3 style={{ margin: "0 0 1rem" }}>Devriye Noktaları</h3>

        {seciliKonum && (
          <form onSubmit={handleEkle} style={{ marginBottom: "1.25rem", padding: "0.75rem", backgroundColor: "#18181b", borderRadius: "6px" }}>
            <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", fontWeight: "bold" }}>
              Nokta Seçildi: ({seciliKonum.x} cm, {seciliKonum.y} cm)
            </p>
            <input
              value={noktaAdi}
              onChange={(e) => setNoktaAdi(e.target.value)}
              placeholder="Nokta Adı (Örn: Kapı Önü)"
              style={{ width: "100%", padding: "0.4rem", marginBottom: "0.5rem" }}
              required
            />
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn btn--primary btn--small" type="submit" disabled={bekliyor}>
                {bekliyor ? "Ekleniyor…" : "Kaydet"}
              </button>
              <button className="btn btn--quiet btn--small" type="button" onClick={() => setSeciliKonum(null)}>
                İptal
              </button>
            </div>
          </form>
        )}

        {noktalar.length === 0 ? (
          <p style={{ fontSize: "0.9rem", color: "var(--color-muted, #a1a1aa)" }}>
            Henüz kaydedilmiş nokta yok. Krokiye tıklayarak "Salon", "Giriş", "Mutfak" gibi noktalar ekleyebilirsiniz.
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {noktalar.map((n) => (
              <li
                key={n.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "0.5rem",
                  backgroundColor: "#18181b",
                  borderRadius: "6px",
                  fontSize: "0.9rem",
                }}
              >
                <div>
                  <strong>{n.name}</strong>
                  <div style={{ fontSize: "0.75rem", color: "var(--color-muted, #a1a1aa)" }}>
                    X: {n.x}cm, Y: {n.y}cm
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn--quiet btn--small"
                  style={{ color: "var(--color-alarm, #ef4444)" }}
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
  );
}
