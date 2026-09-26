import { PROTOCOL_VERSION } from "@astro/protocol";

/**
 * Ana sürüm karşılaştırması.
 *
 * Ajan ile ağ geçidi farklı ana sürümdeyse bağlantı anlaşılır bir hatayla
 * reddedilir. Sessizce devam edip yanlış alan okumak, bir robot kontrol
 * sisteminde en kötü davranış.
 */
export function surumUyumlu(karsiTaraf: string): boolean {
  const bizim = PROTOCOL_VERSION.split(".")[0];
  const onlar = karsiTaraf.split(".")[0];
  return bizim === onlar;
}
