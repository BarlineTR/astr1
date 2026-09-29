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

const ROL_ETIKETLERI: Record<string, { ad: string; renk: string; aciklama: string }> = {
  vip: { ad: "VIP Ziyaretçi", renk: "#eab308", aciklama: "Öncelikli karşılama & hürmet" },
  family: { ad: "Aile Üyesi", renk: "#10b981", aciklama: "Tam yetki & ev modu" },
  staff: { ad: "Ofis / Personel", renk: "#3b82f6", aciklama: "Kurumsal çalışma modu" },
  guest: { ad: "Kayıtlı Misafir", renk: "#8b5cf6", aciklama: "Nazik karşılama" },
  blacklist: { ad: "Kara Liste (Alarm)", renk: "#ef4444", aciklama: "Anında alarm & bildirim" },
};

export default async function KisilerSayfasi() {
  const oturum = await oturumGerekli("/panel/kisiler");
  const kisiler = await kullanicininKisileri(oturum.user.id);

  const vipSayisi = kisiler.filter((k) => k.role === "vip").length;
  const familySayisi = kisiler.filter((k) => k.role === "family").length;
  const blacklistSayisi = kisiler.filter((k) => k.role === "blacklist").length;

  return (
    <>
      <div className="pano__baslik pano__baslik--eylemli">
        <div>
          <h1>Kişi Tanımlama & Biyometrik Yüz Veritabanı</h1>
          <p className="pano__lead">
            Robotunuzun kamerası (YuNet tespit + SFace 512-dim gömme motoru) ile tanıyacağı kişileri ve davranış protokollerini yönetin.
          </p>
        </div>
        <KisiEkleFormu />
      </div>

      {/* İstatistik & Biyometrik Özet Şeridi */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: "1rem",
          margin: "1.25rem 0",
        }}
      >
        <div className="panel" style={{ padding: "0.85rem", border: "1px solid var(--rule)" }}>
          <span style={{ fontSize: "0.75rem", color: "var(--ink-muted)", textTransform: "uppercase" }}>
            Tanımlı Kişiler
          </span>
          <p style={{ margin: "0.25rem 0 0", fontSize: "1.4rem", fontWeight: "bold", fontFamily: "var(--font-mono)" }}>
            {kisiler.length}
          </p>
        </div>

        <div className="panel" style={{ padding: "0.85rem", border: "1px solid var(--rule)" }}>
          <span style={{ fontSize: "0.75rem", color: "var(--ink-muted)", textTransform: "uppercase" }}>
            ⭐ VIP & Aile
          </span>
          <p style={{ margin: "0.25rem 0 0", fontSize: "1.4rem", fontWeight: "bold", color: "var(--accent)", fontFamily: "var(--font-mono)" }}>
            {vipSayisi + familySayisi}
          </p>
        </div>

        <div className="panel" style={{ padding: "0.85rem", border: "1px solid var(--rule)" }}>
          <span style={{ fontSize: "0.75rem", color: "var(--ink-muted)", textTransform: "uppercase" }}>
            🚨 Kara Liste / Alarm
          </span>
          <p style={{ margin: "0.25rem 0 0", fontSize: "1.4rem", fontWeight: "bold", color: blacklistSayisi > 0 ? "var(--alarm)" : "var(--ink-muted)", fontFamily: "var(--font-mono)" }}>
            {blacklistSayisi}
          </p>
        </div>

        <div className="panel" style={{ padding: "0.85rem", border: "1px solid var(--rule)" }}>
          <span style={{ fontSize: "0.75rem", color: "var(--ink-muted)", textTransform: "uppercase" }}>
            Yüz Tanıma Modeli
          </span>
          <p style={{ margin: "0.25rem 0 0", fontSize: "0.95rem", fontWeight: 600, color: "var(--ok)", fontFamily: "var(--font-mono)" }}>
            YuNet + SFace
          </p>
        </div>
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
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: "1rem",
            marginTop: "1.25rem",
          }}
        >
          {kisiler.map((k) => {
            const rolBilgi = ROL_ETIKETLERI[k.role] ?? {
              ad: k.role,
              renk: "#71717a",
              aciklama: "Standart profil",
            };

            return (
              <div
                key={k.id}
                className="panel"
                style={{
                  border: "1px solid var(--rule)",
                  borderTop: `3px solid ${rolBilgi.renk}`,
                  padding: "1.1rem",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  gap: "1rem",
                  position: "relative",
                  background: "var(--bg)",
                }}
              >
                <div style={{ display: "flex", alignItems: "flex-start", gap: "0.85rem" }}>
                  {k.photoBase64 ? (
                    <img
                      src={k.photoBase64}
                      alt={k.name}
                      style={{
                        width: "56px",
                        height: "56px",
                        borderRadius: "8px",
                        objectFit: "cover",
                        border: `2px solid ${rolBilgi.renk}`,
                        boxShadow: `0 0 12px ${rolBilgi.renk}33`,
                        flexShrink: 0,
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: "56px",
                        height: "56px",
                        borderRadius: "8px",
                        backgroundColor: "rgba(255, 255, 255, 0.05)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: "bold",
                        fontFamily: "var(--font-mono)",
                        border: `2px solid ${rolBilgi.renk}`,
                        color: rolBilgi.renk,
                        fontSize: "1.1rem",
                        flexShrink: 0,
                      }}
                    >
                      {k.name.slice(0, 2).toUpperCase()}
                    </div>
                  )}

                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
                      <h2 style={{ fontSize: "1.05rem", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {k.name}
                      </h2>
                    </div>

                    <span
                      style={{
                        display: "inline-block",
                        marginTop: "0.3rem",
                        padding: "0.2rem 0.5rem",
                        borderRadius: "4px",
                        fontSize: "0.72rem",
                        fontWeight: 600,
                        backgroundColor: `${rolBilgi.renk}18`,
                        color: rolBilgi.renk,
                        border: `1px solid ${rolBilgi.renk}33`,
                      }}
                    >
                      {rolBilgi.ad}
                    </span>

                    <p
                      style={{
                        margin: "0.5rem 0 0",
                        fontSize: "0.82rem",
                        color: "var(--ink-muted)",
                        lineHeight: 1.4,
                      }}
                    >
                      {k.notes ? `“${k.notes}”` : "Özel karşılama notu girilmedi."}
                    </p>
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    paddingTop: "0.75rem",
                    borderTop: "1px solid var(--rule)",
                    fontSize: "0.75rem",
                    color: "var(--ink-muted)",
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                    <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--ok)" }} />
                    Biyometri Aktif
                  </span>

                  <KisiSilDugmesi id={k.id} name={k.name} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
