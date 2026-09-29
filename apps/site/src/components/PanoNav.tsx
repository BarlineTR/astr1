"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname } from "next/navigation";
import { useState, useTransition } from "react";

interface Sekme {
  href: Route;
  label: string;
  badge?: string;
}

const SEKMELER: Sekme[] = [
  { href: "/panel", label: "Cihazlar" },
  { href: "/panel/kisiler", label: "Kişiler" },
  { href: "/panel/harita" as Route, label: "Harita & Devriye" },
  { href: "/panel/ayarlar", label: "Ayarlar" },
  { href: "/panel/abonelik", label: "Abonelik" },
  { href: "/panel/faturalar", label: "Faturalar" },
  { href: "/panel/hesap", label: "Hesap" },
];

export function PanoNav() {
  const pathname = usePathname();
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const handleTabClick = (href: string) => {
    if (href !== pathname) {
      setPendingHref(href);
      startTransition(() => {
        // Geçiş tamamlandığında pending state temizlenecek
      });
    }
  };

  return (
    <nav className="pano__nav" aria-label="Panel">
      {SEKMELER.map((sekme) => {
        const isCurrent =
          sekme.href === "/panel"
            ? pathname === "/panel" || pathname.startsWith("/panel/cihaz")
            : pathname.startsWith(sekme.href);
        const isPending = pendingHref === sekme.href && !isCurrent;

        return (
          <Link
            key={sekme.href}
            href={sekme.href}
            onClick={() => handleTabClick(sekme.href)}
            className={`pano__sekme ${isCurrent ? "is-current" : ""} ${isPending ? "is-pending" : ""}`}
            aria-current={isCurrent ? "page" : undefined}
          >
            <span className="pano__sekme-metin">{sekme.label}</span>
            {isPending && <span className="pano__sekme-spinner" aria-hidden="true" />}
            {isCurrent && <span className="pano__sekme-cizgi" aria-hidden="true" />}
          </Link>
        );
      })}
    </nav>
  );
}
