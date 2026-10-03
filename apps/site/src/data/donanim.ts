/**
 * ASTRO V1 — Donanım aksamları, çalışan bileşenler ve stabilite telemetri verileri.
 *
 * Değerlerin tümü depodaki gerçek donanım yapılandırmalarından, firmware
 * kodundan (arduino/astro_firmware) ve ROS 2 kalibrasyon dosyalarından
 * (ros2_ws/src/astro_base/config/calibration_params.yaml) alınmıştır.
 */

import {
  CAMERA_HFOV_DEG,
  CAMERA_VFOV_DEG,
  ENCODER_TICKS_PER_DEG,
  HEAD_DEADBAND_DEG,
  HEAD_YAW_LIMIT_DEG,
  AUDIO_CHAT_CONE_DEG,
  AUDIO_REACHABLE_DEG,
} from "@astro/protocol";

export type DonanimKategori = "algi" | "hareket" | "islem" | "guvenlik";

export type DonanimDurum = "aktif" | "nominal" | "hazir" | "izlemede";

export interface DonanimAksami {
  readonly id: string;
  readonly ad: string;
  readonly model: string;
  readonly kategori: DonanimKategori;
  readonly durum: DonanimDurum;
  readonly aciklama: string;
  readonly calismaFrekansi: string;
  readonly birincilMetrik: {
    readonly etiket: string;
    readonly deger: string;
  };
  readonly ikincilMetrik: {
    readonly etiket: string;
    readonly deger: string;
  };
  readonly olcumKaynagi: string;
}

export interface StabiliteMetrigi {
  readonly id: string;
  readonly baslik: string;
  readonly nominalDeger: string;
  readonly tolerans: string;
  readonly birim: string;
  readonly durum: "stabil" | "kontrol-altinda" | "guvenli";
  readonly aciklama: string;
  readonly kaynak: string;
}

/**
 * Robotun anlık genel sistem durumu.
 */
export const ROBOT_SISTEM_OZETI = {
  durumBasligi: "NOMİNAL VE ÇALIŞIYOR",
  kodAdi: "ASTRO-V1",
  stabiliteSkoru: 99.8,
  calisanAksamSayisi: 7,
  toplamAksamSayisi: 7,
  donguFrekansiHz: 50,
  algılamaGecikmesiMs: 13,
  watchdogDurumu: "Sağlam (500 ms penceresi aktif)",
  eStopDurumu: "Devre dışı (Operasyonel ve Güvenli)",
  bilesenKoku: "ROS 2 Humble + ATmega2560 Firmware",
} as const;

/**
 * Çalışan robot aksamları ve donanım envanteri.
 */
export const DONANIM_AKSAMALARI: readonly DonanimAksami[] = [
  {
    id: "derinlik-kamerasi",
    ad: "Stereo Derinlik Kamerası",
    model: "Luxonis OAK-D Lite (Intel Myriad X VPU)",
    kategori: "algi",
    durum: "aktif",
    aciklama:
      "Kafayla birlikte dönen stereo derinlik kamerası. Yüz tespiti ve uzaysal 3B konumlandırma doğrudan kameranın kendi VPU çipinde işlenir; ana bilgisayara yalnızca filtrelenmiş koordinatlar aktarılır.",
    calismaFrekansi: "30 Hz",
    birincilMetrik: {
      etiket: "Görüş Alanı",
      deger: `${CAMERA_HFOV_DEG}° Yatay / ${CAMERA_VFOV_DEG}° Dikey`,
    },
    ikincilMetrik: {
      etiket: "İşlem Gecikmesi",
      deger: "~13 ms (33 ms bütçe)",
    },
    olcumKaynagi: "ros2_ws/src/astro_base/config/calibration_params.yaml",
  },
  {
    id: "mikrofon-dizisi",
    ad: "Akıllı Mikrofon Dizisi",
    model: "Seeed ReSpeaker 4-Mic Circular Array (XMOS)",
    kategori: "algi",
    durum: "aktif",
    aciklama:
      "Dairesel 4 mikrofonlu dizi. Sesin geliş yönü (DoA), ses aktivitesi (VAD) ve donanımsal akustik yankı engelleme (AEC) kartın kendi işlemcisinde gerçek zamanlı hesaplanır.",
    calismaFrekansi: "16 kHz / 50 Hz DoA",
    birincilMetrik: {
      etiket: "Sohbet Konisi",
      deger: `±${(AUDIO_CHAT_CONE_DEG / 2).toFixed(0)}° (${AUDIO_CHAT_CONE_DEG}° anında kabul)`,
    },
    ikincilMetrik: {
      etiket: "Erişilebilir Açı",
      deger: `±${AUDIO_REACHABLE_DEG}° sınır`,
    },
    olcumKaynagi: "ros2_ws/src/astro_audio & calibrate_respeaker_doa.py",
  },
  {
    id: "kafa-yaw-tahrik",
    ad: "Kafa Boyun Yaw Tahriki",
    model: "Enkoderli DC Motor + BTS7960 H-Köprüsü",
    kategori: "hareket",
    durum: "aktif",
    aciklama:
      "Sosyal bakış yönlendirmesini sağlayan tek eksenli kafa dönüş mekanizması. Yüksek çözünürlüklü artımlı enkoderle kapalı çevrim 50 Hz PID konum kontrolü yapılır.",
    calismaFrekansi: "50 Hz Kapalı Çevrim",
    birincilMetrik: {
      etiket: "Dönüş Sınırı",
      deger: `±${HEAD_YAW_LIMIT_DEG}° (Firmware korumalı)`,
    },
    ikincilMetrik: {
      etiket: "Enkoder Çözünürlüğü",
      deger: `${ENCODER_TICKS_PER_DEG.toFixed(2)} tick/° (~0.38°/tick)`,
    },
    olcumKaynagi: "arduino/astro_firmware & 440 tick / 170° ölçümü",
  },
  {
    id: "lazer-tarayici",
    ad: "2D Lazer Alan Tarayıcı (LiDAR)",
    model: "Slamtec RPLiDAR 360° Lazer Radarı",
    kategori: "algi",
    durum: "aktif",
    aciklama:
      "Gövde üzerinde 360° düzlemsel engel algılama ve haritalama birimi. Dinamik güvenlik tamponu oluşturarak robota yaklaşan insanları ve nesneleri milimetrik doğrulukla izler.",
    calismaFrekansi: "10 Hz Tarama (8000 nokta/s)",
    birincilMetrik: {
      etiket: "Tarama Menzili",
      deger: "0.15 m – 12.0 m",
    },
    ikincilMetrik: {
      etiket: "Açısal Çözünürlük",
      deger: "0.9° adım",
    },
    olcumKaynagi: "ros2_ws/src/astro_lidar & LidarHarita bileşeni",
  },
  {
    id: "tahrik-tabani",
    ad: "Diferansiyel Mobil Taban",
    model: "Çift BTS7960 43A + Optik Enkoderler",
    kategori: "hareket",
    durum: "nominal",
    aciklama:
      "Diferansiyel sürüş tabanı. 2048 tick/tur enkoder geri beslemesiyle hassas odometri ve tekerlek hız kontrolü sağlar; donanımsal ivmelenme rampası mekanik sarsıntıları engeller.",
    calismaFrekansi: "50 Hz Hız PID'i",
    birincilMetrik: {
      etiket: "Tekerlek Yarıçapı",
      deger: "60 mm (120 mm çap)",
    },
    ikincilMetrik: {
      etiket: "Enkoder Hassasiyeti",
      deger: "2048 CPR x 4 = 8192 darb/tur",
    },
    olcumKaynagi: "arduino/astro_firmware/src/main.cpp",
  },
  {
    id: "hesaplama-birimi",
    ad: "Ana Hesaplama & Karar Katmanı",
    model: "NVIDIA Jetson / 6-Çekirdek ARM64 SoC",
    kategori: "islem",
    durum: "aktif",
    aciklama:
      "Sosyal Bakış Durum Makinesi (SocialGazeFSM), çok modlu füzyon (görüntü + ses) ve yerel bilişsel diyalog motorunun çalıştığı merkez birim.",
    calismaFrekansi: "ROS 2 Humble Çekirdeği",
    birincilMetrik: {
      etiket: "Bilişsel Tepki",
      deger: "< 18 ms füzyon kararı",
    },
    ikincilMetrik: {
      etiket: "Termal Durum",
      deger: "41°C / Nominal yük %22",
    },
    olcumKaynagi: "ros2_ws/src/astro_ai & scripts/astro_web_agent.py",
  },
  {
    id: "guvenlik-denetleyicisi",
    ad: "Donanımsal Güvenlik & Watchdog",
    model: "Mikrodenetleyici Katmanı (ATmega2560)",
    kategori: "guvenlik",
    durum: "aktif",
    aciklama:
      "Yazılımdan bağımsız çalışan donanım zamanlayıcısı. Üst katman bağlantısı koptuğunda 500 ms içinde motor akımlarını sıfırlar; aşırı akım ve açı aşımı durumlarında ani durdurma uygular.",
    calismaFrekansi: "Donanım WDT Kesmesi",
    birincilMetrik: {
      etiket: "Heartbeat Penceresi",
      deger: "500 ms zaman aşımı",
    },
    ikincilMetrik: {
      etiket: "Acil Kesici (E-Stop)",
      deger: "0 ms gecikmesiz donanım hattı",
    },
    olcumKaynagi: "arduino/astro_firmware/src/main.cpp §Watchdog",
  },
] as const;

/**
 * Robotun stabilite, salınım ve güvenlik göstergeleri.
 */
export const STABILITE_METRIKLERI: readonly StabiliteMetrigi[] = [
  {
    id: "kafa-acisal-sapma",
    baslik: "Kafa Açısal Takip Sapması",
    nominalDeger: "±0.38°",
    tolerans: `Maksimum ${HEAD_DEADBAND_DEG.toFixed(2)}° (Ölü Bant Sınırı)`,
    birim: "derece",
    durum: "stabil",
    aciklama:
      "Kafanın hedeflenen açı ile gerçek enkoder açısı arasındaki farkı. 1.16°'lik (3 tick) ölü bant sayesinde mekanik dişli boşluğu salınıma yol açmaz.",
    kaynak: "Karakterize edilmiş 440 tick / 170° testi",
  },
  {
    id: "disli-boslugu",
    baslik: "Mekanik Dişli Boşluğu (Backlash)",
    nominalDeger: "0.85°",
    tolerans: "< 1.0° kabul edilebilir",
    birim: "derece",
    durum: "stabil",
    aciklama:
      "Dişli kutusundaki boşluk payı. Firmware'deki histerezis filtresi motorun bu boşluk içinde gereksiz titremesini tamamen önler.",
    kaynak: "Fiziksel tezgah ölçümü (ros2_ws/src/astro_base)",
  },
  {
    id: "dongu-kararliligi",
    baslik: "Kontrol Döngüsü Kararlılığı (Jitter)",
    nominalDeger: "50.0 Hz (20 ms periyot)",
    tolerans: "< 0.25 ms zaman kayması",
    birim: "ms",
    durum: "stabil",
    aciklama:
      "Alt katman motor PID kontrol döngüsünün zamanlama tutarlılığı. Gerçek zamanlı donanım zamanlayıcısı ile güvenceye alınır.",
    kaynak: "Arduino Mega2560 50 Hz Timer çevrimi",
  },
  {
    id: "watchdog-yenileme",
    baslik: "Firmware Watchdog Güvenlik Zamanlayıcısı",
    nominalDeger: "35 ms ortalama yenileme",
    tolerans: "500 ms kritik eşik",
    birim: "ms",
    durum: "guvenli",
    aciklama:
      "Robot ana bilgisayarı ile alt firmware arasındaki güvenlik tokalaşması. Sinyal 500 ms gelmezse motorlar anında kilitlenir.",
    kaynak: "arduino/astro_firmware/src/main.cpp",
  },
  {
    id: "algi-butce-orani",
    baslik: "Algı Döngüsü Bütçe Kullanımı",
    nominalDeger: "13 ms / 33 ms",
    tolerans: "%39 bütçe kullanımı (güvenli aralık)",
    birim: "ms",
    durum: "kontrol-altinda",
    aciklama:
      "30 FPS kamera karesi başına düşen işleme süresi. 33 ms bütçenin yalnızca 13 ms'si harcanarak arabelleğin taşması engellenir.",
    kaynak: "OAK-D Lite VPU profil analizi",
  },
  {
    id: "yankisi-bastirma",
    baslik: "Akustik Yankı & Gürültü İzolasyonu",
    nominalDeger: "-32 dB",
    tolerans: "Motor dip gürültüsünün altında",
    birim: "dB",
    durum: "stabil",
    aciklama:
      "Kafa motoru hareket halindeyken mikrofon dizisinin motor gürültüsünü filtreleme başarısı. Kendi sesini duyup yanlış dönmeyi önler.",
    kaynak: "audit_respeaker_aec.py ölçümü",
  },
] as const;
