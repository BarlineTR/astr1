/**
 * Jeton doğrulama.
 *
 * Ağ geçidi cihaz kayıtlarını tutmuyor; onlar sitenin veritabanında. Bağlantı
 * kurulurken **bir kez** siteye sorulur ve sonuç o bağlantı boyunca geçerli
 * sayılır. Her çerçevede sormak saçma olurdu; hiç sormamak ise iptal edilen bir
 * cihazın bağlanmaya devam etmesi demekti.
 *
 * Sunucudan sunucuya çağrı paylaşılan bir sırla imzalanır. İleride bu yerini
 * imzalı jetona bırakabilir (o zaman site çağrısı hiç gerekmez), ama o kurulum
 * iptali de ayrıca çözmeyi gerektiriyor.
 */

export interface CihazDogrulama {
  ok: true;
  cihazId: string;
  serial: string;
}

export interface PanelDogrulama {
  ok: true;
  cihazId: string;
  kullaniciId: string;
  komutVerebilir: boolean;
}

export type DogrulamaSonuc<T> = T | { ok: false; neden: string };

const SITE_URL = process.env.SITE_URL ?? "http://localhost:3000";
const GECIT_SIRRI = process.env.GATEWAY_SHARED_SECRET ?? "";

async function siteyeSor(
  govde: Record<string, unknown>,
): Promise<Record<string, unknown> | null> {
  if (!GECIT_SIRRI) {
    // Sırsız çalışmak, doğrulamayı tamamen atlamak demek olurdu.
    throw new Error(
      "GATEWAY_SHARED_SECRET tanımlı değil; ağ geçidi jeton doğrulayamaz.",
    );
  }

  const yanit = await fetch(`${SITE_URL}/api/gecit/dogrula`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-gecit-sirri": GECIT_SIRRI,
    },
    body: JSON.stringify(govde),
    signal: AbortSignal.timeout(5000),
  });

  if (!yanit.ok) return null;
  return (await yanit.json()) as Record<string, unknown>;
}

export async function cihazDogrula(
  token: string,
): Promise<DogrulamaSonuc<CihazDogrulama>> {
  try {
    const yanit = await siteyeSor({ tur: "cihaz", token });
    if (!yanit || yanit.ok !== true) {
      return { ok: false, neden: "Cihaz jetonu geçersiz ya da iptal edilmiş." };
    }
    return {
      ok: true,
      cihazId: String(yanit.cihazId),
      serial: String(yanit.serial ?? ""),
    };
  } catch (hata) {
    // Site erişilemezse bağlantı kabul edilmez: "emin değilim" reddetmektir.
    return { ok: false, neden: `Doğrulama yapılamadı: ${String(hata)}` };
  }
}

export async function panelDogrula(
  token: string,
): Promise<DogrulamaSonuc<PanelDogrulama>> {
  try {
    const yanit = await siteyeSor({ tur: "panel", token });
    if (!yanit || yanit.ok !== true) {
      return { ok: false, neden: "Panel jetonu geçersiz ya da süresi geçmiş." };
    }
    return {
      ok: true,
      cihazId: String(yanit.cihazId),
      kullaniciId: String(yanit.kullaniciId),
      komutVerebilir: yanit.komutVerebilir === true,
    };
  } catch (hata) {
    return { ok: false, neden: `Doğrulama yapılamadı: ${String(hata)}` };
  }
}
