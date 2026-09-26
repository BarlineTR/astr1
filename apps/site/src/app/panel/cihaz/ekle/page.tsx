import { RobotEkleFormu } from "@/components/RobotEkleFormu";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Robot ekle",
  aciklama: "Hesabınıza yeni bir robot bağlayın.",
  yol: "/panel",
  dizinleme: false,
});

export default async function RobotEkleSayfasi() {
  await oturumGerekli("/panel/cihaz/ekle");

  return (
    <>
      <div className="pano__baslik">
        <h1>Robot ekle</h1>
        <p className="pano__lead">
          Robotu hesabınıza tanıtın. Ekledikten sonra size bir eşleştirme kodu
          verilir; robot üzerindeki ajan bu kodla bağlanır.
        </p>
      </div>

      <div className="pano__dar">
        <RobotEkleFormu />
      </div>
    </>
  );
}
