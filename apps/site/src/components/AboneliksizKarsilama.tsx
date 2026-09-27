import Link from "next/link";
import { PLANLAR } from "@/data/fiyatlar";
import { kurusBicimle } from "@/lib/para";
import { SatinAlDugmesi } from "@/components/SatinAlDugmesi";

const OZELLIKLER = [
  {
    ikon: "🎥",
    baslik: "3B Sosyal Bakış & Kafa Takibi",
    aciklama:
      "Çift mikrofon ses yönü (DoA) ve kamera ile konuşan kişiyi 50 Hz döngüyle takip eden motorize kafa kontrolü.",
  },
  {
    ikon: "🗺️",
    baslik: "LiDAR 2D Ortam Haritası & Devriye",
    aciklama:
      "RPLiDAR lazer tarayıcı ile odanın anlık 2D krokisini çıkarma, harita üzerinde tıklayarak hedef noktalar belirleme.",
  },
  {
    ikon: "👤",
    baslik: "VIP Yüz Tanıma & Kişi Veritabanı",
    aciklama:
      "YuNet + SFace yapay zeka motoru ile misafirleri, aile üyelerini ve personeli tanıyıp kişiye özel selamlama yapma.",
  },
  {
    ikon: "🗣️",
    baslik: "Doğal Ses & Karakter (TTS / LLM)",
    aciklama:
      "Ayarlanabilir konuşma hızı, ses tonu ve OpenAI / XTTS dil modeli promptlarıyla robot kişiliğini özelleştirme.",
  },
  {
    ikon: "🚨",
    baslik: "Güvenlik & Anomali Alarmları",
    aciklama:
      "Tanınmayan şahıs algılandığında veya mesai dışı hareketlerde güvenlik e-postasına anlık fotoğraflı uyarı gönderme.",
  },
  {
    ikon: "🌐",
    baslik: "Dış Ağ Güvenli Ağ Geçidi",
    aciklama:
      "Müşteri lokasyonunda port açmaya gerek kalmadan, çift yönlü şifreli WebSocket ile dünyanın her yerinden kontrol.",
  },
];

export function AboneliksizKarsilama() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
      <div className="pano__baslik">
        <h1>Hoş Geldiniz — ASTRO V1 Robot Yönetim Platformu</h1>
        <p className="pano__lead">
          Robotunuzu uzaktan yönetmek, canlı telemetriyi izlemek ve gelişmiş yapay zeka modüllerini kullanmak için lütfen bir erişim planı seçin.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: "2rem", alignItems: "start" }}>
        {/* Sol Kolon: Platform Özellikleri */}
        <section className="panel" style={{ border: "1px solid var(--color-border, #333)", borderRadius: "8px", padding: "1.5rem" }}>
          <div style={{ marginBottom: "1.25rem", borderBottom: "1px solid #27272a", paddingBottom: "0.75rem" }}>
            <span className="eyebrow">Yetenekler</span>
            <h2 style={{ fontSize: "1.35rem", margin: "0.25rem 0" }}>Platform Özellikleri</h2>
            <p style={{ fontSize: "0.9rem", color: "var(--color-muted, #a1a1aa)", margin: 0 }}>
              Aktif aboneliğinizle birlikte kullanıma açılacak profesyonel robot yetenekleri:
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
            {OZELLIKLER.map((o) => (
              <div key={o.baslik} style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
                <span style={{ fontSize: "1.5rem", lineHeight: 1 }}>{o.ikon}</span>
                <div>
                  <h3 style={{ fontSize: "1rem", margin: 0, fontWeight: 600 }}>{o.baslik}</h3>
                  <p style={{ fontSize: "0.85rem", color: "var(--color-muted, #a1a1aa)", margin: "0.2rem 0 0", lineHeight: 1.4 }}>
                    {o.aciklama}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Sağ Kolon: Fiyatlandırma & Planlar */}
        <section className="panel" style={{ border: "1px solid var(--color-border, #333)", borderRadius: "8px", padding: "1.5rem", backgroundColor: "#121214" }}>
          <div style={{ marginBottom: "1.25rem", borderBottom: "1px solid #27272a", paddingBottom: "0.75rem" }}>
            <span className="eyebrow">Abonelik</span>
            <h2 style={{ fontSize: "1.35rem", margin: "0.25rem 0" }}>Erişim Planları & Fiyatlandırma</h2>
            <p style={{ fontSize: "0.9rem", color: "var(--color-muted, #a1a1aa)", margin: 0 }}>
              İhtiyacınıza uygun planı seçip anında robotunuzu bağlayabilirsiniz:
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
            {PLANLAR.map((plan) => (
              <article
                key={plan.slug}
                className="fiyat-karti"
                style={{
                  border: plan.slug === "operasyon" ? "2px solid #3b82f6" : "1px solid #27272a",
                  position: "relative",
                  borderRadius: "8px",
                  padding: "1.25rem",
                  backgroundColor: "#18181b",
                }}
              >
                {plan.slug === "operasyon" && (
                  <span
                    style={{
                      position: "absolute",
                      top: "-10px",
                      right: "12px",
                      backgroundColor: "#3b82f6",
                      color: "#fff",
                      fontSize: "0.7rem",
                      fontWeight: "bold",
                      padding: "2px 8px",
                      borderRadius: "4px",
                    }}
                  >
                    ÖNERİLEN
                  </span>
                )}

                <h3 className="fiyat-karti__ad" style={{ fontSize: "1.2rem", margin: "0 0 0.4rem" }}>
                  {plan.ad}
                </h3>
                <p className="fiyat-karti__tutar mono" style={{ fontSize: "1.5rem", margin: "0 0 0.5rem" }}>
                  {kurusBicimle(plan.fiyatKurus)}
                  <span className="fiyat-karti__periyot" style={{ fontSize: "0.9rem", color: "#a1a1aa" }}> / ay</span>
                </p>
                <p className="fiyat-karti__aciklama" style={{ fontSize: "0.85rem", color: "#d4d4d8", margin: "0 0 1rem" }}>
                  {plan.aciklama}
                </p>

                {plan.ozellikler && (
                  <ul className="liste" style={{ fontSize: "0.85rem", margin: "0 0 1.25rem", paddingLeft: "1.2rem" }}>
                    {plan.ozellikler.map((o) => (
                      <li key={o} style={{ marginBottom: "0.25rem" }}>
                        {o}
                      </li>
                    ))}
                  </ul>
                )}

                <SatinAlDugmesi slug={plan.slug} etiket={`${plan.ad} Planını Başlat`} />
              </article>
            ))}
          </div>

          <div style={{ marginTop: "1.5rem", padding: "1rem", backgroundColor: "#18181b", borderRadius: "6px", border: "1px dashed #3f3f46" }}>
            <h4 style={{ margin: "0 0 0.3rem", fontSize: "0.95rem" }}>🏢 Kurumsal veya Çoklu Robot Kullanımı</h4>
            <p style={{ fontSize: "0.8rem", color: "#a1a1aa", margin: "0 0 0.75rem" }}>
              Özel API erişimi, yerinde entegrasyon ve filo yönetimi için teklif hazırlıyoruz.
            </p>
            <Link className="btn btn--quiet btn--small" href="/iletisim">
              Kurumsal Teklif İste
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}
