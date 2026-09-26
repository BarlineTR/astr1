import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "Gizlilik politikası" };

export default function Sayfa() {
  return <YakindaSayfa current="hakkimizda" baslik="Gizlilik politikası" aciklama="Hangi veriyi neden topluyoruz." />;
}
