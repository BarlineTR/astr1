import type { Metadata, Viewport } from "next";

import "@astro/ui/styles/tokens.css";
import "@astro/ui/styles/base.css";
import "@astro/ui/styles/layout.css";
import "@astro/ui/styles/sayfa.css";
import "@astro/ui/styles/form.css";
import "@astro/ui/styles/console.css";

import { KURUM } from "@/data/kurum";

import { mono, serif, ui } from "./fonts";

export const metadata: Metadata = {
  metadataBase: new URL(KURUM.siteUrl),
  title: {
    default: "ASTRO — sosyal robot platformu",
    template: "%s — ASTRO",
  },
  description:
    "ASTRO; çevresindeki insanları gören, duyan ve kiminle ilgileneceğine kendi " +
    "karar veren bir robot platformudur.",
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0a0a0b",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" className={`${serif.variable} ${ui.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
