import type { BaglantiDurumu } from "@/console/gecit-baglantisi";
import { GECIKME_ESIGI_MS } from "@/console/gecit-baglantisi";

const DURUM_METNI: Record<BaglantiDurumu, string> = {
  baglaniyor: "ağ geçidine bağlanılıyor…",
  yetkileniyor: "yetki alınıyor…",
  bagli: "bağlantı kuruldu",
  "robot-yok": "robot bağlı değil",
  kopuk: "bağlantı koptu",
  hata: "bağlantı hatası",
};

const DURUM_SINIFI: Record<BaglantiDurumu, string> = {
  baglaniyor: "badge",
  yetkileniyor: "badge",
  bagli: "badge badge--live",
  "robot-yok": "badge badge--mock",
  kopuk: "badge badge--alarm",
  hata: "badge badge--alarm",
};

/**
 * Bağlantı durumu şeridi.
 *
 * Durum her zaman görünür olmak zorunda: bağlantı yokken son bilinen değeri
 * canlı gibi göstermek, operatöre olmayan bir robotu yönettiğini düşündürür.
 * Gecikme de burada, çünkü eşiği aşınca hareket komutları reddediliyor ve
 * kullanıcının nedenini görebilmesi gerekiyor.
 */
export function BaglantiSeridi({
  durum,
  ayrinti,
  gecikmeMs,
  sonGorulme,
  firmware,
}: {
  durum: BaglantiDurumu;
  ayrinti?: string;
  gecikmeMs: number | null;
  sonGorulme: number | null;
  firmware: string | null;
}) {
  const yuksekGecikme = gecikmeMs !== null && gecikmeMs > GECIKME_ESIGI_MS;

  return (
    <div className="baglanti">
      <span className={DURUM_SINIFI[durum]}>{DURUM_METNI[durum]}</span>

      {gecikmeMs !== null && (
        <span className={yuksekGecikme ? "baglanti__olcu is-uyari" : "baglanti__olcu"}>
          gecikme <strong className="mono">{gecikmeMs} ms</strong>
          {yuksekGecikme && ` — ${GECIKME_ESIGI_MS} ms üstünde hareket komutu gönderilmez`}
        </span>
      )}

      {firmware && (
        <span className="baglanti__olcu">
          firmware <strong className="mono">{firmware}</strong>
        </span>
      )}

      {durum === "robot-yok" && sonGorulme && (
        <span className="baglanti__olcu">
          son görülme{" "}
          <strong className="mono">
            {new Date(sonGorulme).toLocaleTimeString("tr-TR")}
          </strong>
        </span>
      )}

      {ayrinti && <span className="baglanti__ayrinti">{ayrinti}</span>}
    </div>
  );
}
