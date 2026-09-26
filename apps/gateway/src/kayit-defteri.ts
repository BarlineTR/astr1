import type { Telemetry } from "@astro/protocol";

/**
 * Bağlı cihazların ve onları izleyen panellerin defteri.
 *
 * Bellekte tutuluyor ve bilerek öyle: ağ geçidi durumsuz bir röle. Yeniden
 * başladığında robotlar kendiliğinden yeniden bağlanır (dışa doğru bağlantı
 * kurdukları için) ve paneller de yeniden bağlanır. Kalıcı bir durum tutmak,
 * gerçekle uyuşmayan bir "bağlı" kaydı riski demekti.
 */

export interface CihazBaglantisi {
  cihazId: string;
  firmware: string | null;
  baglandi: number;
  sonGorulme: number;
  /** Robota çerçeve yollar. */
  gonder(cerceve: unknown): void;
  kapat(kod: number, neden: string): void;
}

export interface PanelBaglantisi {
  cihazId: string;
  kullaniciId: string;
  komutVerebilir: boolean;
  gonder(cerceve: unknown): void;
}

export class KayitDefteri {
  private readonly cihazlar = new Map<string, CihazBaglantisi>();
  private readonly paneller = new Map<string, Set<PanelBaglantisi>>();
  /** Son telemetri: yeni bağlanan panel boş ekran görmesin. */
  private readonly sonTelemetri = new Map<string, { payload: Telemetry; t: number }>();

  cihazBagla(baglanti: CihazBaglantisi): void {
    /*
     * Aynı cihaz ikinci kez bağlanırsa eskisi kapatılır. İki ajanın aynı anda
     * telemetri basması, panelde iki gerçeğin karışması demek.
     */
    const eski = this.cihazlar.get(baglanti.cihazId);
    if (eski && eski !== baglanti) {
      eski.kapat(4000, "Aynı cihaz başka bir yerden bağlandı");
    }
    this.cihazlar.set(baglanti.cihazId, baglanti);
    this.durumYayinla(baglanti.cihazId);
  }

  cihazAyril(cihazId: string, baglanti: CihazBaglantisi): void {
    // Yalnızca hâlâ kayıtlı olan bağlantı silinir: yerine yenisi geldiyse
    // eskinin kapanışı yeniyi düşürmemeli.
    if (this.cihazlar.get(cihazId) === baglanti) {
      this.cihazlar.delete(cihazId);
      this.durumYayinla(cihazId);
    }
  }

  cihazAl(cihazId: string): CihazBaglantisi | undefined {
    return this.cihazlar.get(cihazId);
  }

  panelBagla(panel: PanelBaglantisi): void {
    const kume = this.paneller.get(panel.cihazId) ?? new Set();
    kume.add(panel);
    this.paneller.set(panel.cihazId, kume);

    // Yeni panel önce durumu, sonra varsa son telemetriyi alır.
    panel.gonder(this.durumCercevesi(panel.cihazId));
    const son = this.sonTelemetri.get(panel.cihazId);
    if (son) {
      panel.gonder({ kind: "gecit.telemetri", payload: son.payload, t: son.t });
    }
  }

  panelAyril(panel: PanelBaglantisi): void {
    const kume = this.paneller.get(panel.cihazId);
    if (!kume) return;
    kume.delete(panel);
    if (kume.size === 0) this.paneller.delete(panel.cihazId);
  }

  telemetriDagit(cihazId: string, payload: Telemetry): void {
    const t = Date.now();
    this.sonTelemetri.set(cihazId, { payload, t });

    const cihaz = this.cihazlar.get(cihazId);
    if (cihaz) cihaz.sonGorulme = t;

    this.panellereYolla(cihazId, { kind: "gecit.telemetri", payload, t });
  }

  panellereYolla(cihazId: string, cerceve: unknown): void {
    for (const panel of this.paneller.get(cihazId) ?? []) panel.gonder(cerceve);
  }

  durumCercevesi(cihazId: string) {
    const cihaz = this.cihazlar.get(cihazId);
    return {
      kind: "gecit.cihaz-durum" as const,
      bagli: Boolean(cihaz),
      sonGorulme: cihaz?.sonGorulme ?? this.sonTelemetri.get(cihazId)?.t ?? null,
      firmware: cihaz?.firmware ?? null,
    };
  }

  private durumYayinla(cihazId: string): void {
    this.panellereYolla(cihazId, this.durumCercevesi(cihazId));
  }

  /** Sağlık ucu için özet. */
  ozet() {
    return {
      bagliCihaz: this.cihazlar.size,
      acikPanel: [...this.paneller.values()].reduce((t, k) => t + k.size, 0),
    };
  }
}
