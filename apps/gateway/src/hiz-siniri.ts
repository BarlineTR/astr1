/**
 * Kayan pencereli hız sınırı.
 *
 * Komut yolunda gerekli: kaydırıcıyı hızlı sürükleyen bir arayüz saniyede
 * onlarca komut üretebiliyor ve bunların robota olduğu gibi gitmesi hem
 * gereksiz hem de motor sürücüsünü yoruyor. Ayrıca jetonu ele geçiren birinin
 * komut yağdırmasını da sınırlıyor.
 */
export class HizSiniri {
  private readonly damgalar: number[] = [];

  constructor(
    private readonly limit: number,
    private readonly pencereMs: number,
  ) {}

  /** Komut kabul edilebilir mi. Kabul edilirse pencereye yazılır. */
  izinVer(simdi = Date.now()): boolean {
    const esik = simdi - this.pencereMs;
    while (this.damgalar.length > 0 && this.damgalar[0]! < esik) this.damgalar.shift();

    if (this.damgalar.length >= this.limit) return false;
    this.damgalar.push(simdi);
    return true;
  }
}
