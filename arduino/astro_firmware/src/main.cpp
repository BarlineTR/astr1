#include <Arduino.h>
#include <Wire.h>
#include <TMCStepper.h>
#include <AccelStepper.h>
#include <avr/wdt.h>

#include "pins.h"
#include "protocol.h"

// ====== Parametreler ======
static constexpr uint32_t SERIAL_BAUD = 115200; // 115200 alternatif
static constexpr float CONTROL_HZ = 50.0f;
static constexpr uint32_t CONTROL_DT_MS = (uint32_t)(1000.0f / CONTROL_HZ);

static constexpr int32_t TICKS_PER_REV_L = 2048; // enkoder CPR*4 uygun biçimde ayarlayın
static constexpr int32_t TICKS_PER_REV_R = 2048;

static constexpr float WHEEL_R_L = 0.06f; // metre (örnek 60mm)
static constexpr float WHEEL_R_R = 0.06f;

static constexpr float KP = 0.6f, KI = 0.2f, KD = 0.0f; // 50 Hz PID için örnek
static constexpr int PWM_MAX = 255;
static constexpr float PID_INTEGRAL_LIMIT = 50.0f; // ✅ FIX: Daha dar anti-windup limit

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

static bool g_motors_enabled = true;
static uint32_t g_diag_flags = 0;

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

void imuInit() {
  Wire.begin();
  // ✅ FIX: I2C timeout ayarla (5ms)
  Wire.setWireTimeout(5000, true); // 5000 microseconds = 5 ms
  
  delay(50);
  // MPU-6050: power management 0x6B = 0x00
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x6B); Wire.write(0x00);
  Wire.endTransmission();

  // Gyro full-scale = ±2000 dps (0x1B=0x18), Accel ±2g (0x1C=0x00)
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x1B); Wire.write(0x18);
  Wire.endTransmission();

  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(0x1C); Wire.write(0x00);
  Wire.endTransmission();
}

bool imuRead() {
  // Okuma: ACCEL_XOUT_H (0x3B) -> 14 byte
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

void tmcInit() {
  pinMode(HEAD_EN_PIN, OUTPUT);
  digitalWrite(HEAD_EN_PIN, LOW); // enable low active olabilir, donanıma göre ayarlayın

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
  
  // ✅ FIX: PWM frekansını artır (Timer 4: pin 6,7,8 -> 31.25 kHz)
  // Mega Timer 4 için prescaler=1
  TCCR4B = (TCCR4B & 0xF8) | 0x01; // 31.25 kHz PWM
}

void stopMotors() {
  setLeftPWM(0);
  setRightPWM(0);
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

  // ✅ FIX: Enkoder okuma atomik yap (AVR'de int32_t atomik değil)
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

  // ✅ FIX: PID anti-windup iyileştirildi (conditional integration)
  auto pid_step = [&](float target_rpm, float meas_rpm, float& e_i, float& e_prev, int pwm_out)->int {
    float e = target_rpm - meas_rpm;
    float de = (e - e_prev) / (dt_ms / 1000.0f);
    e_prev = e;
    
    float u = KP * e + KI * e_i + KD * de;
    int pwm = (int)constrain(u, -PWM_MAX, PWM_MAX);
    
    // Conditional integration: sadece PWM saturate olmadığında integral artır
    if (abs(pwm) < PWM_MAX) {
      e_i += e * (dt_ms / 1000.0f);
      e_i = constrain(e_i, -PID_INTEGRAL_LIMIT, PID_INTEGRAL_LIMIT);
    }
    
    return pwm;
  };

  int l_pwm = 0, r_pwm = 0;
  if (g_motors_enabled) {
    l_pwm = pid_step(g_left_target_rpm, l_rpm_meas, g_left_err_i, g_left_err_prev, l_pwm);
    r_pwm = pid_step(g_right_target_rpm, r_rpm_meas, g_right_err_i, g_right_err_prev, r_pwm);
  }
  setLeftPWM(l_pwm);
  setRightPWM(r_pwm);

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
  imuInit();
  tmcInit();

  g_last_control_ms = millis();
  g_last_heartbeat_ms = millis();

  // ✅ FIX: Watchdog timeout 2s'ye çıkarıldı (güvenlik marjı)
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
