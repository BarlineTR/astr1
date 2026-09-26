import { ImageResponse } from "next/og";

import { KURUM } from "@/data/kurum";

export const alt = "ASTRO — sosyal robot platformu";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Paylaşım görseli kodla üretilir.
 *
 * Ayrı bir PNG dosyası tutmak, marka ya da ürün adı değiştiğinde güncellenmeyen
 * bir kopya demekti. Renkler `tokens.css` ile aynı: zemin #0a0a0b, vurgu
 * #c8a15a.
 */
export default function OgGorsel() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#0a0a0b",
          padding: "72px",
          color: "#e9e7e2",
          fontFamily: "Georgia, serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <span style={{ fontSize: 34, letterSpacing: "0.22em" }}>{KURUM.kisaAd}</span>
          <span style={{ fontSize: 20, color: "#c8a15a" }}>V1</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          <div style={{ width: "120px", height: "2px", background: "#c8a15a" }} />
          <div style={{ fontSize: 76, lineHeight: 1.05, maxWidth: "900px" }}>
            Konuşanı duyar, bakanı görür, ona döner.
          </div>
          <div style={{ fontSize: 26, color: "#9a978f" }}>Sosyal robot platformu</div>
        </div>
      </div>
    ),
    size,
  );
}
