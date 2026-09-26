import type { CerceveKaydi } from "@/console/gecit-baglantisi";

/**
 * Giden ve gelen çerçevelerin günlüğü.
 *
 * Bir kontrol arayüzünde "gönderdim ama gitti mi?" sorusunun cevabı görünür
 * olmalı. Telemetri çerçeveleri buraya yazılmıyor — saniyede onlarca gelip
 * günlüğü kullanılamaz hale getiriyorlardı; onların yeri durum tablosu.
 */
export function CerceveGunlugu({ kayitlar }: { kayitlar: readonly CerceveKaydi[] }) {
  if (kayitlar.length === 0) {
    return <p className="gunluk__bos">Henüz çerçeve alışverişi yok.</p>;
  }

  return (
    <ol className="gunluk">
      {kayitlar.map((k, i) => (
        <li className={`gunluk__satir gunluk__satir--${k.yon}`} key={`${k.t}-${i}`}>
          <span className="gunluk__saat mono">
            {new Date(k.t).toLocaleTimeString("tr-TR", { hour12: false })}
          </span>
          <span className="gunluk__yon mono">{k.yon === "giden" ? "→" : "←"}</span>
          <span className="gunluk__tur mono">{k.tur}</span>
          <span className="gunluk__ozet">{k.ozet}</span>
        </li>
      ))}
    </ol>
  );
}
