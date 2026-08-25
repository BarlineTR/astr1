/*
 * MotorTest - basit motor test sketch'i (sol / sag / kafa)
 * --------------------------------------------------------
 * Tek amaci: motorlar donuyor mu, dogru yone mi donuyor, enkoderler
 * sayiyor mu? PID, IMU, TMC2209 ve ROS protokolu YOKTUR.
 *
 * Kart      : Arduino Mega 2560
 * Seri hiz  : 115200 baud, satir sonu "Newline"
 * Kutuphane : gerekmiyor (sadece Arduino core)
 * Pinler    : bkz. pins.h
 *
 * Komutlar:
 *   h        yardim
 *   t        tekerlek otomatik testi (ileri/geri/sag/sol)
 *   y        kafa otomatik testi (kisa saga, kisa sola - nazik)
 *   l <pwm>  sol tekerlek   (-255..255)
 *   r <pwm>  sag tekerlek   (-255..255)
 *   b <pwm>  iki tekerlek birden
 *   k <pwm>  kafa motoru    (-255..255, tavan HEAD_PWM_LIMIT)
 *   c <derece>  kafayi <derece> kadar cevirdikten sonra tick/derece hesapla
 *   s        DUR
 *   e        enkoder sayaclarini sifirla
 *   m        anlik durumu yaz
 *
 * GUVENLIK: robotu tekerlekleri havada olacak sekilde sehpaya alin.
 */

#include <Arduino.h>
#include "pins.h"

// ====== Ayarlar ======
static const uint32_t SERIAL_BAUD     = 115200;
static const int      PWM_MAX         = 255;

// PWM frekansi: 490 Hz (varsayilan) motorlarda duyulur bir vinlama yapar.
// 1 yapilirsa Timer2/3/4/5 prescaler'i 1'e cekilir -> 31.37 kHz (sessiz).
// NOT: BTS7960 datasheet'i ~25 kHz'e kadar veriyor; 31 kHz pratikte yaygin
// kullaniliyor ama spec'in bir tik ustunde. Suruculer isinirsa 0 yapin.
#define PWM_HIGH_FREQ 0

static const int TEST_PWM = 60;
static const uint32_t TEST_STEP_MS = 1000;

// Kafa 1000 rpm'lik bir motor; tam PWM'de savrulur. Tavani dusuk tutuyoruz.
static const int      HEAD_PWM_LIMIT  = 100;   // kafa icin izin verilen maks PWM
static const int      HEAD_TEST_PWM   = 80;    // kafa otomatik test PWM'i
static const uint32_t HEAD_TEST_MS    = 400;   // kafa test adim suresi (kisa!)

// Kafada limit switch yok: mekanik dayanaga dayanirsa motor stall olur.
// PWM verilmesine ragmen bu sure boyunca tick degismezse kafa kesilir.
static const uint32_t HEAD_STALL_MS   = 300;

static const uint32_t REPORT_MS       = 250;   // durum yazdirma periyodu
static const uint32_t IDLE_TIMEOUT_MS = 10000; // elle komutta oto-stop

// ====== Enkoder ======
volatile int32_t g_left_ticks = 0;
volatile int32_t g_right_ticks = 0;
volatile int32_t g_head_ticks = 0;

void leftEncA()  { g_left_ticks  += digitalRead(L_ENC_B)    ? -1 : +1; }
void rightEncA() { g_right_ticks += digitalRead(R_ENC_B)    ? -1 : +1; }
void headEncA()  { g_head_ticks  += digitalRead(HEAD_ENC_B) ? -1 : +1; }

int32_t readTicks(volatile int32_t& src) {
  int32_t v;
  noInterrupts();
  v = src;
  interrupts();
  return v;
}

// ====== Durum ======
static int g_left_pwm = 0;
static int g_right_pwm = 0;
static int g_head_pwm = 0;

static bool     g_auto_wheels = false;
static bool     g_auto_head = false;
static uint8_t  g_auto_step = 0;
static uint32_t g_auto_step_ms = 0;

static uint32_t g_last_report_ms = 0;
static uint32_t g_last_cmd_ms = 0;

static int32_t  g_prev_l = 0, g_prev_r = 0, g_prev_h = 0;
static uint32_t g_prev_ms = 0;

// Kafa stall takibi
static int32_t  g_head_stall_ref = 0;
static uint32_t g_head_stall_ms = 0;

static char    g_line[32];
static uint8_t g_line_len = 0;

// ====== Motor surus ======
void setMotorPWM(int pwm_fwd_pin, int pwm_rev_pin, int val) {
  // BTS7960: ayni anda tek tarafa PWM ver, digerini sifirla.
  if (val >= 0) {
    analogWrite(pwm_rev_pin, 0);
    analogWrite(pwm_fwd_pin, val);
  } else {
    analogWrite(pwm_fwd_pin, 0);
    analogWrite(pwm_rev_pin, -val);
  }
}

void setLeft(int v) {
  g_left_pwm = constrain(v, -PWM_MAX, PWM_MAX);
  setMotorPWM(L_MOTOR_PWM_FWD, L_MOTOR_PWM_REV, g_left_pwm);
}

void setRight(int v) {
  g_right_pwm = constrain(v, -PWM_MAX, PWM_MAX);
  setMotorPWM(R_MOTOR_PWM_FWD, R_MOTOR_PWM_REV, g_right_pwm);
}

void setHead(int v) {
  g_head_pwm = constrain(v, -HEAD_PWM_LIMIT, HEAD_PWM_LIMIT);
  setMotorPWM(HEAD_MOTOR_PWM_FWD, HEAD_MOTOR_PWM_REV, g_head_pwm);
  // stall dedektorunu sifirla
  g_head_stall_ref = readTicks(g_head_ticks);
  g_head_stall_ms = millis();
}

void stopWheels() { setLeft(0); setRight(0); }
void stopAll()    { stopWheels(); setHead(0); }

// ====== Yazdirma ======
void printHelp() {
  Serial.println();
  Serial.println(F("=============================================="));
  Serial.println(F("  MotorTest - sol / sag / kafa motor testi"));
  Serial.println(F("=============================================="));
  Serial.println(F("  h           yardim"));
  Serial.println(F("  t           TEKERLEK otomatik testi"));
  Serial.println(F("  y           KAFA otomatik testi (nazik)"));
  Serial.println(F("  l <pwm>     sol tekerlek  (-255..255)"));
  Serial.println(F("  r <pwm>     sag tekerlek  (-255..255)"));
  Serial.println(F("  b <pwm>     iki tekerlek birden"));
  Serial.print  (F("  k <pwm>     kafa motoru   (tavan "));
  Serial.print(HEAD_PWM_LIMIT); Serial.println(F(")"));
  Serial.println(F("  c <derece>  kafa tick/derece kalibrasyonu"));
  Serial.println(F("  s           DUR"));
  Serial.println(F("  e           enkoderleri sifirla"));
  Serial.println(F("  m           anlik durum"));
  Serial.println(F("----------------------------------------------"));
  Serial.println(F("  Pinler: sol 5/6  sag 9/10  kafa 44/45"));
  Serial.println(F("  Enkoder: sol 2/3  sag 18/19  kafa 20/21"));
  Serial.println(F("----------------------------------------------"));
  Serial.println(F("  UYARI: tekerlekleri havada test edin!"));
  Serial.print  (F("  Elle komutta ")); Serial.print(IDLE_TIMEOUT_MS / 1000UL);
  Serial.println(F(" sn sonra otomatik durur."));
  Serial.println(F("=============================================="));
}

void printStatus() {
  uint32_t now = millis();
  int32_t l = readTicks(g_left_ticks);
  int32_t r = readTicks(g_right_ticks);
  int32_t hd = readTicks(g_head_ticks);

  float dt_s = (now - g_prev_ms) / 1000.0f;
  int32_t dl = l - g_prev_l;
  int32_t dr = r - g_prev_r;
  int32_t dh = hd - g_prev_h;
  g_prev_l = l; g_prev_r = r; g_prev_h = hd; g_prev_ms = now;

  long l_tps = (dt_s > 0.0f) ? (long)(dl / dt_s) : 0; // tick/saniye
  long r_tps = (dt_s > 0.0f) ? (long)(dr / dt_s) : 0;
  long h_tps = (dt_s > 0.0f) ? (long)(dh / dt_s) : 0;

  Serial.print(F("PWM L=")); Serial.print(g_left_pwm);
  Serial.print(F(" R="));    Serial.print(g_right_pwm);
  Serial.print(F(" K="));    Serial.print(g_head_pwm);
  Serial.print(F(" | TICK L=")); Serial.print(l);
  Serial.print(F(" R="));    Serial.print(r);
  Serial.print(F(" K="));    Serial.print(hd);
  Serial.print(F(" | HIZ L=")); Serial.print(l_tps);
  Serial.print(F(" R="));    Serial.print(r_tps);
  Serial.print(F(" K="));    Serial.print(h_tps);
  Serial.print(F(" tick/s"));

  // Teshis: PWM veriliyor ama enkoder saymiyor
  if (g_left_pwm  != 0 && dl == 0) Serial.print(F("  [!] SOL donmuyor/enkoder yok"));
  if (g_right_pwm != 0 && dr == 0) Serial.print(F("  [!] SAG donmuyor/enkoder yok"));
  if (g_head_pwm  != 0 && dh == 0) Serial.print(F("  [!] KAFA donmuyor/enkoder yok"));
  // Teshis: ileri komutta geri sayiyor -> kablolar ters
  if (g_left_pwm  > 0 && dl < 0)   Serial.print(F("  [!] SOL ters yonde"));
  if (g_right_pwm > 0 && dr < 0)   Serial.print(F("  [!] SAG ters yonde"));
  if (g_head_pwm  > 0 && dh < 0)   Serial.print(F("  [!] KAFA ters yonde"));

  Serial.println();
}

// ====== Otomatik testler ======
struct AutoStep {
  const char* name;
  int left;
  int right;
};

static const AutoStep WHEEL_STEPS[] = {
  { "ILERI",     TEST_PWM,  TEST_PWM  },
  { "DUR",       0,         0         },
  { "GERI",     -TEST_PWM, -TEST_PWM  },
  { "DUR",       0,         0         },
  { "SAGA DON",  TEST_PWM, -TEST_PWM  },
  { "DUR",       0,         0         },
  { "SOLA DON", -TEST_PWM,  TEST_PWM  },
  { "DUR",       0,         0         },
};
static const uint8_t WHEEL_STEP_COUNT = sizeof(WHEEL_STEPS) / sizeof(WHEEL_STEPS[0]);

// Kafa: once bir yone, sonra ayni sure ters yone -> kabaca basladigi yere doner
static const int HEAD_STEPS[] = { HEAD_TEST_PWM, 0, -HEAD_TEST_PWM, 0 };
static const uint8_t HEAD_STEP_COUNT = sizeof(HEAD_STEPS) / sizeof(HEAD_STEPS[0]);

void wheelTestStart() {
  g_auto_head = false;
  setHead(0);
  g_auto_wheels = true;
  g_auto_step = 0;
  g_auto_step_ms = millis();
  Serial.println(F("\n--- TEKERLEK TESTI BASLADI (durdurmak icin 's') ---"));
  Serial.print(F(">>> ")); Serial.println(WHEEL_STEPS[0].name);
  setLeft(WHEEL_STEPS[0].left);
  setRight(WHEEL_STEPS[0].right);
}

void headTestStart() {
  g_auto_wheels = false;
  stopWheels();
  g_auto_head = true;
  g_auto_step = 0;
  g_auto_step_ms = millis();
  Serial.println(F("\n--- KAFA TESTI BASLADI (durdurmak icin 's') ---"));
  Serial.println(F("    Kisa saga, sonra kisa sola. Kafayi gozle takip edin."));
  setHead(HEAD_STEPS[0]);
}

void autoTestUpdate() {
  if (g_auto_wheels) {
    if (millis() - g_auto_step_ms < TEST_STEP_MS) return;
    g_auto_step++;
    if (g_auto_step >= WHEEL_STEP_COUNT) {
      g_auto_wheels = false;
      stopWheels();
      Serial.println(F("--- TEKERLEK TESTI BITTI ---\n"));
      return;
    }
    g_auto_step_ms = millis();
    Serial.print(F(">>> ")); Serial.println(WHEEL_STEPS[g_auto_step].name);
    setLeft(WHEEL_STEPS[g_auto_step].left);
    setRight(WHEEL_STEPS[g_auto_step].right);
  }
  else if (g_auto_head) {
    if (millis() - g_auto_step_ms < HEAD_TEST_MS) return;
    g_auto_step++;
    if (g_auto_step >= HEAD_STEP_COUNT) {
      g_auto_head = false;
      setHead(0);
      Serial.println(F("--- KAFA TESTI BITTI ---\n"));
      return;
    }
    g_auto_step_ms = millis();
    setHead(HEAD_STEPS[g_auto_step]);
    Serial.print(F(">>> kafa PWM = ")); Serial.println(g_head_pwm);
  }
}

// Kafada limit switch yok: dayanaga dayandiysa motoru kes.
void headStallCheck() {
  if (g_head_pwm == 0) return;

  int32_t now_ticks = readTicks(g_head_ticks);
  if (now_ticks != g_head_stall_ref) {
    g_head_stall_ref = now_ticks;
    g_head_stall_ms = millis();
    return;
  }

  if (millis() - g_head_stall_ms > HEAD_STALL_MS) {
    g_auto_head = false;
    setHead(0);
    Serial.println(F("[STALL] Kafa donmuyor -> motor kesildi."));
    Serial.println(F("        Mekanik dayanak, sikisma veya enkoder kopuklugu."));
  }
}

// ====== Komut ayristirma ======
void handleCommand(char* line) {
  while (*line == ' ') line++;
  char c = *line;
  if (c == '\0') return;

  int value = atoi(line + 1); // "l -120" -> -120 (sayi yoksa 0)

  switch (c) {
    case 'h': case 'H': case '?':
      printHelp();
      break;

    case 't': case 'T':
      wheelTestStart();
      break;

    case 'y': case 'Y':
      headTestStart();
      break;

    case 's': case 'S':
      g_auto_wheels = false;
      g_auto_head = false;
      stopAll();
      Serial.println(F("[STOP] tum motorlar kesildi."));
      break;

    case 'l': case 'L':
      g_auto_wheels = false;
      setLeft(value);
      g_last_cmd_ms = millis();
      Serial.print(F("[CMD] sol PWM = ")); Serial.println(g_left_pwm);
      break;

    case 'r': case 'R':
      g_auto_wheels = false;
      setRight(value);
      g_last_cmd_ms = millis();
      Serial.print(F("[CMD] sag PWM = ")); Serial.println(g_right_pwm);
      break;

    case 'b': case 'B':
      g_auto_wheels = false;
      setLeft(value);
      setRight(value);
      g_last_cmd_ms = millis();
      Serial.print(F("[CMD] iki tekerlek PWM = ")); Serial.println(g_left_pwm);
      break;

    case 'k': case 'K':
      g_auto_head = false;
      setHead(value);
      g_last_cmd_ms = millis();
      Serial.print(F("[CMD] kafa PWM = ")); Serial.print(g_head_pwm);
      if (abs(value) > HEAD_PWM_LIMIT) {
        Serial.print(F("  (tavana kirpildi: ")); Serial.print(HEAD_PWM_LIMIT); Serial.print(F(")"));
      }
      Serial.println();
      break;

    case 'c': case 'C': {
      // Kafayi <derece> kadar cevirdikten sonra: tick/derece hesapla
      int32_t ticks = readTicks(g_head_ticks);
      if (value == 0) {
        Serial.println(F("[KALIBRASYON] Kullanim:"));
        Serial.println(F("  1) 'e' ile enkoderleri sifirlayin"));
        Serial.println(F("  2) kafayi bilinen bir aciya cevirin"));
        Serial.println(F("     (elle, ya da 'k 60' verip 's' ile durdurup aciyi olcun)"));
        Serial.println(F("  3) 'c <derece>' yazin, orn: c 90"));
        Serial.print  (F("  Su anki kafa tick = ")); Serial.println(ticks);
      } else {
        float per_deg = (float)ticks / (float)value;
        Serial.print(F("[KALIBRASYON] tick=")); Serial.print(ticks);
        Serial.print(F("  aci=")); Serial.print(value);
        Serial.print(F(" derece  ->  tick/derece = "));
        Serial.println(per_deg, 3);
        Serial.print(F("  360 derece = ")); Serial.print(per_deg * 360.0f, 1);
        Serial.println(F(" tick"));
        Serial.println(F("  Bu degeri firmware'deki HEAD_TICKS_PER_DEG sabitine yazin."));
      }
    } break;

    case 'e': case 'E':
      noInterrupts();
      g_left_ticks = 0;
      g_right_ticks = 0;
      g_head_ticks = 0;
      interrupts();
      g_prev_l = 0; g_prev_r = 0; g_prev_h = 0;
      g_head_stall_ref = 0;
      Serial.println(F("[OK] enkoder sayaclari sifirlandi."));
      break;

    case 'm': case 'M':
      printStatus();
      break;

    default:
      Serial.print(F("[?] bilinmeyen komut: "));
      Serial.println(c);
      break;
  }
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      g_line[g_line_len] = '\0';
      if (g_line_len > 0) handleCommand(g_line);
      g_line_len = 0;
    } else if (g_line_len < sizeof(g_line) - 1) {
      g_line[g_line_len++] = ch;
    }
  }
}

// ====== setup / loop ======
void setup() {
  pinMode(STATUS_LED, OUTPUT);

  pinMode(L_MOTOR_PWM_FWD, OUTPUT);
  pinMode(L_MOTOR_PWM_REV, OUTPUT);
  pinMode(R_MOTOR_PWM_FWD, OUTPUT);
  pinMode(R_MOTOR_PWM_REV, OUTPUT);
  pinMode(HEAD_MOTOR_PWM_FWD, OUTPUT);
  pinMode(HEAD_MOTOR_PWM_REV, OUTPUT);
  stopAll();

  pinMode(L_ENC_A, INPUT_PULLUP);
  pinMode(L_ENC_B, INPUT_PULLUP);
  pinMode(R_ENC_A, INPUT_PULLUP);
  pinMode(R_ENC_B, INPUT_PULLUP);
  pinMode(HEAD_ENC_A, INPUT_PULLUP);
  pinMode(HEAD_ENC_B, INPUT_PULLUP);

  attachInterrupt(digitalPinToInterrupt(L_ENC_A),    leftEncA,  RISING);
  attachInterrupt(digitalPinToInterrupt(R_ENC_A),    rightEncA, RISING);
  attachInterrupt(digitalPinToInterrupt(HEAD_ENC_A), headEncA,  RISING);

#if PWM_HIGH_FREQ
  // Timer2 (pin 9,10), Timer3 (pin 5), Timer4 (pin 6), Timer5 (pin 44,45)
  // prescaler 1 -> 8-bit phase-correct PWM: 16MHz / (1 * 510) = 31.37 kHz.
  // millis()/micros() Timer0'da oldugu icin etkilenmez.
  TCCR2B = (TCCR2B & 0xF8) | 0x01;
  TCCR3B = (TCCR3B & 0xF8) | 0x01;
  TCCR4B = (TCCR4B & 0xF8) | 0x01;
  TCCR5B = (TCCR5B & 0xF8) | 0x01;
#endif

  Serial.begin(SERIAL_BAUD);
  delay(200);
  printHelp();
  Serial.println(F("Hazir. Tekerlekler icin 't', kafa icin 'y' yazin."));

  g_prev_ms = millis();
  g_last_report_ms = millis();
  g_last_cmd_ms = millis();
  g_head_stall_ms = millis();
}

void loop() {
  readSerialCommands();
  autoTestUpdate();
  headStallCheck();

  // Elle verilen komutta guvenlik icin otomatik durdurma
  bool manual_active = (!g_auto_wheels && (g_left_pwm != 0 || g_right_pwm != 0)) ||
                       (!g_auto_head   &&  g_head_pwm != 0);
  if (manual_active && (millis() - g_last_cmd_ms > IDLE_TIMEOUT_MS)) {
    if (!g_auto_wheels) stopWheels();
    if (!g_auto_head)   setHead(0);
    Serial.println(F("[AUTO-STOP] zaman asimi, motorlar kesildi."));
  }

  // Periyodik durum
  if (millis() - g_last_report_ms >= REPORT_MS) {
    g_last_report_ms = millis();
    printStatus();
    bool moving = (g_left_pwm != 0 || g_right_pwm != 0 || g_head_pwm != 0);
    digitalWrite(STATUS_LED, moving ? HIGH : LOW);
  }
}
