"use client";

import { useActionState, useState } from "react";
import { kisiKaydet, type KisiKaydetSonuc } from "@/app/panel/kisiler/actions";

export function KisiEkleFormu() {
  const [acik, setAcik] = useState(false);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [durum, eylem, bekliyor] = useActionState<KisiKaydetSonuc | null, FormData>(
    async (prev, form) => {
      const res = await kisiKaydet(prev, form);
      if (res?.ok) {
        setAcik(false);
        setPhotoPreview(null);
      }
      return res;
    },
    null,
  );

  function handlePhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setPhotoPreview(reader.result as string);
    };
    reader.readAsDataURL(file);
  }

  if (!acik) {
    return (
      <button className="btn btn--primary" type="button" onClick={() => setAcik(true)}>
        + Yeni Kişi Tanımla
      </button>
    );
  }

  return (
    <div className="panel" style={{ marginTop: "1rem", border: "1px solid var(--color-border, #333)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h3>Robot Kişi ve Yüz Tanımlama</h3>
        <button className="btn btn--quiet btn--small" type="button" onClick={() => setAcik(false)}>
          Kapat
        </button>
      </div>

      <form action={eylem} className="form">
        {durum?.hata && (
          <p className="form__hata" role="alert">
            {durum.hata}
          </p>
        )}

        <div className="form__alan">
          <label htmlFor="name">Ad Soyad / Unvan *</label>
          <input id="name" name="name" required placeholder="Örn: Ahmet Bey (Yönetici) veya Selin (Aile)" />
        </div>

        <div className="form__alan">
          <label htmlFor="role">Kişi Rolü / Yetki Seviyesi</label>
          <select id="role" name="role" defaultValue="vip" style={{ padding: "0.5rem", borderRadius: "4px" }}>
            <option value="vip">⭐ VIP (Öncelikli karşılama ve özel hitap)</option>
            <option value="family">🏠 Aile Üyesi (Tam yetki & ev modu)</option>
            <option value="staff">💼 Personel / Ofis Çalışanı</option>
            <option value="guest">👋 Misafir / Ziyaretçi</option>
            <option value="blacklist">🚫 Kara Liste (Anında sesli/e-posta alarm)</option>
          </select>
        </div>

        <div className="form__alan">
          <label htmlFor="notes">Robot Özel Davranış Notu / Selamlama Cümlesi</label>
          <input id="notes" name="notes" placeholder="Örn: 'Hoş geldiniz Ahmet Bey, toplantı odası hazır.'" />
        </div>

        <div className="form__alan">
          <label htmlFor="photo">Yüz Fotoğrafı (İsteğe bağlı — YuNet & SFace ile eşleşir)</label>
          <input id="photo" type="file" accept="image/*" onChange={handlePhoto} />
          {photoPreview && (
            <div style={{ marginTop: "0.5rem" }}>
              <img
                src={photoPreview}
                alt="Önizleme"
                style={{ width: "80px", height: "80px", objectFit: "cover", borderRadius: "8px", border: "1px solid #444" }}
              />
              <input type="hidden" name="photoBase64" value={photoPreview} />
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: "0.75rem", marginTop: "1rem" }}>
          <button className="btn btn--primary" type="submit" disabled={bekliyor}>
            {bekliyor ? "Kaydediliyor…" : "Kaydet ve Robota Eşitle"}
          </button>
          <button className="btn btn--quiet" type="button" onClick={() => setAcik(false)}>
            Vazgeç
          </button>
        </div>
      </form>
    </div>
  );
}
