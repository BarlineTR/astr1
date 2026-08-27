# AstroFirmware — Arduino IDE sürümü

`arduino/astro_firmware` (PlatformIO) projesinin Arduino IDE ile derlenebilen
kopyası. Kontrol mantığı `main.cpp` ile **birebir aynıdır**; tek farkı Serial
Monitor'e okunabilir açılış/durum mesajı basmasıdır.

```
AstroFirmware/
├── AstroFirmware.ino   # ana sketch (main.cpp karşılığı)
├── pins.h              # pin tanımları (astro_firmware/include/pins.h ile aynı)
├── protocol.h          # ikili (binary) paket protokolü
└── README.md
```

> Arduino IDE'de klasör adı ile `.ino` adı aynı olmak zorundadır:
> **File > Open… > AstroFirmware/AstroFirmware.ino**

## Kart ayarları

| Ayar | Değer |
|------|-------|
| Board | Arduino Mega or Mega 2560 |
| Processor | ATmega2560 (Mega 2560) |
| Serial Monitor hızı | **115200 baud** |

**Kütüphane gerekmiyor.** TMCStepper, AccelStepper ve Wire bağımlılıkları
kaldırıldı (aşağıya bakın).

## Donanım

| İşlev | Pin | Timer |
|---|---|---|
| Sol motor RPWM / LPWM | 5 / 6 | Timer3A / Timer4A |
| Sağ motor RPWM / LPWM | 9 / 10 | Timer2B / Timer2A |
| Kafa motoru RPWM / LPWM | 44 / 45 | Timer5C / Timer5B |
| Sol enkoder A / B | 2 (INT0) / 3 (INT1) | — |
| Sağ enkoder A / B | 18 (INT5) / 19 (INT4) | — |
| Kafa enkoder A / B | 20 (INT3) / 21 (INT2) | — |

Üç motor da BTS7960 ile sürülüyor. `R_EN`/`L_EN` uçları 5V'a sabit: sürücüler
daima aktif, MCU tarafından donanımsal olarak kesilemiyor. Durdurma = PWM 0.

### Kaldırılan iki donanım

Mega'nın **altı dış kesme pininin tamamı** enkoderlere ayrıldığı için:

- **MPU-6050 IMU yok.** 20/21 = I2C SDA/SCL, kafa enkoderine verildi. Mega'da
  donanımsal I2C başka pine taşınamaz. `IMU_DATA` paketi artık gönderilmiyor,
  `/imu/data_raw` sessiz. → **`astro_sim/config/ekf.yaml`'daki `imu0` bloğu artık
  veri almıyor**, EKF açısal hızı yalnızca tekerlek odometrisinden çıkaracak.
- **TMC2209 yok.** 18/19 = Serial1 TX1/RX1, sağ enkodere verildi. Kafa zaten
  step motordan enkoderli DC motora geçti.

## Kafa kontrolü

`HEAD_CMD` (float32 `angle_deg`) protokolü **değişmedi** — host tarafında hiçbir
değişiklik gerekmiyor. Arkasındaki uygulama step motordan enkoderli konum
PID'ine geçti.

| Sabit | Değer | Not |
|---|---|---|
| `HEAD_TICKS_PER_DEG` | `14.667` | ⚠️ **Tahmin — kalibre edilmeli** |
| `HEAD_MIN_DEG` / `HEAD_MAX_DEG` | `-90` / `+90` | Yazılımsal limit |
| `HEAD_PWM_LIMIT` | `100` | Motor 12V'ta 1000 rpm, tam PWM'de savrulur |
| `HEAD_PWM_MIN` | `30` | Statik sürtünme eşiği |
| `HEAD_KP` / `HEAD_KD` | `1.8` / `0.08` | Konum PID'i |
| `HEAD_DEADBAND_TICKS` | `8` | Bu kadar yakınsa motoru bırak |
| `HEAD_STALL_MS` | `400` | PWM'e rağmen tick değişmezse kes |

**`HEAD_TICKS_PER_DEG` kalibre edilmeden kafa doğru açıya gitmez.** Ölçmek için
`arduino/MotorTest` sketch'ini yükleyip `c <derece>` komutunu kullanın.

**Homing yok:** limit switch olmadığı için açılıştaki konum 0° kabul edilir.
Robotu kafası ortada başlatın.

## Diagnostik bayrakları

`DIAGNOSTICS` paketindeki `flags` alanı:

| Bit | Anlam |
|---|---|
| `0x01` | Watchdog timeout — 500 ms'dir host'tan komut/heartbeat yok, motorlar kesildi |
| `0x02` | (rezerve — eski IMU okuma hatası) |
| `0x04` | Kafa stall — PWM veriliyor ama enkoder 400 ms kımıldamadı, motor kesildi |
| `0x08` | Kafa limiti — gelen açı `HEAD_MIN/MAX_DEG` aralığına kırpıldı |

`0x04` yalnızca yeni bir `HEAD_CMD` geldiğinde temizlenir.

## Yüklendikten sonra seri ekranda ne görünür?

```
==============================================
  AstroFirmware  v2.0.0-ino
  Arduino Mega 2560 - Astro robot alt kontrol
==============================================
  Derleme   : Aug 23 2026 20:15:00
  Seri hiz  : 115200 baud
  Kontrol   : 50 Hz
----------------------------------------------
  Motor  : sol 5/6   sag 9/10   kafa 44/45
  Enkoder: sol 2/3   sag 18/19  kafa 20/21
  Kafa   : 14.667 tick/derece, limit -90/90 derece
  IMU    : YOK (I2C pinleri kafa enkoderinde)
  TMC2209: YOK (kafa artik DC motor)
----------------------------------------------
  Kafa acilis konumu 0 derece kabul edildi.
  Hazir. Host'tan HEARTBEAT bekleniyor...
==============================================
```

Host bağlı değilken her 2 saniyede bir:

```
[STATUS] t=12s  motor=OFF  encL=0 encR=0 kafa=0.0deg  flags=0x1  (host bagli degil)
```

ROS tarafından ilk paket geldiği anda `[INFO] Host baglandi...` yazılır ve metin
çıktısı durur; port tamamen ikili telemetriye bırakılır. Böylece metin mesajları
host parser'ını bozmaz.

Tamamen sessiz çalışma için sketch başındaki `ENABLE_TEXT_BANNER` ve
`ENABLE_TEXT_STATUS` değerlerini `0` yapın.

## İlgili

- `arduino/MotorTest/` — motorların dönüp dönmediğini test eden bağımsız sketch
  ve kafa tick/derece kalibrasyonu
- `ros2_ws/src/astro_base/src/serial_bridge.py` — bu firmware'in ROS 2 karşılığı
- `scripts/motor_test.py`, `scripts/test_wheels.py` — ROS'suz Python test araçları
