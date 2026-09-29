"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Tam ekran MJPEG kamera görüntüsü bileşeni.
 *
 * - Doğrudan Next.js API proxy'si (/api/kamera) veya robot :8080 portunu kullanır
 * - Bağlantı kesilirse otomatik yeniden dener (3s aralıkla)
 * - Tarayıcı kırık resim simgesi göstermez; temiz offline HUD render eder
 * - Siyah arka plan, aspect-ratio korunan görüntü
 */
export function KameraGorunumu({
  cihazId: _cihazId,
  sabitStreamUrl,
}: {
  cihazId: string;
  sabitStreamUrl: string | null;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [durum, setDurum] = useState<"baglaniyor" | "canli" | "hata">("baglaniyor");
  const [yeniden, setYeniden] = useState(0);
  const [streamUrl, setStreamUrl] = useState<string>("");

  // Stream URL tespiti: Sabit URL yoksa önce /api/kamera proxy'si kullanılır
  useEffect(() => {
    if (sabitStreamUrl) {
      setStreamUrl(sabitStreamUrl);
      return;
    }
    // Varsayılan: Yerel Next.js /api/kamera endpoint'i
    // Eğer 1 defadan fazla hata alındıysa doğrudan port 8080'i dener
    if (yeniden >= 2 && typeof window !== "undefined") {
      const host = window.location.hostname;
      setStreamUrl(`http://${host}:8080/camera/stream.mjpg`);
    } else {
      setStreamUrl("/api/kamera");
    }
  }, [sabitStreamUrl, yeniden]);

  // Stream yüklenince canlı
  const handleLoad = () => setDurum("canli");

  // Hata → 3sn sonra yeniden dene
  const handleError = () => {
    setDurum("hata");
    const t = setTimeout(() => {
      setYeniden((n) => n + 1);
      setDurum("baglaniyor");
    }, 3000);
    return () => clearTimeout(t);
  };

  // yeniden sayacı değişince src'yi sıfırla
  useEffect(() => {
    if (!streamUrl || !imgRef.current) return;
    imgRef.current.src = `${streamUrl}${streamUrl.includes("?") ? "&" : "?"}t=${Date.now()}`;
  }, [yeniden, streamUrl]);

  return (
    <div className="kamera-tam-ekran">
      {/* Durum rozeti */}
      <div className="kamera-tam-ekran__hud">
        {durum === "baglaniyor" && (
          <span className="badge">⏳ Bağlanıyor…</span>
        )}
        {durum === "canli" && (
          <span className="badge badge--live">
            <span className="badge__dot" />
            Canlı · OAK-D Lite
          </span>
        )}
        {durum === "hata" && (
          <span className="badge badge--alarm">
            ⚠️ Sinyal yok — yeniden deneniyor…
          </span>
        )}
      </div>

      {/* Kamera görüntüsü */}
      {streamUrl && (
        <img
          ref={imgRef}
          src={`${streamUrl}${streamUrl.includes("?") ? "&" : "?"}t=${Date.now()}`}
          alt="OAK-D Lite Canlı Video"
          className="kamera-tam-ekran__img"
          style={{ display: durum === "canli" ? "block" : "none" }}
          onLoad={handleLoad}
          onError={handleError}
        />
      )}

      {/* Temiz Offline / Bağlanıyor HUD Katmanı (Kırık resim ikonunu gizler) */}
      {durum !== "canli" && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "0.5rem",
            color: "#71717a",
            textAlign: "center",
            padding: "2rem",
          }}
        >
          <div style={{ fontSize: "2.5rem", opacity: 0.7 }}>📡</div>
          <div
            style={{
              fontFamily: "monospace",
              fontSize: "0.95rem",
              letterSpacing: "0.08em",
              color: "#a1a1aa",
              textTransform: "uppercase",
            }}
          >
            {durum === "baglaniyor" ? "Kamera Akışı Başlatılıyor" : "Kamera Sinyali Alınamıyor"}
          </div>
          <div style={{ fontSize: "0.8rem", color: "#52525b", maxWidth: "340px" }}>
            {durum === "baglaniyor"
              ? "Görüntü sunucusuna bağlanılıyor, lütfen bekleyin..."
              : "Yayın akışı henüz aktif değil veya kamera hazır değil. 3 saniye içinde otomatik yeniden denenecek."}
          </div>
        </div>
      )}

      {/* Alt bilgi */}
      <div className="kamera-tam-ekran__alt">
        <span className="mono" style={{ fontSize: "0.7rem", opacity: 0.5 }}>
          {streamUrl}
        </span>
      </div>
    </div>
  );
}
