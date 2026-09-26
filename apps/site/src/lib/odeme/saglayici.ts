/**
 * Ödeme sağlayıcısı arayüzü.
 *
 * Tasarım belgesi §9: kod hiçbir yerde `iyzipay`i doğrudan çağırmaz, yalnızca
 * bu arayüzü çağırır. Uluslararası tahsilat kararı ertelendiği için (Stripe
 * Türkiye'ye merchant hesabı vermiyor) ikinci bir sağlayıcı eklemek tek dosya
 * olmalı.
 */

export interface SepetKalemi {
  slug: string;
  ad: string;
  birimKurus: number;
  adet: number;
}

export interface Alici {
  id: string;
  ad: string;
  soyad: string;
  eposta: string;
  /** Ters vekil arkasında X-Forwarded-For'dan gelir. */
  ip: string;
  telefon?: string;
  adres?: string;
  sehir?: string;
  ulke?: string;
}

export interface OdemeBaslatGirdi {
  siparisId: string;
  conversationId: string;
  toplamKurus: number;
  paraBirimi: string;
  kalemler: readonly SepetKalemi[];
  alici: Alici;
  /** Sağlayıcının sonucu bildireceği mutlak adres. */
  geriDonusUrl: string;
}

export interface OdemeBaslatSonuc {
  ok: boolean;
  /** Sağlayıcı oturum kimliği; sonucu almak için saklanır. */
  token?: string;
  /** Kullanıcının yönlendirileceği ödeme sayfası. */
  odemeSayfasiUrl?: string;
  hata?: string;
}

export interface OdemeSonucu {
  ok: boolean;
  /** Sağlayıcıdaki ödeme kimliği; idempotensi buna dayanır. */
  odemeId?: string;
  durum: "basarili" | "basarisiz" | "bilinmiyor";
  tutarKurus?: number;
  paraBirimi?: string;
  conversationId?: string;
  kartAilesi?: string;
  kartSonDort?: string;
  hata?: string;
  ham: unknown;
}

export interface OdemeSaglayici {
  readonly id: string;
  /** Gerçek para hareket ediyor mu. Arayüzde uyarı çizmek için. */
  readonly canli: boolean;
  odemeBaslat(girdi: OdemeBaslatGirdi): Promise<OdemeBaslatSonuc>;
  sonucuAl(token: string): Promise<OdemeSonucu>;
}
