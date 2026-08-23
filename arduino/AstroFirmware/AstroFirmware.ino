/*
 * AstroFirmware - Arduino IDE sürümü
 * ----------------------------------
 * Bu sketch, arduino/astro_firmware (PlatformIO) projesinin Arduino IDE kopyasıdır.
 *
 * Kart      : Arduino Mega 2560
 * Seri hız  : 115200 baud (Serial Monitor da 115200 olmalı)
 *
 * Gerekli kütüphaneler (Sketch > Include Library > Manage Libraries):
 *   - TMCStepper   (teemuatlut)
 *   - AccelStepper (Mike McCauley)
 *   - Wire         (Arduino AVR core ile birlikte gelir)
 */

#include <Arduino.h>
#include <Wire.h>
#include <TMCStepper.h>
#include <AccelStepper.h>
#include <avr/wdt.h>

#include "pins.h"
#include "protocol.h"

// Arduino IDE otomatik prototip uretir, ancak referans parametreli
// fonksiyonlar icin acik prototip vermek daha guvenlidir.
int pidStep(float target_rpm, float meas_rpm, float& e_i, float& e_prev, uint32_t dt_ms);

// I2C'den big-endian int16 oku (Wire.read() sirasi garanti altina alinir)
static inline int16_t readInt16BE() {
  int16_t h = Wire.read();
  int16_t l = Wire.read();
  return (int16_t)((h << 8) | l);
}

// ====== Seri ekran (Serial Monitor) mesajları ======
// 1 = açılışta banner bas, 0 = tamamen sessiz (sadece binary protokol)
#define ENABLE_TEXT_BANNER 1
// 1 = host bağlı değilken periyodik durum satırı bas
#define ENABLE_TEXT_STATUS 1
#define TEXT_STATUS_PERIOD_MS 2000UL

#define FW_NAME    "AstroFirmware"
#define FW_VERSION "1.0.0-ino"

// ====== Parametreler ======
static const uint32_t SERIAL_BAUD = 115200; // standart baud (host ile ayni olmali)
static const float CONTROL_HZ = 50.0f;
static const uint32_t CONTROL_DT_MS = (uint32_t)(1000.0f / CONTROL_HZ);

static const int32_t TICKS_PER_REV_L = 2048; // enkoder CPR*4 uygun biçimde ayarlayın
static const int32_t TICKS_PER_REV_R = 2048;

static const float WHEEL_R_L = 0.06f; // metre (örnek 60mm)
static const float WHEEL_R_R = 0.06f;

static const float KP = 0.6f, KI = 0.2f, KD = 0.0f; // 50 Hz PID için örnek
static const int PWM_MAX = 255;
static const float PID_INTEGRAL_LIMIT = 50.0f; // anti-windup limiti

// ====== Global Durum ======
volatile int32_t g_left_ticks = 0;
volatile int32_t g_right_ticks = 0;

static int32_t g_left_last_ticks = 0;
static int32_t g_right_last_ticks = 0;

static float g_left_target_rpm = 0.0f;
static float g_right_target_rpm = 0.0f;

static float g_left_err_i = 0.0f, g_right_err_i = 0.0f;
static float g_left_err_prev = 0.0f, g_right_err_prev = 0.0f;

static uint32_t g_last_control_ms = 0;
static uint32_t g_last_heartbeat_ms = 0;
static uint32_t g_last_text_ms = 0;
static bool g_host_seen = false; // host'tan en az bir paket geldi mi?

static bool g_motors_enabled = true;
static uint32_t g_diag_flags = 0;

static bool g_imu_ok = false;
static bool g_tmc_ok = false;

// IMU ham değerleri -> m/s2, rad/s dönüştürülecek
static float ax, ay, az, gx, gy, gz;
static uint32_t imu_last_us = 0;

// TMC2209 (UART üzerinden konfigürasyon)
TMC2209Stepper tmc2209(&TMC2209_SERIAL, 0.11f, TMC2209_ADDRESS); // 0.11 ohm örnek Rsense
AccelStepper head_stepper(AccelStepper::DRIVER, HEAD_STEP_PIN, HEAD_DIR_PIN);

// ====== Yardımcılar ======
inline void setMotorPWM(int pwm_fwd_pin, int pwm_rev_pin, int val) {
  val = constrain(val, -PWM_MAX, PWM_MAX);
  if (val >= 0) {
    analogWrite(pwm_fwd_pin, val);
    analogWrite(pwm_rev_pin, 0);
  } else {
    analogWrite(pwm_fwd_pin, 0);
    analogWrite(pwm_rev_pin, -val);
  }
}

inline void setLeftPWM(int v) { setMotorPWM(L_MOTOR_PWM_FWD, L_MOTOR_PWM_REV, v); }
inline void setRightPWM(int v){ setMotorPWM(R_MOTOR_PWM_FWD, R_MOTOR_PWM_REV, v); }

void leftEncA() {
  // Quadrature yön tespiti
  bool b = digitalRead(L_ENC_B);
  g_left_ticks += b ? -1 : +1;
}
void rightEncA() {
  bool b = digitalRead(R_ENC_B);
  g_right_ticks += b ? -1 : +1;
}

bool imuInit() {
  Wire.begin();
  // I2C timeout (5 ms) - hatalı hatta takılıp kalmayı önler
  Wire.setWireTimeout(5000, true);

  delay(50);
  // MPU-6050: power management 0x6B = 0x00
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x6B); Wire.write(0x00);
  bool ok = (Wire.endTransmission() == 0);

  // Gyro full-scale = ±2000 dps (0x1B=0x18), Accel ±2g (0x1C=0x00)
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x1B); Wire.write(0x18);
  Wire.endTransmission();

  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x1C); Wire.write(0x00);
  Wire.endTransmission();

  return ok;
}

bool imuRead() {
  // Okuma: ACCEL_XOUT_H (0x3B) -> 14 byte
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) {
    g_diag_flags |= 0x02; // IMU_READ_FAIL flag
    return false;
  }

  uint8_t n = Wire.requestFrom((uint8_t)IMU_I2C_ADDR, (uint8_t)14, (uint8_t)true);
  if (n != 14) {
    g_diag_flags |= 0x02; // IMU_READ_FAIL flag
    return false;
  }

  int16_t axr = readInt16BE();
  int16_t ayr = readInt16BE();
  int16_t azr = readInt16BE();
  int16_t tmp = readInt16BE(); (void)tmp;
  int16_t gxr = readInt16BE();
  int16_t gyr = readInt16BE();
  int16_t gzr = readInt16BE();

  // Dönüşümler
  // Accel: ±2g -> LSB/g = 16384, g=9.80665
  const float A_SCALE = 9.80665f / 16384.0f;
  // Gyro: ±2000 dps -> 16.4 LSB/(°/s); rad/s = dps * pi/180
  const float G_SCALE = (PI / 180.0f) / 16.4f;

  ax = axr * A_SCALE;
  ay = ayr * A_SCALE;
  az = azr * A_SCALE;
  gx = gxr * G_SCALE;
  gy = gyr * G_SCALE;
  gz = gzr * G_SCALE;

  imu_last_us = micros();
  g_diag_flags &= ~0x02; // Clear IMU_READ_FAIL flag
  return true;
}

bool tmcInit() {
  pinMode(HEAD_EN_PIN, OUTPUT);
  digitalWrite(HEAD_EN_PIN, LOW); // enable low active olabilir, donanıma göre ayarlayın

  // Not: bu USB/Serial Monitor portu DEĞİL, sürücüye giden ayrı UART (Serial1).
  TMC2209_SERIAL.begin(500000); // TMC2209 için yüksek baudrate önerilir
  delay(50);
  tmc2209.begin();
  tmc2209.pdn_disable(true);
  tmc2209.I_scale_analog(false);
  tmc2209.rms_current(500); // mA
  tmc2209.microsteps(16);
  tmc2209.en_spreadCycle(false);
  tmc2209.TCOOLTHRS(0xFFFFF);

  head_stepper.setMaxSpeed(2000);     // steps/s
  head_stepper.setAcceleration(2000); // steps/s^2

  // UART üzerinden sürücüye ulaşabiliyor muyuz?
  return tmc2209.test_connection() == 0;
}

void setupIO() {
  pinMode(STATUS_LED, OUTPUT);
  pinMode(L_MOTOR_PWM_FWD, OUTPUT);
  pinMode(L_MOTOR_PWM_REV, OUTPUT);
  pinMode(R_MOTOR_PWM_FWD, OUTPUT);
  pinMode(R_MOTOR_PWM_REV, OUTPUT);

  pinMode(L_ENC_A, INPUT_PULLUP);
  pinMode(L_ENC_B, INPUT_PULLUP);
  pinMode(R_ENC_A, INPUT_PULLUP);
  pinMode(R_ENC_B, INPUT_PULLUP);

  attachInterrupt(digitalPinToInterrupt(L_ENC_A), leftEncA, RISING);
  attachInterrupt(digitalPinToInterrupt(R_ENC_A), rightEncA, RISING);

  // PWM frekansını artır (Mega Timer 4: pin 6,7,8 -> 31.25 kHz)
  TCCR4B = (TCCR4B & 0xF8) | 0x01;
}

void stopMotors() {
  setLeftPWM(0);
  setRightPWM(0);
}

// ====== Seri ekran metin çıktıları ======
void printBanner() {
#if ENABLE_TEXT_BANNER
  Serial.println();
  Serial.println(F("=============================================="));
  Serial.print (F("  ")); Serial.print(F(FW_NAME));
  Serial.print (F("  v")); Serial.println(F(FW_VERSION));
  Serial.println(F("  Arduino Mega 2560 - Astro robot alt kontrol"));
  Serial.println(F("=============================================="));
  Serial.print  (F("  Derleme      : ")); Serial.print(F(__DATE__));
  Serial.print  (F(" ")); Serial.println(F(__TIME__));
  Serial.print  (F("  Seri hiz     : ")); Serial.print(SERIAL_BAUD); Serial.println(F(" baud"));
  Serial.print  (F("  Kontrol      : ")); Serial.print((int)CONTROL_HZ); Serial.println(F(" Hz"));
  Serial.print  (F("  IMU (0x")); Serial.print(IMU_I2C_ADDR, HEX); Serial.print(F(")  : "));
  Serial.println(g_imu_ok ? F("OK") : F("YOK / cevap vermiyor"));
  Serial.print  (F("  TMC2209      : "));
  Serial.println(g_tmc_ok ? F("OK (UART)") : F("YOK / UART cevap vermiyor"));
  Serial.println(F("----------------------------------------------"));
  Serial.println(F("  Hazir. Host'tan HEARTBEAT bekleniyor..."));
  Serial.println(F("  Not: veri akisi ikili (binary) protokoldur;"));
  Serial.println(F("       ekranda anlamsiz karakterler gorursunuz."));
  Serial.println(F("=============================================="));
  Serial.flush();
#endif
}

void printStatusLine() {
#if ENABLE_TEXT_STATUS
  Serial.print(F("[STATUS] t="));
  Serial.print(millis() / 1000UL);
  Serial.print(F("s  motor="));
  Serial.print(g_motors_enabled ? F("ON") : F("OFF"));
  Serial.print(F("  encL="));
  Serial.print(g_left_last_ticks);
  Serial.print(F("  encR="));
  Serial.print(g_right_last_ticks);
  Serial.print(F("  imu="));
  Serial.print((g_diag_flags & 0x02) ? F("FAIL") : F("OK"));
  Serial.print(F("  flags=0x"));
  Serial.print(g_diag_flags, HEX);
  Serial.println(F("  (host bagli degil)"));
#endif
}

void publishIMU() {
  uint8_t payload[6 * 4 + 4];
  // floatları little-endian olarak kopyala
  float vals[6] = {ax, ay, az, gx, gy, gz};
  memcpy(&payload[0], vals, sizeof(vals));
  memcpy(&payload[6 * 4], &imu_last_us, 4);
  Proto::writePacket(Serial, Proto::IMU_DATA, payload, sizeof(payload));
}

void publishEncoders(uint32_t dt_us, int32_t dl, int32_t dr) {
  uint8_t payload[4 + 4 + 4];
  memcpy(&payload[0], &dl, 4);
  memcpy(&payload[4], &dr, 4);
  memcpy(&payload[8], &dt_us, 4);
  Proto::writePacket(Serial, Proto::ENCODER_TICKS, payload, sizeof(payload));
}

void publishDiag(uint16_t vbat_mV, int16_t temp_cX100, uint32_t flags) {
  uint8_t payload[2 + 2 + 4];
  memcpy(&payload[0], &vbat_mV, 2);
  memcpy(&payload[2], &temp_cX100, 2);
  memcpy(&payload[4], &flags, 4);
  Proto::writePacket(Serial, Proto::DIAGNOSTICS, payload, sizeof(payload));
}

void loopControl() {
  uint32_t now = millis();
  if (now - g_last_control_ms < CONTROL_DT_MS) return;
  uint32_t dt_ms = now - g_last_control_ms;
  g_last_control_ms = now;

  // Watchdog: 500 ms içinde heartbeat/komut gelmezse motorları kes
  if (now - g_last_heartbeat_ms > 500) {
    g_motors_enabled = false;
    stopMotors();
    g_diag_flags |= 0x01; // WATCHDOG_TIMEOUT flag
  } else {
    g_motors_enabled = true;
    g_diag_flags &= ~0x01; // Clear WATCHDOG_TIMEOUT flag
  }

  // Enkoder okuma atomik (AVR'de int32_t atomik değil)
  int32_t l_ticks, r_ticks;
  noInterrupts();
  l_ticks = g_left_ticks;
  r_ticks = g_right_ticks;
  interrupts();

  int32_t dl = l_ticks - g_left_last_ticks;
  int32_t dr = r_ticks - g_right_last_ticks;
  g_left_last_ticks = l_ticks;
  g_right_last_ticks = r_ticks;

  float dt_min = dt_ms / 60000.0f; // ms -> dakika
  float l_rpm_meas = (dl / (float)TICKS_PER_REV_L) / dt_min;
  float r_rpm_meas = (dr / (float)TICKS_PER_REV_R) / dt_min;

  int l_pwm = 0, r_pwm = 0;
  if (g_motors_enabled) {
    l_pwm = pidStep(g_left_target_rpm,  l_rpm_meas, g_left_err_i,  g_left_err_prev,  dt_ms);
    r_pwm = pidStep(g_right_target_rpm, r_rpm_meas, g_right_err_i, g_right_err_prev, dt_ms);
  }
  setLeftPWM(l_pwm);
  setRightPWM(r_pwm);

  // IMU oku (50 Hz)
  imuRead();

  // Host bağlıysa binary telemetri gönder; değilse seri ekranı kirletme
  if (g_host_seen) {
    publishIMU();
    publishEncoders(dt_ms * 1000u, dl, dr);

    // Basit diagnostik: bayraklar
    uint16_t vbat = 12000; // mV (örn. gelecekte ADC ile ölç)
    int16_t temp = 2500;   // 25.00 C
    publishDiag(vbat, temp, g_diag_flags);
  }
}

// PID adımı - stiction feedforward + conditional integration ile anti-windup
// (main.cpp'deki pid_step ile birebir aynı davranış)
int pidStep(float target_rpm, float meas_rpm, float& e_i, float& e_prev, uint32_t dt_ms) {
  // Hedef sıfırsa motoru tamamen bırak, integrali de temizle
  if (abs(target_rpm) < 0.01f) {
    e_i = 0.0f;
    e_prev = 0.0f;
    return 0;
  }

  float e = target_rpm - meas_rpm;
  float de = (e - e_prev) / (dt_ms / 1000.0f);
  e_prev = e;

  // Feedforward: motor statik sürtünme (stiction) eşiğini aşmak için minimum PWM tabanı
  float ff = (target_rpm > 0.0f) ? 25.0f : -25.0f;
  float u = ff + (KP * 2.0f * e) + (KI * e_i) + (KD * de);
  int pwm = (int)constrain(u, -PWM_MAX, PWM_MAX);

  // Sadece PWM saturate olmadığında integral artır
  if (abs(pwm) < PWM_MAX) {
    e_i += e * (dt_ms / 1000.0f);
    e_i = constrain(e_i, -PID_INTEGRAL_LIMIT, PID_INTEGRAL_LIMIT);
  }

  return pwm;
}

void processPacket(uint8_t msg_id, const uint8_t* pl, uint8_t len) {
  if (!g_host_seen) {
    g_host_seen = true;
#if ENABLE_TEXT_BANNER
    Serial.println(F("[INFO] Host baglandi - binary telemetri baslatiliyor."));
    Serial.flush();
#endif
  }

  switch (msg_id) {
    case Proto::HEARTBEAT: {
      g_last_heartbeat_ms = millis();
      Proto::writePacket(Serial, Proto::HEARTBEAT_ACK, nullptr, 0);
      digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    } break;
    case Proto::WHEEL_CMD: {
      if (len < 8) break;
      memcpy(&g_left_target_rpm, &pl[0], 4);
      memcpy(&g_right_target_rpm, &pl[4], 4);
      g_last_heartbeat_ms = millis(); // komut da heartbeat sayılır
    } break;
    case Proto::HEAD_CMD: {
      if (len < 4) break;
      float angle_deg;
      memcpy(&angle_deg, &pl[0], 4);
      // steps/degree hesabı: motor_steps_per_rev * microsteps / 360
      const float motor_steps_per_rev = 200.0f; // 1.8 derece stepper
      const float micro = 16.0f; // tmc ayarında
      float steps_per_deg = (motor_steps_per_rev * micro) / 360.0f;
      long target_steps = lroundf(angle_deg * steps_per_deg);
      head_stepper.moveTo(target_steps);
      g_last_heartbeat_ms = millis();
    } break;
  }
}

void setup() {
  setupIO();

  Serial.begin(SERIAL_BAUD);
  delay(200); // Serial Monitor'ün açılmasına küçük bir pay

  g_imu_ok = imuInit();
  g_tmc_ok = tmcInit();

  printBanner();

  // Kısa açılış LED işareti
  for (uint8_t i = 0; i < 6; ++i) {
    digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    delay(80);
  }
  digitalWrite(STATUS_LED, LOW);

  g_last_control_ms = millis();
  g_last_heartbeat_ms = millis();
  g_last_text_ms = millis();

  // Donanım watchdog (2 s güvenlik marjı)
  wdt_enable(WDTO_2S);
}

void loop() {
  // Watchdog besle
  wdt_reset();

  // TMC/Stepper güncelle
  head_stepper.run();

  // Seri parser
  static Proto::Parser parser;
  while (Serial.available() > 0) {
    uint8_t b = Serial.read();
    uint8_t id; const uint8_t* payload; uint8_t pl_len;
    if (parser.feed(b, id, payload, pl_len)) {
      processPacket(id, payload, pl_len);
    }
  }

  // Kontrol döngüsü 50 Hz
  loopControl();

  // Host bağlı değilken seri ekrana okunabilir durum satırı bas
#if ENABLE_TEXT_STATUS
  if (!g_host_seen && (millis() - g_last_text_ms >= TEXT_STATUS_PERIOD_MS)) {
    g_last_text_ms = millis();
    printStatusLine();
  }
#endif
}
