import { z } from "zod";

/**
 * İletişim ve teklif formu.
 *
 * Doğrulama **sunucuda** yapılır; istemci tarafındaki kontrol yalnızca hızlı
 * geri bildirim içindir ve atlanabilir.
 */
export const iletisimSchema = z
  .object({
    tur: z.enum(["iletisim", "teklif"]),
    ad: z.string().trim().min(2, "Adınızı yazın.").max(120),
    eposta: z.email("Geçerli bir e-posta adresi yazın.").max(200),
    sirket: z.string().trim().max(160).optional(),
    telefon: z.string().trim().max(40).optional(),
    mesaj: z
      .string()
      .trim()
      .min(20, "Biraz daha ayrıntı yazar mısınız?")
      .max(5000, "Mesaj çok uzun."),
    kvkkOnay: z.boolean(),
    kaynakSayfa: z.string().max(200).optional(),
    /*
     * Tuzak alan (honeypot). Gerçek kullanıcı bu alanı görmez ve doldurmaz;
     * dolu gelen istek bir bottan gelmiştir. CAPTCHA'sız, JavaScript
     * gerektirmeyen ve kullanıcıyı hiç yormayan bir filtre.
     */
    website: z.string().max(0, "Bu alan boş bırakılmalı.").optional(),
  })
  .refine((d) => d.kvkkOnay, {
    message: "Devam etmek için KVKK aydınlatma metnini onaylamanız gerekiyor.",
    path: ["kvkkOnay"],
  })
  .refine((d) => d.tur !== "teklif" || (d.sirket?.length ?? 0) > 1, {
    message: "Teklif talebi için kurum adı gerekiyor.",
    path: ["sirket"],
  });

export type IletisimGirdi = z.infer<typeof iletisimSchema>;
