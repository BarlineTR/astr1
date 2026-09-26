import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "Platform" };

export default function Sayfa() {
  return <YakindaSayfa current="platform" baslik="Platform" aciklama="ASTRO V1'in yetenekleri, çalışma sınırları ve teknik verileri." />;
}
