import Link from "next/link";

import { KayitFormu } from "@/components/KayitFormu";
import { KimlikKabuk } from "@/components/KimlikKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Hesap oluştur",
  aciklama: "ASTRO paneli için hesap oluşturun.",
  yol: "/kayit",
  dizinleme: false,
});

export default function KayitSayfasi() {
  return (
    <KimlikKabuk
      baslik="Hesap oluştur"
      lead="Panele erişmek ve cihazlarınızı bağlamak için."
      altYazi={
        <>
          Hesabınız var mı? <Link href="/giris">Giriş yapın</Link>
        </>
      }
    >
      <KayitFormu />
    </KimlikKabuk>
  );
}
