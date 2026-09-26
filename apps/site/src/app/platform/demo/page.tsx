import { YakindaSayfa } from "@/components/YakindaSayfa";

export const metadata = { title: "Konsol demosu" };

export default function Sayfa() {
  return <YakindaSayfa current="platform" baslik="Konsol demosu" aciklama="Kontrol konsolunun tarayıcı içinde koşan gösterimi." />;
}
