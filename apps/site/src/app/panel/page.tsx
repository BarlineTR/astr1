import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "Panel" };

export default function Sayfa() {
  return <YakindaSayfa current="panel" baslik="Panel" aciklama="Cihazlarınız ve hesabınız." />;
}
