import type { Command } from "@astro/protocol";
import { commandSchema } from "@astro/protocol/schema";

export type ParseResult =
  | { ok: true; command: Command }
  | { ok: false; message: string };

/**
 * Soket üzerinden gelen ham metni komuta çevirir.
 *
 * Fırlatmaz: WebSocket dinleyicisinin içinde atılan bir hata bağlantıyı
 * düşürürdü ve operatör bunu "robot koptu" olarak görürdü. Hata bir değer
 * olarak dönüyor ve istemciye anlaşılır bir mesaj gidiyor.
 *
 * Sınır ihlalinde komut kırpılarak kabul edilmez, reddedilir — sessizce kırpmak
 * operatöre gönderdiği komutun uygulandığını düşündürür.
 */
export function parseCommand(raw: string): ParseResult {
  let govde: unknown;
  try {
    govde = JSON.parse(raw);
  } catch {
    return { ok: false, message: "Komut çözümlenemedi" };
  }

  const sonuc = commandSchema.safeParse(govde);
  if (!sonuc.success) {
    return { ok: false, message: "Komut sözleşmeye uymuyor" };
  }
  return { ok: true, command: sonuc.data };
}
