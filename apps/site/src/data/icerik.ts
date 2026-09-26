/** Sitenin metin içeriği. Teknik ayrıntı burada değil, depoda durur. */

import {
  AUDIO_REACHABLE_DEG,
  CAMERA_HFOV_DEG,
  HEAD_YAW_LIMIT_DEG,
} from "@astro/protocol";

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

/**
 * Girişin altındaki rakam şeridi: aracın çalışma sınırları.
 *
 * Değerler `@astro/protocol` sabitlerinden okunur, elle yazılmaz. Kalibrasyon
 * değişip sabit güncellendiğinde site kendiliğinden doğru kalır; iki yerde
 * tutulan bir ölçüm kaçınılmaz olarak ayrışıyordu.
 */
export const FIGURES = [
  { label: "Kafa dönüş aralığı", value: `±${HEAD_YAW_LIMIT_DEG}°` },
  { label: "Kamera görüş açısı", value: `${CAMERA_HFOV_DEG}°` },
  { label: "Ulaşılabilir ses açısı", value: `${AUDIO_REACHABLE_DEG}°` },
  { label: "Etkileşim mesafesi", value: "0,4 – 2,5 m" },
] as const;

/**
 * Model üzerinde tek tek gösterilen özellikler.
 *
 * Her adımın modelde bir çapası ve kendi kamera açısı vardır. Çapa, modelin
 * ölçülerine oranla tanımlanır (yükseklik ve yarıçapın katı olarak); böylece
 * model değiştiğinde noktalar mutlak metre değerleriyle yerinden oynamaz.
 *
 * Sırayı belirleyen şey aşağıdan yukarı ya da yukarıdan aşağı bir tur değil,
 * anlatının kendisi: önce robotun neyi algıladığı, sonra nasıl karar verdiği,
 * en sonda nasıl hareket ettiği.
 */
export const SHOWCASE = [
  {
    id: "gorme",
    label: "Kamera",
    title: "Görme",
    body:
      "Derinlik kamerası kafanın önündedir ve kafayla birlikte döner. Yüz tespiti " +
      "kameranın kendi işlemcisinde çalışır; ana bilgisayara yalnızca sonuç ulaşır.",
    anchor: { y: 0.82, z: 0.62, x: 0.08 },
    camera: { azimuthDeg: 20, polarDeg: 78, distanceScale: 1.55 },
  },
  {
    id: "duyma",
    label: "Mikrofon dizisi",
    title: "Duyma",
    body:
      "Dört mikrofon dairesel bir dizi oluşturur. Sesin geliş yönü mikrofon " +
      "kartının kendi işlemcisinde hesaplanır ve kafanın o anki açısıyla birleştirilir.",
    anchor: { y: 0.99, z: 0.0, x: 0.0 },
    camera: { azimuthDeg: -26, polarDeg: 60, distanceScale: 1.5 },
  },
  {
    id: "bakis",
    title: "Sosyal bakış",
    label: "Kafa ekseni",
    body:
      "Kafa tek eksende döner ve nereye bakacağına görüntü ile sesi birlikte " +
      "değerlendirerek karar verir. Yüz görünürken yön yalnızca görüntüden gelir.",
    anchor: { y: 0.72, z: 0.5, x: 0.0 },
    camera: { azimuthDeg: 0, polarDeg: 84, distanceScale: 1.95 },
  },
  {
    id: "karar",
    label: "İşlem birimi",
    title: "Karar",
    body:
      "Tanıma modelleri cihaz üzerinde çalışır. Kimi gördüğü ve kimin konuştuğu " +
      "aynı kimlikte birleşir; bunun için ağ bağlantısı gerekmez.",
    anchor: { y: 0.5, z: 0.62, x: 0.1 },
    camera: { azimuthDeg: 32, polarDeg: 84, distanceScale: 1.85 },
  },
  {
    id: "cevre",
    label: "Tarayıcı",
    title: "Çevre algısı",
    body:
      "Lazer tarayıcı ve derinlik verisi birlikte çevrenin haritasını çıkarır. " +
      "Kişilerin uzaklığı kadrajdaki konumundan değil gerçek ölçümden gelir.",
    anchor: { y: 0.26, z: 0.7, x: -0.1 },
    camera: { azimuthDeg: -22, polarDeg: 80, distanceScale: 1.95 },
  },
  {
    id: "hareket",
    label: "Tahrik tabanı",
    title: "Hareket",
    body:
      "Diferansiyel tahrikli taban konum değiştirir. Hareket sınırları ve hız " +
      "rampası donanım katmanında zorlanır; bağlantı koparsa motorlar durur.",
    anchor: { y: 0.1, z: 0.6, x: 0.0 },
    camera: { azimuthDeg: 16, polarDeg: 88, distanceScale: 2.05 },
  },
] as const;

/** Model üzerinde yeri olmayan, listede kalan özellikler. */
export const FEATURES = [
  {
    title: "Sesli diyalog",
    body:
      "Doğal konuşma ile soru alır ve yanıtlar. Ağ bağlantısı koptuğunda yerel " +
      "motorlarla çalışmaya devam eder.",
  },
  {
    title: "Yüz ve ses tanıma",
    body:
      "Tanıtılan kişileri yüzünden ve sesinden tanır, ikisini aynı kimlikte " +
      "birleştirir. Tanıma işlemi cihaz üzerinde çalışır.",
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
