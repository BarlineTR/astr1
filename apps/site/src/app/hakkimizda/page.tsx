import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "Hakkımızda" };

export default function Sayfa() {
  return <YakindaSayfa current="hakkimizda" baslik="Hakkımızda" aciklama="Nasıl başladı, nasıl çalışıyoruz." />;
}
