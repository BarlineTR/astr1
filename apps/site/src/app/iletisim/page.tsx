import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "İletişim" };

export default function Sayfa() {
  return <YakindaSayfa current="iletisim" baslik="İletişim" aciklama="Sorular, iş birliği ve teklif talepleri." />;
}
