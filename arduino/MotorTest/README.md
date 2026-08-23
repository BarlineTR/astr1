# MotorTest — sol / sağ / kafa motor test sketch'i

Tek amacı var: **motorlar dönüyor mu, doğru yöne mi dönüyor, enkoderler sayıyor mu?**
PID, IMU, TMC2209 ve ROS protokolü yoktur. Ana firmware'i yüklemeden önce
kablolamayı doğrulamak için kullanın.

- Kart: **Arduino Mega 2560**
- Serial Monitor: **115200 baud**, satır sonu **Newline**
- Ek kütüphane gerekmez (sadece Arduino core)

## Pin haritası (`pins.h`)

| İşlev | Pin | Timer |
|---|---|---|
| Sol motor RPWM / LPWM | **5 / 6** | Timer3A / Timer4A |
| Sağ motor RPWM / LPWM | **9 / 10** | Timer2B / Timer2A |
| Kafa motoru RPWM / LPWM | **44 / 45** | Timer5C / Timer5B |
| Sol enkoder A / B | 2 (INT0) / 4 | — |
| Sağ enkoder A / B | 3 (INT1) / **22** | — |
| Kafa enkoder A / B | 20 (INT3) / 21 (INT2) | — |

> ⚠️ **Sağ enkoder B kablosu 9'dan 22'ye taşınmalı.** Pin 9 artık sağ motor
> sürücüsünün RPWM'i. Eski `pins.h` sağ enkoder B'yi 9'da tanımlıyordu.

> ⚠️ **Kafa enkoderi 20/21 = I2C (SDA/SCL).** Bu test sketch'i I2C kullanmadığı
> için burada sorun çıkmaz. Ana firmware'de MPU-6050 aynı hatta olduğundan
> çakışır — orada kafa enkoderi 18/19'a taşınmalı.

BTS7960'ların `R_EN`/`L_EN` uçları 5V'a sabitlenmiş: sürücüler her zaman aktif,
MCU tarafından donanımsal olarak kesilemiyor. Durdurma yalnızca PWM = 0 ile.

## Komutlar

| Komut | Etki |
|---|---|
| `h` | yardım menüsü |
| `t` | **tekerlek otomatik testi**: ileri → dur → geri → dur → sağa → dur → sola → dur (her adım 2 sn) |
| `y` | **kafa otomatik testi**: kısa sağa, kısa sola (400 ms, PWM 80) — kabaca başladığı yere döner |
| `l <pwm>` | sol tekerlek (`-255..255`), örn. `l 120` / `l -120` |
| `r <pwm>` | sağ tekerlek |
| `b <pwm>` | iki tekerlek birden |
| `k <pwm>` | kafa motoru — tavan `HEAD_PWM_LIMIT` (100), aşan değer kırpılır |
| `c <derece>` | kafa tick/derece kalibrasyonu |
| `s` | DUR |
| `e` | enkoder sayaçlarını sıfırla |
| `m` | anlık durumu bir kez yazdır |

## Çıktı

Her 250 ms'de bir satır:

```
PWM L=150 R=150 K=0 | TICK L=4820 R=4791 K=0 | HIZ L=1930 R=1918 K=0 tick/s
```

Sorun varsa satır sonuna teşhis eklenir:

- `[!] SOL donmuyor/enkoder yok` — PWM veriliyor ama tick artmıyor
  (motor gerçekten dönmüyorsa güç/sürücü sorunu; dönüyorsa enkoder kablosu)
- `[!] SAG ters yonde` — motor ileri komutunda geri sayıyor
  (motor uçlarını veya enkoder A/B'yi ters bağlamışsınız)
- `[STALL] Kafa donmuyor -> motor kesildi` — kafaya PWM veriliyor ama 300 ms
  boyunca tick değişmedi; mekanik dayanağa dayanmış olabilir

İki tekerin `tick/s` değerleri aynı PWM'de kabaca eşit olmalı; ciddi fark varsa
mekanik sürtünme ya da sürücü dengesizliği vardır.

## Kafa tick/derece kalibrasyonu

Motorun ürün sayfası enkoder CPR'ını vermiyor, bu yüzden ölçmek gerekiyor:

1. `e` → sayaçları sıfırla
2. Kafayı bilinen bir açıya çevir — elle, ya da `k 60` verip `s` ile durdurup
   açıyı iletki ile ölç
3. `c 90` (çevirdiğiniz gerçek açıyı yazın)

Çıktı:

```
[KALIBRASYON] tick=1320  aci=90 derece  ->  tick/derece = 14.667
  360 derece = 5280.0 tick
```

Bu değeri firmware'e kafa konum PID'i yazılırken `HEAD_TICKS_PER_DEG` sabiti
olarak gireceğiz.

## Güvenlik

- Tekerlekleri **havada** (sehpa üstünde) test edin.
- Kafa 1000 rpm'lik bir motor — tam PWM'de savrulur. Bu yüzden kafa PWM'i
  `HEAD_PWM_LIMIT = 100` ile sınırlı ve otomatik testi çok kısa tutuldu.
- Kafada limit switch yok. Dayanağa dayanırsa stall koruması motoru keser.
- Elle verilen PWM komutları 10 sn sonra otomatik kesilir (`IDLE_TIMEOUT_MS`).
- `s` her an tüm motorları durdurur, otomatik testleri de iptal eder.

## PWM frekansı

`PWM_HIGH_FREQ 1` iken Timer2/3/4/5 prescaler'ı 1'e çekilir → **31.37 kHz**
(sessiz). `millis()`/`micros()` Timer0'da olduğu için etkilenmez.

BTS7960 datasheet'i ~25 kHz'e kadar veriyor; 31 kHz pratikte yaygın kullanılıyor
ama spec'in bir tık üstünde. Sürücüler ısınırsa `PWM_HIGH_FREQ 0` yapın —
o zaman 490 Hz'e döner (motorlar duyulur şekilde vınlar).
