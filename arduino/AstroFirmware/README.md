# AstroFirmware — Arduino IDE sürümü

`arduino/astro_firmware` (PlatformIO) projesinin Arduino IDE ile derlenebilen kopyası.
Kaynak mantık birebir aynıdır; ek olarak **seri ekrana okunabilir açılış/durum mesajları** basar.

## Klasör yapısı

```
AstroFirmware/
├── AstroFirmware.ino   # ana sketch (main.cpp karşılığı)
├── pins.h              # pin tanımları
├── protocol.h          # ikili (binary) paket protokolü
└── README.md
```

> Arduino IDE'de klasör adı ile `.ino` adı aynı olmak zorundadır. Klasörü olduğu gibi
> açın: **File > Open… > AstroFirmware/AstroFirmware.ino**

## Kart ayarları

| Ayar | Değer |
|------|-------|
| Board | Arduino Mega or Mega 2560 |
| Processor | ATmega2560 (Mega 2560) |
| Serial Monitor hızı | **500000 baud** |

## Gerekli kütüphaneler

**Sketch > Include Library > Manage Libraries…** üzerinden kurun:

- `TMCStepper` — teemuatlut
- `AccelStepper` — Mike McCauley
- `Wire`, `SPI` — Arduino AVR core ile birlikte gelir (ayrıca kurmaya gerek yok)

## Yüklendikten sonra seri ekranda ne görünür?

Kart açılır açılmaz Serial Monitor'e şu banner basılır:

```
==============================================
  AstroFirmware  v1.0.0-ino
  Arduino Mega 2560 - Astro robot alt kontrol
==============================================
  Derleme      : Aug 23 2026 18:57:00
  Seri hiz     : 500000 baud
  Kontrol      : 50 Hz
  IMU (0x68)   : OK
  TMC2209      : OK (UART)
----------------------------------------------
  Hazir. Host'tan HEARTBEAT bekleniyor...
  Not: veri akisi ikili (binary) protokoldur;
       ekranda anlamsiz karakterler gorursunuz.
==============================================
```

IMU ve TMC2209 satırları gerçek donanım kontrolüdür (I2C ACK ve TMC UART
`test_connection()`), yani kablolama hatasını açılışta görürsünüz. Ardından
durum LED'i (pin 13) 6 kez yanıp söner.

**Host bağlı değilken** her 2 saniyede bir okunabilir durum satırı basılır:

```
[STATUS] t=12s  motor=OFF  encL=0  encR=0  imu=OK  flags=0x1  (host bagli degil)
```

ROS tarafından ilk paket geldiği anda `[INFO] Host baglandi...` yazılır ve
metin çıktısı durur; port tamamen ikili telemetriye bırakılır (IMU / enkoder /
diagnostik paketleri). Böylece metin mesajları host parser'ını bozmaz.

## Metin çıktısını kapatma

`AstroFirmware.ino` başındaki anahtarlar:

```cpp
#define ENABLE_TEXT_BANNER 1   // 0 = açılış banner'ını kapat
#define ENABLE_TEXT_STATUS 1   // 0 = periyodik durum satırını kapat
#define TEXT_STATUS_PERIOD_MS 2000UL
```

Tamamen sessiz (yalnızca binary protokol) çalışma için ikisini de `0` yapın.

## PlatformIO sürümünden farkları

- `include/` klasörü yerine header'lar sketch klasöründe (Arduino IDE gereği).
- `imuInit()` / `tmcInit()` artık `bool` döndürüyor → banner'da OK/YOK gösterimi.
- PID lambda'sı `pidStep()` fonksiyonuna taşındı (aynı davranış, aynı katsayılar).
- Açılış banner'ı, host bağlantı bilgisi ve periyodik durum satırı eklendi.
- Binary telemetri yalnızca host'tan ilk paket geldikten sonra gönderilir.

Firmware davranışı (PID katsayıları, 50 Hz kontrol, 500 ms komut watchdog'u,
2 s donanım watchdog'u, 31.25 kHz PWM, protokol paketleri) değişmedi.
