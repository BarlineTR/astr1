import Link from "next/link";
import { KimlikKabuk } from "@/components/KimlikKabuk";
import { DogrulamaTekrarFormu } from "@/components/DogrulamaTekrarFormu";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "E-posta Doğrulaması Gerekli",
  aciklama: "Hesabınızı etkinleştirmek için lütfen e-posta adresinizi doğrulayın.",
  yol: "/dogrulama-bekleniyor",
  dizinleme: false,
});

export default async function DogrulamaBekleniyorSayfasi({
  searchParams,
}: {
  searchParams: Promise<{ eposta?: string }>;
}) {
  const params = await searchParams;
  const eposta = params.eposta ?? "";

  return (
    <KimlikKabuk
      baslik="E-posta Doğrulaması Gerekli"
      lead="Robot kontrol paneline ve cihaz yönetimine erişmek için e-posta adresinizi doğrulamanız gerekmektedir."
      altYazi={
        <>
          Zaten doğruladınız mı? <Link href="/giris">Giriş yapın</Link>
        </>
      }
    >
      <div className="dogrulama-karti" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <p>
          {eposta ? (
            <>
              <strong className="mono">{eposta}</strong> adresine bir doğrulama bağlantısı gönderdik.
            </>
          ) : (
            "Kayıtlı e-posta adresinize bir doğrulama bağlantısı gönderdik."
          )}
        </p>
        <p style={{ color: "var(--color-muted, #a1a1aa)", fontSize: "0.9rem" }}>
          Gelen kutunuzu (ve spam/gereksiz klasörünü) kontrol ederek bağlantıya tıklayın. Doğrulama tamamlandıktan sonra robot yönetim panelinize erişebilirsiniz.
        </p>

        {eposta && <DogrulamaTekrarFormu eposta={eposta} />}
      </div>
    </KimlikKabuk>
  );
}
