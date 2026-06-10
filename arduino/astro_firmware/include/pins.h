#pragma once

// Motor sürücü BTS7960 pinleri (örnek):
// Her motor için iki PWM: FWD ve REV. Enable pinleri opsiyonel.
#define L_MOTOR_PWM_FWD   5
#define L_MOTOR_PWM_REV   6
#define R_MOTOR_PWM_FWD   7
#define R_MOTOR_PWM_REV   8

// Enkoder pinleri (Mega dış kesme destekli A kanalları: 2,3,18,19,20,21)
#define L_ENC_A 2     // INT0
#define L_ENC_B 4
#define R_ENC_A 3     // INT1
#define R_ENC_B 9

// TMC2209 Step/Dir pinleri (kafa):
#define HEAD_STEP_PIN  10
#define HEAD_DIR_PIN   11
#define HEAD_EN_PIN    12

// TMC2209 UART (Mega üzerinde HW Serial1 kullanımı önerilir: TX1=18, RX1=19)
#define TMC2209_SERIAL Serial1
#define TMC2209_ADDRESS 0b00  // MS1/MS2 adres pinlerine göre ayarlayın

// IMU I2C adresi (MPU-6050 için tipik adres)
#define IMU_I2C_ADDR 0x68

// LED / Durum
#define STATUS_LED 13
