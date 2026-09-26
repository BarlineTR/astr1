/**
 * Hukuki metinler — **YER TUTUCU** (`docs/RISKLER.md` R2).
 *
 * Hiçbiri hukukçu onayından geçmedi ve sayfalar bunu kendi üstlerinde söylüyor.
 * Ödeme fazı bu metinler onaylanmadan yayına çıkmaz.
 *
 * Sürüm numarası önemli: onay kayıtları buna referans veriyor. Metin
 * değiştiğinde sürüm artmalı, yoksa eski onayların hangi metne verildiği
 * kaybolur ve onay ispatlanamaz hale gelir.
 */
export const KVKK_METIN_SURUMU = "2026-09-26-taslak";

/** Metinler onaylanana kadar sayfalarda uyarı çizilir. */
export const HUKUKI_YER_TUTUCU = true;

export interface HukukiMetin {
  readonly slug: string;
  readonly baslik: string;
  readonly surum: string;
  readonly bolumler: ReadonlyArray<{ baslik: string; paragraflar: readonly string[] }>;
}

const SURUM = KVKK_METIN_SURUMU;

export const HUKUKI_METINLER: Record<string, HukukiMetin> = {
  kvkk: {
    slug: "kvkk",
    baslik: "KVKK aydınlatma metni",
    surum: SURUM,
    bolumler: [
      {
        baslik: "Veri sorumlusu",
        paragraflar: [
          "Kişisel verileriniz, 6698 sayılı Kişisel Verilerin Korunması Kanunu kapsamında veri sorumlusu sıfatıyla işlenmektedir. Kurumsal künye bilgileri iletişim sayfasında yer almaktadır.",
        ],
      },
      {
        baslik: "İşlenen veriler ve amaçları",
        paragraflar: [
          "Hesap oluşturduğunuzda ad, e-posta adresi ve isteğe bağlı olarak kurum ve telefon bilgileriniz; oturum yönetimi, hizmet sunumu ve destek amacıyla işlenir.",
          "İletişim veya teklif formu doldurduğunuzda verdiğiniz bilgiler yalnızca talebinizi yanıtlamak için kullanılır.",
          "Panel üzerinden gerçekleştirilen işlemler güvenlik ve hesap verebilirlik amacıyla denetim kaydına yazılır; kayıt kim, hangi cihazda, ne zaman, hangi işlemi yaptı bilgisini içerir.",
        ],
      },
      {
        baslik: "Robot üzerindeki veriler",
        paragraflar: [
          "Robot üzerinde çalışan yüz ve ses tanıma modelleri cihaz üzerinde çalışır; görüntü ve ses verisi varsayılan olarak cihaz dışına çıkarılmaz.",
          "Uzaktan görüntü aktarımı özelliği etkinleştirildiğinde işlenen veri biyometrik veri niteliği taşır ve ayrıca açık rızanız alınır.",
        ],
      },
      {
        baslik: "Haklarınız",
        paragraflar: [
          "Kanunun 11. maddesi uyarınca verilerinize erişme, düzeltilmesini, silinmesini veya anonim hale getirilmesini isteme haklarına sahipsiniz. Talepleriniz için iletişim sayfasındaki adresten bize ulaşabilirsiniz.",
          "Silme talebinde hesabınıza ait kayıtlar gerçekten silinir; denetim kayıtlarında yalnızca kimliksizleştirilmiş iz kalır.",
        ],
      },
    ],
  },

  gizlilik: {
    slug: "gizlilik",
    baslik: "Gizlilik politikası",
    surum: SURUM,
    bolumler: [
      {
        baslik: "Hangi veriyi topluyoruz",
        paragraflar: [
          "Hesap bilgileriniz, iletişim talepleriniz ve panel üzerindeki işlem kayıtlarınız. Bunların dışında davranışsal reklam veya profilleme amacıyla veri toplamıyoruz.",
        ],
      },
      {
        baslik: "Nerede saklanıyor",
        paragraflar: [
          "Veriler barındırma sağlayıcımızın sunucularında tutulur. Sunucu konumu ve sağlayıcı bilgisi talep üzerine paylaşılır.",
        ],
      },
      {
        baslik: "Üçüncü taraflar",
        paragraflar: [
          "E-posta bildirimleri için bir e-posta sağlayıcısı kullanılır. Ödeme altyapısı devreye alındığında ödeme sağlayıcısı bilgileri bu metne eklenecektir.",
        ],
      },
    ],
  },

  cerez: {
    slug: "cerez",
    baslik: "Çerez politikası",
    surum: SURUM,
    bolumler: [
      {
        baslik: "Kullandığımız çerezler",
        paragraflar: [
          "Site yalnızca oturum çerezi kullanır: giriş yaptığınızda oturumunuzu sürdürmek için. Bu çerez zorunludur ve olmadan panel çalışmaz.",
          "Reklam, izleme veya üçüncü taraf analiz çerezi kullanılmamaktadır. Bu nedenle bir çerez onay penceresi göstermiyoruz.",
        ],
      },
    ],
  },

  kosullar: {
    slug: "kosullar",
    baslik: "Kullanım koşulları",
    surum: SURUM,
    bolumler: [
      {
        baslik: "Hizmetin kapsamı",
        paragraflar: [
          "Bu site ASTRO sosyal robot platformunun tanıtımını yapar ve kayıtlı kullanıcılara cihaz izleme paneli sunar.",
        ],
      },
      {
        baslik: "Hesap güvenliği",
        paragraflar: [
          "Hesap bilgilerinizin gizliliğinden siz sorumlusunuz. Hesabınızla yapılan işlemler denetim kaydına yazılır.",
        ],
      },
      {
        baslik: "Uzaktan kontrol ve güvenlik",
        paragraflar: [
          "Uzaktan kontrol özelliği, robotun bulunduğu ortamın güvenliğinden sorumlu bir kişinin gözetiminde kullanılmalıdır. Panel üzerinden verilen acil durdurma komutu ek bir güvenlik katmanıdır; hareket sınırlarını zorlayan asıl katman cihaz üzerindeki gömülü yazılımdır.",
        ],
      },
    ],
  },

  "mesafeli-satis": {
    slug: "mesafeli-satis",
    baslik: "Mesafeli satış sözleşmesi",
    surum: SURUM,
    bolumler: [
      {
        baslik: "Taraflar ve konu",
        paragraflar: [
          "Bu sözleşme, satıcı ile alıcı arasında elektronik ortamda kurulan satışın koşullarını düzenler. Satıcıya ait kurumsal künye bilgileri iletişim sayfasında yer alır.",
        ],
      },
      {
        baslik: "Ödeme ve teslimat",
        paragraflar: [
          "Ödeme altyapısı henüz devreye alınmamıştır. Devreye alındığında ödeme yöntemleri, teslimat süreleri ve kargo koşulları bu bölümde ayrıntılı olarak yer alacaktır.",
        ],
      },
    ],
  },

  iade: {
    slug: "iade",
    baslik: "Teslimat ve iade koşulları",
    surum: SURUM,
    bolumler: [
      {
        baslik: "Cayma hakkı",
        paragraflar: [
          "Tüketici, sözleşmenin kurulduğu tarihten itibaren on dört gün içinde hiçbir gerekçe göstermeksizin cayma hakkına sahiptir. Dijital içerik ve hizmetlerde cayma hakkının istisnaları ilgili mevzuata göre uygulanır.",
        ],
      },
      {
        baslik: "İade süreci",
        paragraflar: [
          "Ödeme altyapısı devreye alındığında iade talebinin nasıl iletileceği ve geri ödemenin hangi sürede yapılacağı bu bölümde belirtilecektir.",
        ],
      },
    ],
  },
};
