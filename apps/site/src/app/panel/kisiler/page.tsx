import Link from "next/link";
import { kullanicininKisileri } from "@/db/sorgular/kisiler";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";
import { KisiEkleFormu } from "@/components/KisiEkleFormu";
import { KisiSilDugmesi } from "@/components/KisiSilDugmesi";

export const metadata = sayfaMetadata({
  baslik: "Kişi Tanımlama & VIP Listesi",
  aciklama: "Robotun yüz tanıma motoru için tanımlı kişiler ve yetkiler.",
  yol: "/panel",
  dizinleme: false,
});

const ROL_ETIKETLERI: Record<string, { ad: string; renk: string }> = {
  vip: { ad: "VIP Ziyaretçi", renk: "#eab308" },
  family: { ad: "Aile Üyesi", renk: "#10b981" },
  staff: { ad: "Ofis / Personel", renk: "#3b82f6" },
  guest: { ad: "Kayıtlı Misafir", renk: "#8b5cf6" },
  blacklist: { ad: "Kara Liste (Alarm)", renk: "#ef4444" },
};

export default async function KisilerSayfasi() {
  const oturum = await oturumGerekli("/panel/kisiler");
  const kisiler = await kullanicininKisileri(oturum.user.id);

  return (
    <>
      <div className="pano__baslik pano__baslik--eylemli">
        <div>
          <h1>Kişi Tanımlama & Yüz Veritabanı</h1>
          <p className="pano__lead">
            Robotunuzun kamerasından (YuNet + SFace algılayıcı) tanıyacağı kişileri yönetin.
          </p>
        </div>
        <KisiEkleFormu />
      </div>

      {kisiler.length === 0 ? (
        <div className="bos-durum">
          <p className="eyebrow">Henüz tanımlı kişi yok</p>
          <p>
            Robotunuz şu an çevresindeki herkesi anonim olarak görüyor ve takip ediyor.
            Kişi ekleyerek robota özel karşılama, selamlama ve güvenlik kuralları atayabilirsiniz.
          </p>
        </div>
      ) : (
        <ul className="cihaz-listesi" style={{ marginTop: "1.5rem" }}>
          {kisiler.map((k) => {
            const rolBilgi = ROL_ETIKETLERI[k.role] ?? { ad: k.role, renk: "#71717a" };
            return (
              <li
                key={k.id}
                className="cihaz"
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                  {k.photoBase64 ? (
                    <img
                      src={k.photoBase64}
                      alt={k.name}
                      style={{
                        width: "48px",
                        height: "48px",
                        borderRadius: "50%",
                        objectFit: "cover",
                        border: `2px solid ${rolBilgi.renk}`,
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: "48px",
                        height: "48px",
                        borderRadius: "50%",
                        backgroundColor: "#27272a",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: "bold",
                        border: `2px solid ${rolBilgi.renk}`,
                      }}
                    >
                      {k.name.slice(0, 2).toUpperCase()}
                    </div>
                  )}
                  <div>
                    <h2 className="cihaz__ad" style={{ fontSize: "1.1rem", margin: 0 }}>
                      {k.name}
                    </h2>
                    <p style={{ margin: "0.2rem 0 0", fontSize: "0.85rem", color: "var(--color-muted, #a1a1aa)" }}>
                      {k.notes ? `“${k.notes}”` : "Özel not girilmedi"}
                    </p>
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                  <span
                    style={{
                      padding: "0.25rem 0.6rem",
                      borderRadius: "999px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      backgroundColor: `${rolBilgi.renk}22`,
                      color: rolBilgi.renk,
                      border: `1px solid ${rolBilgi.renk}44`,
                    }}
                  >
                    {rolBilgi.ad}
                  </span>
                  <KisiSilDugmesi id={k.id} name={k.name} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
