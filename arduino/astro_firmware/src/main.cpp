#include <Arduino.h>
#include <Wire.h>
#include <TMCStepper.h>
#include <AccelStepper.h>
#include <avr/wdt.h>

#include "pins.h"
#include "protocol.h"

// ====== Parametreler ======
static constexpr uint32_t SERIAL_BAUD = 500000;
static constexpr float CONTROL_HZ = 50.0f;
static constexpr uint32_t CONTROL_DT_MS = (uint32_t)(1000.0f / CONTROL_HZ);

static constexpr int32_t TICKS_PER_REV_L = 2048;
static constexpr int32_t TICKS_PER_REV_R = 2048;

static constexpr float WHEEL_R_L = 0.06f;
static constexpr float WHEEL_R_R = 0.06f;

static constexpr float KP = 0.6f, KI = 0.2f, KD = 0.0f;
static constexpr int PWM_MAX = 160;  // Donanımsal koruma için maksimum PWM sinyal limiti (0-255 arası)
static constexpr float MAX_TARGET_RPM = 60.0f;
static constexpr float MAX_RPM_ACCEL = 40.0f; // RPM/saniye ivmelenme limiti (Soft-Start)
static constexpr float PID_INTEGRAL_LIMIT = 40.0f;

// ====== Global Durum ======
volatile int32_t g_left_ticks = 0;
volatile int32_t g_right_ticks = 0;

static int32_t g_left_last_ticks = 0;
static int32_t g_right_last_ticks = 0;

static float g_left_target_rpm = 0.0f;
static float g_right_target_rpm = 0.0f;

static float g_left_curr_target_rpm = 0.0f;
static float g_right_curr_target_rpm = 0.0f;

static float g_left_err_i = 0.0f, g_right_err_i = 0.0f;
static float g_left_err_prev = 0.0f, g_right_err_prev = 0.0f;

// BTS7960 Dead-time için son PWM durumları
static int g_left_prev_pwm = 0;
static int g_right_prev_pwm = 0;

// Motor Sıkışma (Stall) Algılama Süreçleri
static uint32_t g_left_stall_timer = 0;
static uint32_t g_right_stall_timer = 0;

static uint32_t g_last_control_ms = 0;
static uint32_t g_last_heartbeat_ms = 0;

static bool g_motors_enabled = false;
static bool g_stall_fault = false;
static uint32_t g_diag_flags = 0;

// IMU ham değerleri -> m/s2, rad/s dönüştürülecek
static float ax, ay, az, gx, gy, gz; 
static uint32_t imu_last_us = 0;

// TMC2209 (UART üzerinden konfigürasyon)
TMC2209Stepper tmc2209(&TMC2209_SERIAL, 0.11f, TMC2209_ADDRESS); // 0.11 ohm örnek Rsense
AccelStepper head_stepper(AccelStepper::DRIVER, HEAD_STEP_PIN, HEAD_DIR_PIN);

// ====== Güvenli Sürücü ve Yardımcı Fonksiyonlar ======

// Hardware düzeyinde BTS7960 sürücülerini aç/kapat
inline void enableDriverHardware(bool enable) {
  digitalWrite(L_MOTOR_EN, enable ? HIGH : LOW);
  digitalWrite(R_MOTOR_EN, enable ? HIGH : LOW);
}

// BTS7960 Dead-Time (Ölü Zaman) Korumalı PWM Ayarı
inline void setMotorPWMWithDeadtime(int pwm_fwd_pin, int pwm_rev_pin, int val, int& prev_val) {
  val = constrain(val, -PWM_MAX, PWM_MAX);

  // Yön değiştirme (Shoott-through) tespiti: Pozitiften negatife veya tam tersi
  if ((prev_val > 0 && val < 0) || (prev_val < 0 && val > 0)) {
    // Önce iki PWM hattını da sıfırla ve MOSFET'lerin kapanması için bekle
    analogWrite(pwm_fwd_pin, 0);
    analogWrite(pwm_rev_pin, 0);
    delayMicroseconds(50); // 50 mikro saniyelik kritik ölü zaman gecikmesi
  }

  if (val > 0) {
    analogWrite(pwm_rev_pin, 0);
    analogWrite(pwm_fwd_pin, val);
  } else if (val < 0) {
    analogWrite(pwm_fwd_pin, 0);
    analogWrite(pwm_rev_pin, -val);
  } else {
    analogWrite(pwm_fwd_pin, 0);
    analogWrite(pwm_rev_pin, 0);
  }
  prev_val = val;
}

inline void setLeftPWM(int v) { setMotorPWMWithDeadtime(L_MOTOR_PWM_FWD, L_MOTOR_PWM_REV, v, g_left_prev_pwm); }
inline void setRightPWM(int v){ setMotorPWMWithDeadtime(R_MOTOR_PWM_FWD, R_MOTOR_PWM_REV, v, g_right_prev_pwm); }

void leftEncA() {
  bool b = digitalRead(L_ENC_B);
  g_left_ticks += b ? -1 : +1;
}
void rightEncA() {
  bool b = digitalRead(R_ENC_B);
  g_right_ticks += b ? -1 : +1;
}

void imuInit() {
  Wire.begin();
  Wire.setWireTimeout(5000, true); // 5000 microseconds = 5 ms
  
  delay(50);
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x6B); Wire.write(0x00);
  Wire.endTransmission();

  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x1B); Wire.write(0x18);
  Wire.endTransmission();

  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x1C); Wire.write(0x00);
  Wire.endTransmission();
}

bool imuRead() {
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) {
    g_diag_flags |= 0x02; // IMU_READ_FAIL flag
    return false;
  }

  uint8_t n = Wire.requestFrom(IMU_I2C_ADDR, 14u, true);
  if (n != 14) {
    g_diag_flags |= 0x02; // IMU_READ_FAIL flag
    return false;
  }

  auto rd = []() -> int16_t {
    int16_t h = Wire.read();
    int16_t l = Wire.read();
    return (int16_t)((h << 8) | l);
  };

  int16_t axr = rd();
  int16_t ayr = rd();
  int16_t azr = rd();
  int16_t tmp = rd(); (void)tmp;
  int16_t gxr = rd();
  int16_t gyr = rd();
  int16_t gzr = rd();

  const float A_SCALE = 9.80665f / 16384.0f;
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

void tmcInit() {
  pinMode(HEAD_EN_PIN, OUTPUT);
  digitalWrite(HEAD_EN_PIN, LOW);

  TMC2209_SERIAL.begin(500000);
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
}

void setupIO() {
  pinMode(STATUS_LED, OUTPUT);
  pinMode(L_MOTOR_PWM_FWD, OUTPUT);
  pinMode(L_MOTOR_PWM_REV, OUTPUT);
  pinMode(R_MOTOR_PWM_FWD, OUTPUT);
  pinMode(R_MOTOR_PWM_REV, OUTPUT);

  pinMode(L_MOTOR_EN, OUTPUT);
  pinMode(R_MOTOR_EN, OUTPUT);
  enableDriverHardware(false); // Başlangıçta sürücüleri donanımsal olarak kapat

  pinMode(L_ENC_A, INPUT_PULLUP);
  pinMode(L_ENC_B, INPUT_PULLUP);
  pinMode(R_ENC_A, INPUT_PULLUP);
  pinMode(R_ENC_B, INPUT_PULLUP);

  attachInterrupt(digitalPinToInterrupt(L_ENC_A), leftEncA, RISING);
  attachInterrupt(digitalPinToInterrupt(R_ENC_A), rightEncA, RISING);
  
  // Timer 4 PWM Frekansı -> 31.25 kHz
  TCCR4B = (TCCR4B & 0xF8) | 0x01;
}

void stopMotors() {
  enableDriverHardware(false);
  setLeftPWM(0);
  setRightPWM(0);
  g_left_curr_target_rpm = 0.0f;
  g_right_curr_target_rpm = 0.0f;
  g_left_err_i = 0.0f;
  g_right_err_i = 0.0f;
}

void publishIMU() {
  uint8_t payload[6 * 4 + 4];
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
  float dt_s = dt_ms / 1000.0f;
  g_last_control_ms = now;

  // Watchdog & Heartbeat Güvenlik Kontrolü
  if (now - g_last_heartbeat_ms > 500 || g_stall_fault) {
    g_motors_enabled = false;
    stopMotors();
    if (g_stall_fault) {
      g_diag_flags |= 0x04; // STALL_FAULT flag
    } else {
      g_diag_flags |= 0x01; // WATCHDOG_TIMEOUT flag
    }
  } else {
    g_motors_enabled = true;
    enableDriverHardware(true); // Motorlar aktifleştiğinde sürücüleri hardware seviyesinde aç
    g_diag_flags &= ~0x05;
  }

  // Atomik Enkoder Okuması
  int32_t l_ticks, r_ticks;
  noInterrupts();
  l_ticks = g_left_ticks;
  r_ticks = g_right_ticks;
  interrupts();
  
  int32_t dl = l_ticks - g_left_last_ticks;
  int32_t dr = r_ticks - g_right_last_ticks;
  g_left_last_ticks = l_ticks;
  g_right_last_ticks = r_ticks;

  float dt_min = dt_ms / 60000.0f;
  float l_rpm_meas = (dl / (float)TICKS_PER_REV_L) / dt_min;
  float r_rpm_meas = (dr / (float)TICKS_PER_REV_R) / dt_min;

  // ====== SOFT-START (İvme Sınırlaması / Slew Rate Limiting) ======
  auto ramp = [&](float target, float current) -> float {
    float max_change = MAX_RPM_ACCEL * dt_s;
    if (target > current) return min(current + max_change, target);
    else return max(current - max_change, target);
  };
  g_left_curr_target_rpm = ramp(g_left_target_rpm, g_left_curr_target_rpm);
  g_right_curr_target_rpm = ramp(g_right_target_rpm, g_right_curr_target_rpm);

  // ====== MOTOR STALL (SIKIŞMA / KİLİTLENME) KORUMASI ======
  // Eğer motora belirli bir RPM hedeflenmişse fakat enkoder hareket etmiyorsa akımı kes!
  auto checkStall = [&](float target_rpm, int32_t ticks_diff, uint32_t& stall_timer) {
    if (abs(target_rpm) > 5.0f && ticks_diff == 0) {
      if (stall_timer == 0) stall_timer = now;
      else if (now - stall_timer > 600) { // 600 ms boyunca tekerlek kilitlendiyse
        g_stall_fault = true;
      }
    } else {
      stall_timer = 0;
    }
  };
  if (g_motors_enabled) {
    checkStall(g_left_curr_target_rpm, dl, g_left_stall_timer);
    checkStall(g_right_curr_target_rpm, dr, g_right_stall_timer);
  }

  // ====== PID KONTROL DÖNGÜSÜ ======
  auto pid_step = [&](float target_rpm, float meas_rpm, float& e_i, float& e_prev)->int {
    float e = target_rpm - meas_rpm;
    float de = (e - e_prev) / dt_s;
    e_prev = e;
    
    float u = KP * e + KI * e_i + KD * de;
    int pwm = (int)constrain(u, -PWM_MAX, PWM_MAX);
    
    // Anti-windup (Conditional integration)
    if (abs(pwm) < PWM_MAX) {
      e_i += e * dt_s;
      e_i = constrain(e_i, -PID_INTEGRAL_LIMIT, PID_INTEGRAL_LIMIT);
    }
    
    return pwm;
  };

  int l_pwm = 0, r_pwm = 0;
  if (g_motors_enabled && !g_stall_fault) {
    l_pwm = pid_step(g_left_curr_target_rpm, l_rpm_meas, g_left_err_i, g_left_err_prev);
    r_pwm = pid_step(g_right_curr_target_rpm, r_rpm_meas, g_right_err_i, g_right_err_prev);
    setLeftPWM(l_pwm);
    setRightPWM(r_pwm);
  } else {
    stopMotors();
  }

  // IMU oku (50 Hz)
  imuRead();
  publishIMU();
  publishEncoders(dt_ms * 1000u, dl, dr);

  // Basit diagnostik: bayraklar
  uint16_t vbat = 12000; // mV (örn. gelecekte ADC ile ölç)
  int16_t temp = 2500;   // 25.00 C
  publishDiag(vbat, temp, g_diag_flags);
}

void processPacket(uint8_t msg_id, const uint8_t* pl, uint8_t len) {
  switch (msg_id) {
    case Proto::HEARTBEAT: {
      g_last_heartbeat_ms = millis();
      Proto::writePacket(Serial, Proto::HEARTBEAT_ACK, nullptr, 0);
      digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    } break;
    case Proto::WHEEL_CMD: {
      if (len < 8) break;
      float left_rpm, right_rpm;
      memcpy(&left_rpm, &pl[0], 4);
      memcpy(&right_rpm, &pl[4], 4);
      g_left_target_rpm = constrain(left_rpm, -MAX_TARGET_RPM, MAX_TARGET_RPM);
      g_right_target_rpm = constrain(right_rpm, -MAX_TARGET_RPM, MAX_TARGET_RPM);
      g_last_heartbeat_ms = millis();
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
  stopMotors();
  Serial.begin(SERIAL_BAUD);
  imuInit();
  tmcInit();

  g_last_control_ms = millis();
  g_last_heartbeat_ms = 0;  // require valid heartbeat before enabling motors

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
}
