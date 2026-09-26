import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "Yönetim" };

export default function Sayfa() {
  return <YakindaSayfa current="hakkimizda" baslik="Yönetim" aciklama="Yönetim ekibi." />;
}
