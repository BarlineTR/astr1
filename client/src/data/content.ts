/** Sitenin metin içeriği. Teknik ayrıntı burada değil, depoda durur. */

export const SITE = {
  name: "ASTRO",
  version: "V1",
  repoUrl: "https://github.com/BarlineTR/astr1",
} as const;

/** Açılış animasyonunun ilk evresi: yalnızca isim. */
export const INTRO = {
  kicker: "Karşınızda",
  name: "ASTRO",
  tail: "Sosyal robot platformu",
} as const;

export const HERO = {
  eyebrow: "Sosyal robot platformu",
  title: "Konuşanı duyar, bakanı görür, ona döner.",
  lead:
    "ASTRO; çevresindeki insanları gören, duyan ve kiminle ilgileneceğine kendi " +
    "karar veren bir robot platformudur. Karşılama, bilgilendirme ve etkileşim " +
    "gerektiren ortamlar için geliştirildi.",
} as const;

/** Girişin altındaki rakam şeridi: aracın çalışma sınırları. */
export const FIGURES = [
  { label: "Kafa dönüş aralığı", value: "±85°" },
  { label: "Kamera görüş açısı", value: "72°" },
  { label: "Ulaşılabilir ses açısı", value: "121°" },
  { label: "Etkileşim mesafesi", value: "0,4 – 2,5 m" },
] as const;

/** Ana sayfadaki özellikler. Başlık düzeyinde; ayrıntı yok. */
export const FEATURES = [
  {
    title: "Sosyal bakış",
    body:
      "Konuşan kişiye döner, görüş alanındaki yüzü takip eder. Kime bakacağına " +
      "görüntü ve sesi birlikte değerlendirerek karar verir.",
  },
  {
    title: "Yüz ve ses tanıma",
    body:
      "Tanıtılan kişileri yüzünden ve sesinden tanır, ikisini aynı kimlikte " +
      "birleştirir. Tanıma işlemi cihaz üzerinde çalışır.",
  },
  {
    title: "Sesli diyalog",
    body:
      "Doğal konuşma ile soru alır ve yanıtlar. Ağ bağlantısı koptuğunda yerel " +
      "motorlarla çalışmaya devam eder.",
  },
  {
    title: "Çevre algısı",
    body:
      "Derinlik kamerası ve lazer tarayıcı ile çevresini üç boyutlu algılar; " +
      "kişilerin uzaklığını ölçer.",
  },
  {
    title: "Hareketli taban",
    body:
      "Diferansiyel tahrikli taban ile konum değiştirir. Tekerlek geri beslemesi " +
      "ve eylemsizlik ölçümü ile konumunu izler.",
  },
  {
    title: "Güvenlik",
    body:
      "Hareket sınırları donanım katmanında zorlanır. Bağlantı kesilirse motor " +
      "çıkışları saniyenin yarısı içinde durur.",
  },
  {
    title: "Uzaktan izleme",
    body:
      "Yerel ağ üzerinden kontrol konsolu ile durumu izlenir, kafa hareketi " +
      "yönlendirilir ve acil durdurma verilebilir.",
  },
  {
    title: "Açık mimari",
    body:
      "ROS 2 üzerine kurulu modüler yapı. Bileşenler ayrı ayrı değiştirilebilir, " +
      "yeni yetenekler eklenebilir.",
  },
] as const;

export const CLOSING = {
  title: "Teknik ayrıntılar",
  lead:
    "Donanım özellikleri, ölçüm sonuçları, kalibrasyon değerleri ve kaynak kodun " +
    "tamamı genel depoda açık olarak yayımlanmaktadır.",
  action: "Depoyu görüntüle",
} as const;

/**
 * Hakkımızda sayfası metni — TASLAK.
 *
 * Kurum bilgileri henüz verilmediği için bu metin yer tutucudur. Bilerek
 * doğrulanabilir iddia içermez: kuruluş yılı, çalışan sayısı, müşteri veya ödül
 * gibi yanlış olabilecek somut bilgiler yazılmamıştır. Anlatılan şey yaklaşım ve
 * yöntemdir. Gerçek metin geldiğinde bu sabit tümüyle değişecektir.
 */
export const ABOUT = {
  lead:
    "İnsanla makine arasındaki etkileşimi, ekrana dokunmaktan çıkarıp doğal " +
    "olana yaklaştırmaya çalışıyoruz.",
  sections: [
    {
      id: "hikaye",
      title: "Nasıl başladı",
      paragraphs: [
        "ASTRO bir ürün fikriyle değil, bir gözlemle başladı. Karşılama görevi " +
          "üstlenen makineler insanlara bakmıyordu; ekranlarına dokunulmasını " +
          "bekliyorlardı. Oysa bir insanın bir başkasına yöneldiğini gösteren ilk " +
          "işaret konuşması değil, başını ona çevirmesidir.",
        "Ekip önce bu tek hareketi doğru yapmaya çalıştı: sesin geldiği yöne " +
          "dönmek. İlk denemeler bir masa üzerinde, tek eksenli bir motor ve dört " +
          "mikrofonluk bir diziyle yapıldı. Duvardan yansıyan ses, motorun kendi " +
          "gürültüsü ve işleme gecikmesi yüzünden kafa ısrarla yanlış yöne döndü.",
        "Bugün ASTRO'nun karar katmanındaki kuralların çoğu, o hataların tek tek " +
          "ölçülüp giderilmesinden geriye kalanlardır. Hangi açıdaki sesin anında " +
          "kabul edileceği, hangisinin ısrar isteyeceği, kafanın hiç denememesi " +
          "gereken açının nerede başladığı — hepsi tahminle değil ölçümle konuldu.",
      ],
    },
    {
      id: "yaklasim",
      title: "Yaklaşımımız",
      paragraphs: [
        "Ölçmeden değiştirmiyoruz. Bu yığında yavaş göründüğü için değiştirilen " +
          "pek çok şeyin aslında bir aktarım sorunu olduğu ortaya çıktı; " +
          "algoritmaya dokunmak sorunu gizlemekten başka işe yaramazdı.",
        "Bir davranışın nedenini söyleyemiyorsak, o davranışı ürüne koymuyoruz. " +
          "Sistemin her kritik değeri, nereden geldiği yazılı olarak duruyor.",
      ],
    },
    {
      id: "alanlar",
      title: "Çalışma alanlarımız",
      items: [
        "Sosyal robotik ve insan-makine etkileşimi",
        "Görüntü ve ses verisinin birlikte değerlendirilmesi",
        "Gömülü hareket kontrolü ve kalibrasyon",
        "Cihaz üzerinde çalışan tanıma modelleri",
        "Otonom hareket ve çevre algısı",
      ],
    },
    {
      id: "ekip",
      title: "Ekip",
      paragraphs: [
        "Donanım tasarımı, gömülü yazılım, algı ve etkileşim tasarımı aynı masada " +
          "yürüyor. Bir kararın mekanik, elektronik ve yazılım tarafındaki " +
          "sonuçları ayrı ayrı değil birlikte konuşuluyor.",
      ],
    },
  ],
  contact: {
    title: "İletişim",
    body: "Proje hakkındaki sorular ve iş birliği talepleri için depomuz üzerinden ulaşabilirsiniz.",
  },
} as const;

export const CONSOLE_INTRO = {
  title: "Kontrol konsolu",
  lead:
    "Robotun anlık durumu ve kafa hareketi. Konsol yalnızca yerel ağ üzerinden " +
    "çalışır.",
} as const;
