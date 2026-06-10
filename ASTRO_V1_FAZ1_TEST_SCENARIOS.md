# ASTRO V1 Faz 1 - Test Senaryoları

## Test 1: Watchdog Timeout Testi

### Amaç
Software watchdog mekanizmasının çalıştığını ve 500 ms timeout süresinde motorların güvenli şekilde durduğunu doğrulamak.

### Ön Koşullar
- Arduino Mega USB ile bağlı
- Motorlar havada (tekerlek yerde değil)
- ROS 2 serial_bridge node çalışıyor

### Test Adımları

1. **Başlangıç Durumu:**
   ```bash
   ros2 run astro_base serial_bridge.py
   ```

2. **Motor Komutları Gönder:**
   ```bash
   ros2 topic pub -r 10 /wheel_cmds astro_base/msg/WheelCmd \
     "{left_rpm: 50.0, right_rpm: 50.0}"
   ```
   - Motorlar dönmeye başlamalı
   - `/arduino/diagnostics` topic'inde `flags=0x00` olmalı (watchdog aktif değil)

3. **Heartbeat Kesme (USB Kabloyu Fiziksel Olarak Çek):**
   - USB kablosunu Arduino'dan ayır
   - Zamanlayıcıyı başlat

4. **Beklenen Davranış:**
   - **T=0 ms:** USB çekildi, heartbeat kesildi
   - **T=500 ms:** Arduino watchdog timeout tetiklendi
   - **Motorlar PWM=0'a gitmeli** (setLeftPWM(0), setRightPWM(0))
   - **Status LED hızlıca yanıp sönmeli** (watchdog uyarısı)

5. **Doğrulama:**
   - Motorların 500 ms içinde durduğunu gözle veya enkoder ile doğrula
   - USB'yi tekrar tak
   - `/arduino/diagnostics` topic'inde `flags=0x01` (WATCHDOG_TIMEOUT) görülmeli

### Kabul Kriteri
✅ Motorlar 500 ms içinde durmalı  
✅ Diagnostics flag'i doğru ayarlanmalı  
✅ USB tekrar takıldığında sistem normal çalışmaya devam etmeli

---

## Test 2: Enkoder Atomik Okuma Testi

### Amaç
Enkoder okuma işleminin atomik olduğunu ve yüksek frekansta torn read olmadığını doğrulamak.

### Ön Koşullar
- Arduino firmware yüklü
- Enkoderler doğru bağlı
- Serial terminal açık (115200 bps veya 500000 bps)

### Test Adımları

1. **Yüksek Hızda Enkoder Pulse Üret:**
   - Teker/motor'u elle hızlıca çevir (veya test motor ile 1000 RPM)
   - Enkoder ~10000 pulse/saniye üretmeli

2. **ROS Joint States İzle:**
   ```bash
   ros2 topic hz /joint_states
   ```
   - Frekans: ~50 Hz olmalı
   
3. **Enkoder Sayacını İzle:**
   ```bash
   ros2 topic echo /joint_states --field position
   ```
   - Pozisyon sürekli artmalı/azalmalı (torn read yoksa)

4. **Beklenen Davranış:**
   - Enkoder pozisyonu sıçrama/atlama göstermemeli
   - `noInterrupts()/interrupts()` atomik okuma sayesinde veri bütünlüğü korunmalı

5. **Negative Test (Opsiyonel):**
   - Atomik okuma kodunu kaldır (`noInterrupts` satırlarını yorum yap)
   - Tekrar test et
   - Torn read gözlemlenirse (örn: `0x12345678` -> `0x12340078` gibi sıçramalar), atomik okuma gerekli olduğu doğrulanır

### Kabul Kriteri
✅ Yüksek hızda enkoder okumalarında sıçrama/torn read olmamalı  
✅ Joint states pozisyonu düzgün artmalı

---

## Test 3: I2C IMU Timeout Testi

### Amaç
IMU I2C bus'ı takılsa bile sistemin donmamasını ve timeout mekanizmasının çalıştığını doğrulamak.

### Ön Koşullar
- IMU (MPU-6050 veya OAK-D IMU) bağlı
- Serial bridge çalışıyor

### Test Adımları

1. **Normal Çalışma:**
   ```bash
   ros2 topic hz /imu/data_raw
   ```
   - IMU verisi ~50 Hz gelmeli

2. **I2C Bus Stress (IMU Kablo Çek/Tak):**
   - IMU I2C kablosunu çek
   - 5 saniye bekle
   - Tekrar tak

3. **Beklenen Davranış:**
   - Kablo çekildiğinde: `Wire.requestFrom()` timeout (5ms) sayesinde donmaz
   - `/arduino/diagnostics` topic'inde `flags=0x02` (IMU_READ_FAIL) görülmeli
   - IMU verisi gelmez ama motorlar çalışmaya devam eder
   - Kablo takıldığında: IMU verisi tekrar gelmeye başlar, `flags=0x00` olur

4. **Doğrulama:**
   ```bash
   ros2 topic echo /arduino/diagnostics --field status[0].message
   ```
   - Kablo çekildiğinde: "IMU_READ_FAIL"
   - Kablo takıldığında: "OK"

### Kabul Kriteri
✅ I2C timeout çalışmalı (sistem donmamalı)  
✅ Diagnostics doğru flag'i ayarlamalı  
✅ Motor kontrolü IMU'dan bağımsız çalışmalı

---

## Test 4: PID Anti-Windup Testi

### Amaç
PID kontrolörün conditional integration anti-windup mekanizmasının çalıştığını ve integral teriminin aşırı birikmediğini doğrulamak.

### Ön Koşullar
- Motorlar çalışır durumda
- Serial bridge aktif

### Test Adımları

1. **Yüksek Hedef Hız Ayarla (Ulaşılamaz):**
   ```bash
   ros2 topic pub -1 /wheel_cmds astro_base/msg/WheelCmd \
     "{left_rpm: 500.0, right_rpm: 500.0}"
   ```
   - Motor maksimum hızda (~200 RPM) takılmalı (PWM=255 saturasyon)

2. **10 Saniye Bekle:**
   - Integral terim `PID_INTEGRAL_LIMIT=50.0f` sınırında kalmalı
   - PWM=255 saturasyonda olduğu için conditional integration integral artışını engellemeli

3. **Hedef Hızı Düşür (Ulaşılabilir):**
   ```bash
   ros2 topic pub -1 /wheel_cmds astro_base/msg/WheelCmd \
     "{left_rpm: 50.0, right_rpm: 50.0}"
   ```

4. **Beklenen Davranış:**
   - Motor **anında** yeni hedef hıza uyum sağlamalı (overshoot minimum)
   - Eğer anti-windup olmasaydı: integral aşırı birikmiş olur, motor hızla geriye gitmez (overshoot büyük olur)

5. **Doğrulama:**
   - Hız değişimi grafik çiz (örn: `rqt_plot /joint_states/velocity`)
   - Overshoot < %10 olmalı

### Kabul Kriteri
✅ Saturasyonda integral birikimi olmamalı  
✅ Hedef hız değişiminde hızlı tepki verilmeli  
✅ Overshoot minimal olmalı

---

## Test 5: Seri Haberleşme CRC Testi

### Amaç
CRC-8 paket doğrulama mekanizmasının bozuk paketleri reddettiğini ve sistem kararlılığını koruduğunu doğrulamak.

### Ön Koşullar
- Serial port açık
- Test script hazır (Python)

### Test Adımları

1. **CRC Test Script Çalıştır:**
   ```python
   import serial
   import struct
   
   def crc8(data):
       crc = 0x00
       for b in data:
           crc ^= b
           for _ in range(8):
               if crc & 0x80:
                   crc = ((crc << 1) & 0xFF) ^ 0x07
               else:
                   crc = (crc << 1) & 0xFF
       return crc
   
   ser = serial.Serial('/dev/ttyACM0', 500000)
   
   # Geçerli paket gönder
   payload = struct.pack('<ff', 100.0, 100.0)
   length = 1 + len(payload)
   body = bytes([length, 0x02]) + payload
   valid_crc = crc8(body)
   valid_pkt = bytes([0xAA, 0x55]) + body + bytes([valid_crc])
   ser.write(valid_pkt)
   print("Valid packet sent")
   
   # Bozuk CRC paketi gönder
   bad_crc = (valid_crc + 1) & 0xFF  # Yanlış CRC
   bad_pkt = bytes([0xAA, 0x55]) + body + bytes([bad_crc])
   ser.write(bad_pkt)
   print("Bad CRC packet sent")
   ```

2. **Arduino Serial Monitor:**
   - Geçerli paket: İşlenir, motor komutları uygulanır
   - Bozuk CRC paketi: Red edilir, işlem yapılmaz

3. **Beklenen Davranış:**
   - Parser bozuk CRC paketini tespit eder ve `state=WAIT_SOF1` durumuna döner
   - Sistem çökmez, sonraki geçerli paketleri işler

### Kabul Kriteri
✅ Geçerli CRC paketleri kabul edilmeli  
✅ Bozuk CRC paketleri reddedilmeli  
✅ Sistem kararlılığı korunmalı

---

## Test 6: Zaman Senkronizasyonu Testi

### Amaç
Arduino `micros()` zaman damgası ile ROS zaman arasındaki senkronizasyonun doğru çalıştığını ve gecikmenin <50 ms olduğunu doğrulamak.

### Ön Koşullar
- IMU çalışıyor
- Serial bridge aktif

### Test Adımları

1. **IMU Zaman Damgası İzle:**
   ```bash
   ros2 topic echo /imu/data_raw --field header.stamp
   ```

2. **Gecikme Hesapla:**
   - Arduino IMU ölçümü: `t_arduino = micros()` (payload'da gönderiliyor)
   - ROS zaman: `t_ros = header.stamp`
   - Offset: `offset = t_ros - t_arduino_converted`
   - Gecikme: `latency = current_ros_time - (t_arduino + offset)`

3. **Beklenen Davranış:**
   - İlk IMU paketinde offset hesaplanır (`time_offset_ns`)
   - Sonraki paketlerde: `stamp_ros_ns = (micros_ts * 1000) + time_offset_ns`
   - Gecikme <50 ms olmalı

4. **Doğrulama Script:**
   ```python
   import rclpy
   from rclpy.node import Node
   from sensor_msgs.msg import Imu
   
   class LatencyChecker(Node):
       def __init__(self):
           super().__init__('latency_checker')
           self.sub = self.create_subscription(Imu, '/imu/data_raw', self.callback, 10)
       
       def callback(self, msg):
           now = self.get_clock().now()
           stamp = rclpy.time.Time.from_msg(msg.header.stamp)
           latency_ns = (now - stamp).nanoseconds
           latency_ms = latency_ns / 1e6
           self.get_logger().info(f'IMU latency: {latency_ms:.1f} ms')
   
   rclpy.init()
   node = LatencyChecker()
   rclpy.spin(node)
   ```

### Kabul Kriteri
✅ Zaman senkronizasyonu offset doğru hesaplanmalı  
✅ IMU gecikme <50 ms olmalı  
✅ Drift minimal olmalı (uzun süreli test)

---

## Test 7: PWM Frekans Doğrulama Testi

### Amaç
Motor PWM frekansının 31.25 kHz'e çıkarıldığını ve motor gürültüsünün azaldığını doğrulamak.

### Ön Koşullar
- Osiloskop veya logic analyzer
- Motor bağlı

### Test Adımları

1. **Osiloskop Bağla:**
   - Probe: Motor PWM pin'i (örn: Pin 6 - L_MOTOR_PWM_FWD)
   - Ground: Arduino GND

2. **Motor PWM Çıkışı Üret:**
   ```bash
   ros2 topic pub -1 /wheel_cmds astro_base/msg/WheelCmd \
     "{left_rpm: 100.0, right_rpm: 100.0}"
   ```

3. **Frekans Ölçümü:**
   - Osiloskop: Frekans = 31.25 kHz ± 0.5 kHz olmalı
   - Logic Analyzer: Period = 31.96 μs

4. **Ses Gürültüsü Kontrolü:**
   - Eski frekans (490 Hz): Motor yüksek perdeden ses çıkarır
   - Yeni frekans (31.25 kHz): Motor sessiz çalışmalı (insan işitme eşiği ~20 kHz üstü)

### Kabul Kriteri
✅ PWM frekansı 31.25 kHz olmalı  
✅ Motor gürültüsü azalmalı  
✅ Motor performansı düzgün olmalı

---

## Test 8: ROS 2 QoS BEST_EFFORT Testi

### Amaç
Sensör verilerinin (IMU, Joint States) BEST_EFFORT QoS ile yayınlandığını ve yüksek frekansta paket kaybı olsa bile sistemin kararlı çalıştığını doğrulamak.

### Ön Koşullar
- Yoğun ROS 2 network trafiği (simülasyon)

### Test Adımları

1. **QoS Doğrulama:**
   ```bash
   ros2 topic info /imu/data_raw
   ```
   - `Reliability: BEST_EFFORT` görülmeli

2. **Yüksek Yüklü Test:**
   - 10+ ROS 2 node çalıştır (dummy publisher'lar)
   - Network bandwidth'i kısıtla (tc tool ile)

3. **Beklenen Davranış:**
   - BEST_EFFORT: Paket kaybı olabilir ama sistem çökmez
   - RELIABLE olsaydı: Network yavaşlar, buffer dolar, sistem donabilir

4. **Doğrulama:**
   ```bash
   ros2 topic hz /imu/data_raw
   ```
   - Frekans düşebilir (%80-100 arası) ama 0'a düşmemeli

### Kabul Kriteri
✅ Sensör verileri BEST_EFFORT QoS kullanmalı  
✅ Yüksek yükte sistem kararlı olmalı  
✅ Paket kaybı toleransı olmalı

---

## Test Sonuçları Şablonu

| Test # | Test Adı | Durum | Notlar |
|--------|----------|-------|--------|
| 1 | Watchdog Timeout | ⬜ PASS / ⬜ FAIL | |
| 2 | Enkoder Atomik Okuma | ⬜ PASS / ⬜ FAIL | |
| 3 | I2C IMU Timeout | ⬜ PASS / ⬜ FAIL | |
| 4 | PID Anti-Windup | ⬜ PASS / ⬜ FAIL | |
| 5 | Seri Haberleşme CRC | ⬜ PASS / ⬜ FAIL | |
| 6 | Zaman Senkronizasyonu | ⬜ PASS / ⬜ FAIL | |
| 7 | PWM Frekans | ⬜ PASS / ⬜ FAIL | |
| 8 | ROS 2 QoS BEST_EFFORT | ⬜ PASS / ⬜ FAIL | |

---

**Test Onay:**  
Test Mühendisi: ___________________  
Tarih: ___________________  
İmza: ___________________
