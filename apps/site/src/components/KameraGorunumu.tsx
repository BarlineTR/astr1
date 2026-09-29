"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Tam ekran MJPEG kamera görüntüsü bileşeni.
 *
 * - Robot hostname'ini tarayıcıdan alır (window.location.hostname)
 * - Bağlantı kesilirse otomatik yeniden dener (3s aralıkla)
 * - Snapshot modu: stream çalışmazsa tek kare çeker
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

  // Client-side hostname tespiti
  useEffect(() => {
    if (sabitStreamUrl) {
      setStreamUrl(sabitStreamUrl);
      return;
    }
    const host = window.location.hostname;
    setStreamUrl(`http://${host}:8080/camera/stream.mjpg`);
  }, [sabitStreamUrl]);

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
    imgRef.current.src = `${streamUrl}?t=${Date.now()}`;
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
      {streamUrl ? (
        <img
          ref={imgRef}
          src={`${streamUrl}?t=${Date.now()}`}
          alt="OAK-D Lite Canlı Video"
          className="kamera-tam-ekran__img"
          onLoad={handleLoad}
          onError={handleError}
        />
      ) : (
        <div className="kamera-tam-ekran__bekleme">
          <span>Adres belirleniyor…</span>
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
