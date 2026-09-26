/**
 * Sektör sayfaları.
 *
 * Metinler bilerek doğrulanamaz iddia içermiyor: müşteri sayısı, kurulum
 * adedi, tasarruf oranı gibi rakamlar yazılmadı. Anlatılan şey senaryonun
 * kendisi ve platformun ölçülmüş yetenekleri.
 */
export interface Cozum {
  readonly slug: string;
  readonly ad: string;
  readonly ozet: string;
  readonly senaryo: readonly string[];
  readonly kazanc: readonly string[];
}

export const COZUMLER: readonly Cozum[] = [
  {
    slug: "karsilama",
    ad: "Karşılama",
    ozet:
      "Girişte bekleyen ziyaretçiye ekranına dokunmasını beklemeden yönelen, " +
      "konuşanı duyup ona dönen bir karşılama noktası.",
    senaryo: [
      "Ziyaretçi kapıdan girer; kafa, sesin geldiği yöne döner ve yüz görünür olunca yön yalnızca görüntüden sürülür.",
      "Tanıtılmış bir kişi geldiyse yüzünden ve sesinden aynı kimlikte tanınır.",
      "Soru sesli sorulur; yanıt cihaz üzerinde çalışan modellerle verilir, ağ kopsa da çalışmaya devam eder.",
    ],
    kazanc: [
      "Dokunmatik ekran beklemeyen doğal bir ilk temas",
      "Görme engelli ziyaretçi için sesli etkileşim",
      "Ağ bağlantısı koptuğunda da çalışan yerel çalışma kipi",
    ],
  },
  {
    slug: "bilgilendirme",
    ad: "Bilgilendirme",
    ozet:
      "Fuar, müze ve showroom gibi ortamlarda, kalabalık içinde kiminle " +
      "ilgilendiğini belli eden bir bilgi noktası.",
    senaryo: [
      "Kalabalıkta birden çok yüz görünür; dikkat sahibi tek bir kişide kilitlenir ve bu kilit ölçülmüş eşiklerle korunur.",
      "Kişi uzaklaşınca bakış yeni konuşana geçer; kafa boşuna gezinmez.",
      "Anlatılan içerik oturum boyunca kaydedilir ve sonradan incelenebilir.",
    ],
    kazanc: [
      "Kalabalıkta kiminle konuştuğu görünür olan bir cihaz",
      "Kafa hareketi ölçülmüş ölü bant içinde; titremez",
      "Oturum kaydıyla ziyaretçi ilgisinin incelenebilmesi",
    ],
  },
  {
    slug: "egitim",
    ad: "Eğitim",
    ozet:
      "Robotik, görüntü işleme ve insan-makine etkileşimi dersleri için " +
      "kaynağı açık, her katmanı değiştirilebilir bir platform.",
    senaryo: [
      "Öğrenci algı katmanını değiştirip sonucu aynı gövdede sınar.",
      "Kalibrasyon değerleri ve ölçüm yöntemleri depoda açık olarak durur.",
      "ROS 2 üzerine kurulu modüler yapı, bileşenlerin tek tek değiştirilmesine izin verir.",
    ],
    kazanc: [
      "Kaynak kodun ve ölçümlerin tamamına erişim",
      "Bileşen bazında değiştirilebilir mimari",
      "Gerçek donanım üzerinde sınanabilir ödevler",
    ],
  },
];

export function cozumBul(slug: string): Cozum | undefined {
  return COZUMLER.find((c) => c.slug === slug);
}
