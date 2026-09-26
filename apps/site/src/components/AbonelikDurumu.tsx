"use client";

import { useActionState } from "react";

import { abonelikIptal, type IptalSonuc } from "@/app/panel/abonelik/actions";
import { kurusBicimle } from "@/lib/para";

const BASLANGIC: IptalSonuc | null = null;

const DURUM_ADI: Record<string, string> = {
  bekliyor: "ödeme bekleniyor",
  aktif: "aktif",
  odenmedi: "ödeme alınamadı",
  iptal: "iptal edildi",
  bitti: "sona erdi",
};

/**
 * Aktif abonelik kartı.
 *
 * Yenileme tarihi her zaman görünür: kullanıcı ne zaman tekrar çekileceğini
 * bilmeli. Bilmediği bir tarihte kartından para çekilmesi, aboneliğin en sık
 * şikâyet edilen yanı.
 */
export function AbonelikDurumu({
  planAdi,
  fiyatKurus,
  durum,
  donemSonu,
  iptalEdildi,
}: {
  planAdi: string;
  fiyatKurus: number;
  durum: string;
  donemSonu: string | null;
  iptalEdildi: boolean;
}) {
  const [sonuc, iptal, bekliyor] = useActionState(abonelikIptal, BASLANGIC);

  return (
    <div className="abonelik-karti">
      <div className="abonelik-karti__ust">
        <div>
          <h3 className="fiyat-karti__ad">{planAdi}</h3>
          <p className="fiyat-karti__tutar mono">
            {kurusBicimle(fiyatKurus)}
            <span className="fiyat-karti__periyot"> / ay</span>
          </p>
        </div>
        <span
          className={
            iptalEdildi
              ? "badge badge--mock"
              : durum === "aktif"
                ? "badge badge--live"
                : "badge badge--mock"
          }
        >
          {/* İptal edilmiş ama dönemi süren abonelik hâlâ "aktif" durumda. */}
          {iptalEdildi ? "dönem sonunda bitiyor" : (DURUM_ADI[durum] ?? durum)}
        </span>
      </div>

      {donemSonu && (
        <p className="pano__not">
          {iptalEdildi ? (
            <>
              Aboneliğiniz iptal edildi. Erişiminiz{" "}
              <strong>{donemSonu}</strong> tarihine kadar sürüyor — ödediğiniz dönem
              sonuna kadar kullanmaya devam edebilirsiniz.
            </>
          ) : (
            <>
              Bir sonraki tahsilat: <strong>{donemSonu}</strong>
            </>
          )}
        </p>
      )}

      {durum === "odenmedi" && (
        <p className="form__hata" role="alert">
          Son tahsilat alınamadı. Kartınızı güncellemeniz gerekebilir; aksi hâlde
          abonelik kısa süre içinde sona erer.
        </p>
      )}

      {sonuc?.hata && (
        <p className="form__hata" role="alert">
          {sonuc.hata}
        </p>
      )}

      {!iptalEdildi && durum !== "iptal" && durum !== "bitti" && (
        <form action={iptal}>
          <button className="btn btn--alarm" type="submit" disabled={bekliyor}>
            {bekliyor ? "İptal ediliyor…" : "Aboneliği iptal et"}
          </button>
        </form>
      )}
    </div>
  );
}
