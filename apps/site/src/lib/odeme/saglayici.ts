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
  /** Tek seferlik mi, aylık mı. Yalnızca gösterim için. */
  periyot?: "tek" | "ay";
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

/* ────────────────────────────  Abonelik  ──────────────────────────── */

export interface AbonelikBaslatGirdi {
  abonelikId: string;
  conversationId: string;
  /** Sağlayıcıdaki fiyat planı referansı. */
  planRef: string;
  planAdi: string;
  fiyatKurus: number;
  alici: Alici;
  geriDonusUrl: string;
}

export interface AbonelikBaslatSonuc {
  ok: boolean;
  token?: string;
  odemeSayfasiUrl?: string;
  hata?: string;
}

export type AbonelikDurumu = "bekliyor" | "aktif" | "odenmedi" | "iptal" | "bitti";

export interface AbonelikSonucu {
  ok: boolean;
  /** Sağlayıcıdaki abonelik referansı; iptal ve sorgu bununla yapılır. */
  abonelikRef?: string;
  durum: AbonelikDurumu;
  /** Bir sonraki yenileme (ms, epoch). */
  donemSonu?: number;
  conversationId?: string;
  hata?: string;
  ham: unknown;
}

/**
 * Tekrarlayan tahsilat yapabilen sağlayıcı.
 *
 * Ayrı bir arayüz: iyzico'da abonelik ayrı bir ürün ve hesapta ayrıca
 * etkinleştirilmesi gerekiyor. Tek seferlik ödeme çalışırken aboneliğin
 * çalışmaması olağan bir durum ve tip bunu yansıtmalı.
 */
export interface AbonelikSaglayici {
  abonelikBaslat(girdi: AbonelikBaslatGirdi): Promise<AbonelikBaslatSonuc>;
  abonelikSonucuAl(token: string): Promise<AbonelikSonucu>;
  abonelikDurumAl(abonelikRef: string): Promise<AbonelikSonucu>;
  abonelikIptal(abonelikRef: string): Promise<{ ok: boolean; hata?: string }>;
}

/** Sağlayıcı abonelik destekliyor mu. */
export function abonelikDestekliyorMu(
  s: OdemeSaglayici,
): s is OdemeSaglayici & AbonelikSaglayici {
  return typeof (s as Partial<AbonelikSaglayici>).abonelikBaslat === "function";
}
