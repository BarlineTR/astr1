# ASTRO V1 — Proje Özeti

> Bu dosya "ASTRO nedir, hangi parçalardan oluşur, şu an nerede duruyor"
> sorularının tek cevabıdır. Kurulum ve çalıştırma için `README.md`,
> klasör haritası için `docs/KLASOR-YAPISI.md`.

**Son güncelleme:** 2026-08-23 · **Aktif branch:** `feat/realtime-s2s-voice-core`

---

## 1. ASTRO nedir

ASTRO, ROS 2 Humble üzerinde çalışan, Türkçe konuşan sosyal bir mobil robottur.
Üç yeteneği bir arada taşır:

- **Konuşma** — OpenAI Realtime API ile düşük gecikmeli speech-to-speech
- **Algı** — OAK-D kamerayla yüz tanıma, nesne inceleme; ReSpeaker ile ses yönü
  ve konuşmacı tanıma
- **Hareket** — RPLIDAR + SLAM Toolbox + Nav2 ile haritalama ve navigasyon,
  Arduino Mega üzerinden diferansiyel sürüş

Çalıştığı donanım: NVIDIA Jetson (üretim) + geliştirme laptop'u (simülasyon ve
testler).

---

## 2. Mimari — dört çekirdek

```
                         ASTRO V1
                            │
                 ┌──────────┴──────────┐
                 │                     │
             SOCIAL CORE          MOBILITY CORE
                 │                     │
          OpenAI Realtime          Nav2 / SLAM
          Konuşma, persona          LiDAR
          Barge-in, tools           Arduino, tekerlek
                 │                     │
                 └──────────┬──────────┘
                            │
                       ACTION BUS
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
       VISION            MEMORY            MOTION
       OAK-D             SQLite           /cmd_vel
```

Yönlendirici ilke: **Realtime, canlı konuşmanın yürütme motorudur — sistemin
sahibi değildir.** Görme, hafıza ve hareket ayrı alt sistemlerdir; Realtime
onlara tool çağrıları üzerinden erişir. Model saçma bir motor komutu üretse bile
güvenlik katmanı onu sınırlar.

### Ses veri yolu — tek sahip kuralı

```
        ReSpeaker (16 kHz)
              │
              ▼
      ┌───────────────────┐
      │ audio_stream_node │  ◄── TEK DONANIM SAHİBİ (giriş + çıkış)
      └───────────────────┘
         │             ▲
  /audio/realtime   /audio/realtime
   _input_pcm        _output_pcm
         │             │
         ▼             │
   ┌──────────────────────────┐
   │   astro_realtime_node    │
   │   EngineState (bağlantı) │
   │   TurnMachine  (tur)     │
   └──────────────────────────┘
         │             ▲
         ▼             │
    OpenAI Realtime WebSocket
    (server VAD sahibi)
```

Sesin tek bir sahibi vardır ve bu **launch bayrağıyla değil kodla** garanti
edilir. Aynı ALSA cihazına iki süreç yazarsa `Device or resource busy` ve
`write to closed file` hataları döner; ASTRO'nun geçmişindeki en inatçı hata
sınıfı budur.

### İki state machine, asla karışmaz

| Eksen | Modül | Durumlar |
|---|---|---|
| Bağlantı | `realtime/engine_state.py` | `REALTIME_PRIMARY`, `RECONNECTING`, `FALLBACK_ACTIVE` |
| Konuşma turu | `realtime/turn_machine.py` | `IDLE`, `USER_SPEAKING`, `RESPONSE_PENDING`, `RESPONSE_STREAMING`, `TOOL_EXECUTING`, `RESPONSE_CANCELLING` |

Bir turun ortasında bağlantı kopabilir; bağlantı sağlıklıyken hiçbir tur açık
olmayabilir. İki ekseni karıştırmak tanımsız durumlar üretir — bu yüzden iki
modül birbirini import etmez ve bu kural testle korunur.

---

## 3. Ses motoru modları

`voice_engine` launch argümanı hangi beynin `audio_stream_node`'un arkasında
duracağını seçer:

| Mod | Akış | Başlatılan düğümler |
|---|---|---|
| `realtime` (varsayılan) | Mic PCM → OpenAI → hoparlör | `audio_stream_node`, `astro_realtime_node` |
| `cascaded` | Mic → Whisper → LLM → Edge-TTS | `audio_capture_node`, `speech_recognition_node`, `ai_brain_node`, `tts_node` |

```bash
ros2 launch astro_bringup bringup.launch.py voice_engine:=realtime
ros2 launch astro_bringup bringup.launch.py voice_engine:=cascaded
```

**`ai_brain_node` silinmemiştir.** Realtime modunda başlatılmaz, ama cascaded
modun bilişsel arka ucu olarak ve ileride internet kesintisi fallback'i olarak
korunur. Groq/Gemini altyapısı çöpe gitmez.

### Turn ve kesme otoritesi

Yanıt üretimi ve barge-in **sunucunun** işidir:
`session.audio.input.turn_detection` altında `create_response: true` ve
`interrupt_response: true`. İstemci `speech_stopped` üzerine
`response.create` göndermez.

Python tarafında kalan tek ses sorumluluğu **akustik yankı korumasıdır**:
robot kendi sesini duyup kendini kesmesin diye kısa bir koruma penceresi ve
çalmayı durdurma. Konuşma mantığı sunucuda, akustik koruma yerelde.

---

## 4. Alt sistemler

| Alt sistem | Paket | Sorumluluk |
|---|---|---|
| Ses G/Ç | `astro_audio` | Tek donanım sahibi, 16↔24 kHz yeniden örnekleme, playback kuyruğu |
| Konuşma zekâsı | `astro_ai` | Realtime WebSocket, persona, hafıza, tool yürütme |
| Görme | `astro_vision` | OAK-D, yüz tanıma/kayıt, uzamsal algı |
| LiDAR | `astro_lidar` | RPLIDAR sürücüsü ve tarama filtresi |
| Navigasyon | `astro_navigation` | SLAM Toolbox, Nav2 |
| Taban | `astro_base` | Arduino seri köprüsü, heartbeat, IMU, enkoder |
| Model | `astro_description` | URDF/xacro, TF ağacı |
| Simülasyon | `astro_sim` | Gazebo dünyası, EKF |
| Başlatma | `astro_bringup` | Launch kompozisyonu, `.env` enjeksiyonu |

---

## 5. Güvenlik sınırları

**Hareket, motor sağlığı kanıtlanmadan gerçekleşmez.** `move_robot` tool'u şu
dördü doğrulanmadan `/cmd_vel`'e hiçbir şey yazmaz:

```
serial_connected  = true
handshake         = true
heartbeat_healthy = true
motor_enabled     = true
```

Bilgi `/arduino/diagnostics`'ten gelir ve **bayatlık kontrolü** vardır: Arduino
susarsa son "sağlıklı" mesaj hareketi yetkilendirmez.

**Durdurma komutu kapıya takılmaz** — durmak her zaman güvenlidir.

**Bilinen boşluk:** `/cmd_vel`'in gerçek robotta tüketicisi yoktur.
`serial_bridge` `/wheel_cmds` bekler. Aradaki `base_bridge` düğümü henüz
yazılmamıştır (bkz. `docs/simulasyon-ve-gercek-robot.md` §4). Bu yüzden
`move_robot` gerçek robotta `no_motion_backend` ile **açıkça reddeder**.
Sessizce `success` dönüp tekerleğin dönmemesi hem kullanıcıya yalan söyler hem
modelin dünya modelini bozar.

---

## 6. Şu an nerede duruyoruz

### Tamamlanan

- ROS 2 paket iskeleti, URDF, TF ağacı, Gazebo simülasyonu
- SLAM Toolbox + Nav2 yapılandırması (simülasyonda çalışıyor)
- Arduino firmware (500000 baud), seri protokol, heartbeat TX/ACK
- OAK-D görme hattı, yüz tanıma ve kayıt
- Realtime WebSocket bağlantısı, persona motoru, hafıza (SQLite + `memory_v2`)
- Sağlayıcı kayıt defteri, devre kesici, fallback zinciri
- `voice_engine` launch ayrımı (`bab0512`)
- Sunucu tarafı `create_response`, tool çağrılarının event loop'tan çıkarılması (`bab0512`)

### Spec #1: Realtime S2S Ses Çekirdeği — Kapı 1 tamamlandı

Branch: `feat/realtime-s2s-voice-core`

- ✅ Turn, session ve motor durumu ROS'suz modüllere çıkarıldı (`astro_ai/realtime/`)
- ✅ `interrupt_response` eklendi; barge-in otoritesi sunucuya devredildi
- ✅ Cascaded metin enjeksiyon hattı söküldü (`ai_brain_node` korundu)
- ✅ `tts_node`'un realtime PCM aboneliği koddan kaldırıldı
- ✅ `move_robot` motor sağlığı kanıtlanmadan reddediyor (fail-closed)
- ✅ `realtime_sensors` `voice_engine`'e bağlandı
- ⏳ **Kapı 2 bekliyor** — Jetson'da `scripts/acceptance_p0.sh`

Uygulama sırasında testlerin yakaladığı iki gerçek tasarım hatası düzeltildi:
`response.created` `IDLE` durumunda yok sayılıyordu (proaktif selamlama boyunca
makine desync kalır, barge-in ölürdü), ve kimlik karşılaştırılamadığında ses
düşürülüyordu (bayatlık kanıtlanamazken susmak robotu gereksiz susturur).

Tasarım: `docs/superpowers/specs/2026-08-23-realtime-s2s-voice-core-design.md`
Plan: `docs/superpowers/plans/2026-08-23-realtime-s2s-voice-core.md`

### Sıradaki

| Spec | Konu |
|---|---|
| #2 | `base_bridge` düğümü — `/cmd_vel` ↔ `/wheel_cmds`, `/odom`, `odom → base_footprint` tf. Gerçek robotta SLAM/Nav2'nin önündeki tek engel. Sonrasında `move_robot` gerçekten hareket ettirir. |
| #3 | Fallback motorunun `astro_realtime_node`'dan ayrı modüle çıkarılması; `EngineState` geçişlerinin bağlanması |
| P1 | Idle learning, persona ve hafıza yazma politikası (her cümle SQLite'a gitmez) |

---

## 7. Doğrulama modeli

İş iki kapıdan geçer:

**Kapı 1 — geliştirme laptop'unda otomatik.** `pytest` + `colcon build`. Turn
state machine, session yapılandırması, launch kompozisyonu ve ses sahipliği
burada kanıtlanır. Gerçek donanım gerektiren tek-sahip testi opt-in'dir
(`ASTRO_HW_AUDIO_TEST=1`).

**Kapı 2 — Jetson'da manuel.** `scripts/acceptance_p0.sh` launch log'unu okuyup
ses sahipliği, turn yaşam döngüsü, barge-in, motor sağlığı ve hata sayaçlarını
PASS/FAIL tablosu olarak basar.

### Testleri çalıştırma

```bash
source /opt/ros/humble/setup.bash
source ros2_ws/install/setup.bash
.venv/bin/python -m pytest
```

Workspace source edilmezse 32 test `ModuleNotFoundError: astro_base` /
`LookupError: astro_bringup` ile **ortam kaynaklı** olarak düşer. Bu bir kod
hatası değildir.

### Bilinen baseline fail'leri

| Test | Sebep |
|---|---|
| `test_21_migration_from_legacy_json` | Legacy JSON migration 0 fact üretiyor (`memory_v2`) |
| `test_xtts_client_batch_size_default_is_one` | Tek başına geçiyor → test kirliliği, sıra bağımlı |
| `test_wake_with_command_forwards_turn` | **Dalgalı** — ~4 koşudan 1'inde düşer, tek başına geçer |

> Bu suite sıra bağımlı durum sızdırıyor; baseline'ı tek koşuyla ölçmek
> yanıltıcıdır. Üç tanesi de `bab0512` üzerinde de mevcuttu.

---

## 8. Yapılandırma

Tüm ayarlar repo kökündeki `.env`'dedir; şablon `.env.example`. Launch dosyaları
`.env`'i CWD'den yukarı doğru arayıp bulur ve her düğüm sürecine enjekte eder —
`ros2 launch` komutunu nereden verdiğiniz fark etmez.

Öne çıkan anahtarlar:

| Anahtar | Ne yapar |
|---|---|
| `REALTIME_MODEL` | Realtime modeli (varsayılan `gpt-realtime-2.1-mini`) |
| `REALTIME_VAD_TYPE` | `server_vad` \| `semantic_vad` |
| `REALTIME_VAD_SILENCE_MS` | Konuşma bitti sayılmadan önceki sessizlik |
| `REALTIME_INTERRUPT_RESPONSE` | Barge-in otoritesi (`true` = sunucu) |
| `ASTRO_MOTION_BACKEND` | Boşsa `move_robot` reddeder |
| `AUDIO_INPUT_DEVICE` / `AUDIO_OUTPUT_DEVICE` | Ses cihazı sabitleme |

Model ve VAD değerleri mimariye sabitlenmez. Hangi `silence_duration_ms`'in
Türkçe doğal konuşmada iyi davrandığı gerçek Jetson benchmark'ıyla belirlenir;
`gpt-realtime-2.1-mini` için dolaşan hız iddialarının doğrulanabilir kaynağı
yoktur.
