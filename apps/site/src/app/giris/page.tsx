import Link from "next/link";
import { Suspense } from "react";

import { GirisFormu } from "@/components/GirisFormu";
import { KimlikKabuk } from "@/components/KimlikKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Giriş",
  aciklama: "ASTRO paneline giriş.",
  yol: "/giris",
  dizinleme: false,
});

export default function GirisSayfasi() {
  return (
    <KimlikKabuk
      baslik="Giriş"
      lead="Cihazlarınızı ve hesabınızı yönetmek için giriş yapın."
      altYazi={
        <>
          Hesabınız yok mu? <Link href="/kayit">Hesap oluşturun</Link>
        </>
      }
    >
      {/* useSearchParams kullanan form; Suspense olmadan sayfa statik üretilemiyor. */}
      <Suspense fallback={null}>
        <GirisFormu />
      </Suspense>
    </KimlikKabuk>
  );
}
