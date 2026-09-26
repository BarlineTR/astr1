"use client";

import { useActionState } from "react";

import {
  cihaziSil,
  koduYenile,
  type CihazIslemSonuc,
} from "@/app/panel/cihaz/[id]/actions";

const BASLANGIC: CihazIslemSonuc | null = null;

/**
 * Cihaz yönetimi: eşleştirme kodu ve silme.
 *
 * İki ayrı form, tek bileşen: ikisi de aynı cihaza ait ve ayrı sayfalara
 * bölmek kullanıcıyı gezdirmekten başka işe yaramıyordu.
 */
export function CihazYonetimi({
  cihazId,
  seri,
  kodGecerliMi,
}: {
  cihazId: string;
  seri: string;
  kodGecerliMi: boolean;
}) {
  const [kodDurum, kodYenile, kodBekliyor] = useActionState(koduYenile, BASLANGIC);
  const [silDurum, sil, silBekliyor] = useActionState(cihaziSil, BASLANGIC);

  return (
    <>
      <section className="pano__bolum">
        <h2 className="pano__bolum-baslik">Eşleştirme</h2>

        {kodDurum?.kod ? (
          <div className="eslestirme__kutu">
            <p className="eyebrow">Eşleştirme kodu</p>
            <p className="eslestirme__kod mono">{kodDurum.kod}</p>
            <p className="eslestirme__not">
              Bu kod <strong>yalnızca bir kez</strong> gösteriliyor. Kodu yenilemek
              cihazın önceki bağlantı jetonunu da geçersiz kıldı; ajanın yeniden
              bağlanması gerekiyor.
            </p>
          </div>
        ) : (
          <p className="pano__lead">
            {kodGecerliMi
              ? "Bu cihazın geçerli bir eşleştirme kodu var. Kodu kaybettiyseniz yenisini üretebilirsiniz — eski kod ve varsa mevcut bağlantı jetonu geçersiz olur."
              : "Bu cihazın geçerli bir eşleştirme kodu yok. Ajanı yeniden bağlamak için yeni bir kod üretin."}
          </p>
        )}

        {kodDurum?.hata && (
          <p className="form__hata" role="alert">
            {kodDurum.hata}
          </p>
        )}

        <form action={kodYenile}>
          <input type="hidden" name="cihazId" value={cihazId} />
          <button className="btn" type="submit" disabled={kodBekliyor}>
            {kodBekliyor ? "Üretiliyor…" : "Kodu yenile"}
          </button>
        </form>
      </section>

      <section className="pano__bolum pano__bolum--tehlikeli">
        <h2 className="pano__bolum-baslik">Cihazı sil</h2>
        <p className="pano__lead">
          Cihaz listenizden kalkar ve bağlantı jetonu geçersiz olur. Denetim
          kayıtları silinmez — kimin ne zaman ne yaptığı kaydı cihazla birlikte
          silinirse denetimin anlamı kalmaz.
        </p>

        {silDurum?.hata && (
          <p className="form__hata" role="alert">
            {silDurum.hata}
          </p>
        )}

        <form className="form" action={sil}>
          <input type="hidden" name="cihazId" value={cihazId} />
          <div className="form__alan">
            {/* Tek tıkla silinen bir cihaz, yanlışlıkla silinen bir cihazdır. */}
            <label htmlFor="onay">
              Silmek için seri numarasını yazın: <code className="mono">{seri}</code>
            </label>
            <input id="onay" type="text" name="onay" autoComplete="off" required />
          </div>
          <button className="btn btn--alarm" type="submit" disabled={silBekliyor}>
            {silBekliyor ? "Siliniyor…" : "Cihazı sil"}
          </button>
        </form>
      </section>
    </>
  );
}
