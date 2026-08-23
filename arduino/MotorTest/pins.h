#pragma once

/*
 * MotorTest pin haritasi - GERCEK KABLOLAMA (2026-08 montaj)
 * ----------------------------------------------------------
 * DIKKAT: bu dosya ana firmware'in arduino/astro_firmware/include/pins.h
 * dosyasindan FARKLIDIR. Burasi sahadaki kablolamayi yansitir; firmware
 * pin haritasi kafa motoru DC'ye cevrildikten sonra senkronlanacak.
 */

// ─────────────────────────────────────────────────────────────
//  Tekerlek motorlari - BTS7960 (RPWM / LPWM)
// ─────────────────────────────────────────────────────────────
#define L_MOTOR_PWM_FWD   5    // sol  RPWM  -> Timer3A
#define L_MOTOR_PWM_REV   6    // sol  LPWM  -> Timer4A
#define R_MOTOR_PWM_FWD   9    // sag  RPWM  -> Timer2B
#define R_MOTOR_PWM_REV   10   // sag  LPWM  -> Timer2A

// ─────────────────────────────────────────────────────────────
//  Kafa motoru - BTS7960 (enkoderli 25mm redüktörlü DC, 12V)
//  R_EN ve L_EN 5V'a sabitlenmis: surucu her zaman aktif,
//  MCU tarafindan donanimsal olarak kesilemez.
// ─────────────────────────────────────────────────────────────
#define HEAD_MOTOR_PWM_FWD 44  // kafa RPWM  -> Timer5C
#define HEAD_MOTOR_PWM_REV 45  // kafa LPWM  -> Timer5B

// ─────────────────────────────────────────────────────────────
//  Tekerlek enkoderleri (A kanallari kesme destekli olmali)
//  Mega kesme pinleri: 2, 3, 18, 19, 20, 21
// ─────────────────────────────────────────────────────────────
#define L_ENC_A 2     // INT0
#define L_ENC_B 4
#define R_ENC_A 3     // INT1
#define R_ENC_B 22    // (!) ESKIDEN 9 IDI - o pini sag motor RPWM aldi.
                      //     Sag enkoderin B kablosunu 9'dan 22'ye alin.

// ─────────────────────────────────────────────────────────────
//  Kafa enkoderi
//  (!) 20 = SDA, 21 = SCL. Bu test sketch'i I2C kullanmadigi icin
//      burada sorun yok. ANA FIRMWARE'de MPU-6050 bu hatta oldugundan
//      cakisir; orada kafa enkoderi 18/19'a tasinmali.
// ─────────────────────────────────────────────────────────────
#define HEAD_ENC_A 20 // INT3  (SDA)
#define HEAD_ENC_B 21 // INT2  (SCL)

// ─────────────────────────────────────────────────────────────
//  Durum LED'i
// ─────────────────────────────────────────────────────────────
#define STATUS_LED 13
