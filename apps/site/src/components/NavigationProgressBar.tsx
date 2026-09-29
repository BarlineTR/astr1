"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * Sayfa geçişlerinde ekranın en üstünde zarif altın-pirinç ışıltılı
 * bir ilerleme çubuğu gösterir.
 *
 * Kullanıcı herhangi bir sekmeye veya linke tıkladığı anda görsel geri bildirim
 * anında başlar ("sanki bir şey olmuyor" hissini tamamen yok eder).
 */
export function NavigationProgressBar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);

  // Pathname veya query param değiştiğinde yükleme biter
  useEffect(() => {
    if (loading) {
      setProgress(100);
      const timer = setTimeout(() => {
        setLoading(false);
        setProgress(0);
      }, 240);
      return () => clearTimeout(timer);
    }
  }, [pathname, searchParams]);

  // Global link tıklamalarını yakala
  useEffect(() => {
    const handleAnchorClick = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest("a");
      if (!target) return;

      const href = target.getAttribute("href");
      const targetAttr = target.getAttribute("target");

      // Dış bağlantılar, yeni sekmede açılanlar veya aynı sayfadaki hash linkleri atla
      if (
        !href ||
        href.startsWith("#") ||
        href.startsWith("http") ||
        href.startsWith("mailto:") ||
        href.startsWith("tel:") ||
        targetAttr === "_blank" ||
        e.ctrlKey ||
        e.metaKey
      ) {
        return;
      }

      // Mevcut URL ile aynı değilse yükleme animasyonunu başlat
      const currentUrl = window.location.pathname + window.location.search;
      if (href !== currentUrl) {
        setLoading(true);
        setProgress(25);

        // Kademeli akış simülasyonu
        const t1 = setTimeout(() => setProgress(65), 100);
        const t2 = setTimeout(() => setProgress(85), 300);

        return () => {
          clearTimeout(t1);
          clearTimeout(t2);
        };
      }
    };

    document.addEventListener("click", handleAnchorClick, { capture: true });
    return () => document.removeEventListener("click", handleAnchorClick, { capture: true });
  }, []);

  if (!loading && progress === 0) return null;

  return (
    <div
      aria-hidden="true"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        height: "3px",
        zIndex: 99999,
        pointerEvents: "none",
        backgroundColor: "rgba(200, 161, 90, 0.15)",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${progress}%`,
          backgroundColor: "var(--accent, #c8a15a)",
          boxShadow: "0 0 10px #c8a15a, 0 0 5px #e0bd7c",
          transition: progress === 100 ? "width 150ms ease-out, opacity 150ms ease-out" : "width 250ms cubic-bezier(0.16, 1, 0.3, 1)",
          opacity: progress === 100 ? 0 : 1,
        }}
      />
    </div>
  );
}
