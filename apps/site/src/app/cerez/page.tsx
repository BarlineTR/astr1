import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "Çerez politikası" };

export default function Sayfa() {
  return <YakindaSayfa current="hakkimizda" baslik="Çerez politikası" aciklama="Çerez kullanımı." />;
}
