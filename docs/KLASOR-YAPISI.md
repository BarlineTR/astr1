# ASTRO V1 — Klasör Yapısı

> Her dizinin ve önemli dosyanın ne işe yaradığı. Neyin nerede olduğunu
> ararken buraya bakın. Sistemin nasıl çalıştığı için `docs/PROJE-OZETI.md`.

**Son güncelleme:** 2026-08-23

`🆕` işaretli dosyalar Spec #1 kapsamında eklenecektir
(`docs/superpowers/plans/2026-08-23-realtime-s2s-voice-core.md`).

---

## Üst düzey

```
astr1/
├── ros2_ws/          ROS 2 çalışma alanı — kodun neredeyse tamamı
├── arduino/          Arduino Mega firmware (PlatformIO)
├── scripts/          Kurulum, kayıt ve doğrulama yardımcıları
├── docs/             Tasarım, plan ve kullanım dokümanları
├── .github/          CI iş akışları
├── .env              Yapılandırma — GİZLİ, git'e girmez
├── .env.example      Yapılandırma şablonu (anahtarların tamamı burada)
├── README.md         Kurulum ve çalıştırma
├── requirements.in   Doğrudan Python bağımlılıkları (uv kaynağı)
├── requirements.txt  Kilitlenmiş bağımlılıklar (uv çıktısı)
├── pytest.ini        Test yolları ve ROS eklenti devre dışı bırakma
└── COLCON_IGNORE     Repo kökünün colcon paketi sanılmasını engeller
```

**Git'e girmeyenler:** `.env`, `.venv/`, `ros2_ws/build|install|log/`,
`faces/`, `Persons/`, `ros2_ws/astro_memory.json`. Ayrıntı: `.gitignore`.

---

## `ros2_ws/src/` — ROS 2 paketleri

### `astro_ai/` — konuşma zekâsı

Projenin beyni. Realtime WebSocket köprüsü, persona, hafıza, tool yürütme.

```
astro_ai/astro_ai/
├── astro_realtime_node.py    Realtime WebSocket düğümü — ana konuşma motoru
├── ai_brain_node.py          Cascaded mod bilişsel arka ucu (Groq/Gemini)
├── realtime/                 🆕 S2S çekirdeği — ROS'suz, ağsız, donanımsız
│   ├── turn_machine.py       🆕 Konuşma turu FSM + cancel/generation guard'ları
│   ├── session_config.py     🆕 session.update payload üreticisi (VAD dahil)
│   └── engine_state.py       🆕 Bağlantı durumu (turn durumundan ayrık)
├── brain/                    Sosyal biliş: niyet, duygu, ilişki, dünya modeli
├── memory_v2/                Katmanlı hafıza: epizodik, semantik, uzamsal
├── contracts/                Alt sistemler arası veri tipleri
├── spatial/                  LiDAR takibi ve uzamsal füzyon
├── tools_arbitration/        Tool kaydı, yönlendirme, güvenlik guard'ı
├── memory_manager.py         Kalıcı profil ve olgu deposu (SQLite)
├── persona_engine.py         Kişilik modları ve sistem promptu üretimi
├── provider_registry.py      LLM sağlayıcı yetenekleri ve hata sınıflandırma
├── circuit_breaker.py        Sağlayıcı devre kesici
├── conversation_session.py   Oturum yaşam döngüsü ve özetleme
├── inference_engine.py       LLM çağrı sarmalayıcısı
├── multimodal_perception.py  Görme + ses + uzam füzyonu
├── officials_database.py     Tanınan kişiler veritabanı
├── repetition_guard.py       Tekrar eden cevapları engelleme
├── state_machine.py          Robot üst durumu (LISTENING, THINKING…)
├── performance_profiler.py   Gecikme ölçümü
├── cloud_manager.py          Bulut erişilebilirlik kontrolü
└── profiler_node.py          Profil telemetri düğümü
```

> `tools_arbitration/` şu an yalnızca testler tarafından kullanılıyor.
> Spec #2'de gerçek tool bus olarak canlandırılacak.

Testler: `astro_ai/test/`

| Dosya | Kapsam |
|---|---|
| `test_p0_runtime_stabilization.py` | Çalışma zamanı kararlılığı, Arduino, ses hataları |
| `test_provider_and_fallback.py` | Sağlayıcı zinciri, Realtime değişmezleri, barge-in |
| `test_cognitive_social_brain.py` | Sosyal biliş, hafıza v2 |
| `test_conversational_hardening.py` | Konuşma sağlamlaştırma |
| `test_core_modules.py` | Çekirdek modül birim testleri |
| `test_turn_machine.py` | 🆕 Turn FSM, cancel guard, generation isolation |
| `test_session_config.py` | 🆕 VAD yapılandırması, `interrupt_response` |
| `test_engine_state.py` | 🆕 Bağlantı durumu, iki FSM'in ayrıklığı |
| `test_audio_ownership.py` | 🆕 Cascaded hat sökümü, tek playback sahibi (statik) |
| `test_launch_voice_engine.py` | 🆕 `voice_engine` launch ayrımı |
| `test_move_robot_safety.py` | 🆕 Motor sağlığı kapısı |

### `astro_audio/` — ses giriş/çıkış

```
astro_audio/astro_audio/
├── audio_stream_node.py       ⭐ TEK DONANIM SAHİBİ — realtime modu G/Ç
├── audio_capture_node.py      Cascaded mod mikrofonu (realtime'da başlatılmaz)
├── speech_recognition_node.py Cascaded mod STT (realtime'da başlatılmaz)
├── tts_node.py                Cascaded mod TTS (realtime'da başlatılmaz)
├── audio_output_manager.py    Donanım çalma soyutlaması (sounddevice/aplay)
├── playback_watchdog.py       Takılan çalmayı tespit
├── memory_guard.py            TTS motorlarının bellek koruması
├── sentence_chunker.py        Metni akış için cümlelere böler
├── tts_router.py              TTS motor seçimi ve fallback zinciri
├── tts_orchestrator.py        TTS istek sıralaması
├── tts_metrics.py             TTS gecikme telemetrisi
├── base_tts_engine.py         TTS motor arayüzü
├── openai_tts_engine.py       OpenAI TTS
├── elevenlabs_engine.py       ElevenLabs TTS
├── edge_tts_engine.py         Edge-TTS (acil durum fallback'i)
├── local_offline_tts_engine.py espeak (son çare)
├── local_xtts_engine.py       XTTS yerel motoru
├── xtts_client.py             XTTS istemcisi
├── xtts_worker.py             XTTS alt süreci
├── stt_router.py              STT motor seçimi
├── realtime_engine.py         Realtime TTS motor sarmalayıcısı
├── voice_recognizer.py        Konuşmacı biyometrisi
├── speaker_db.py              Ses parmak izi veritabanı
└── local_audio_resources.py   Yerel model yolları
```

> `⭐ audio_stream_node.py` sesin tek sahibidir. `tts_node.py`'nin
> `/audio/realtime_output_pcm` aboneliği Spec #1'de **koddan silinir** —
> tek sahiplik launch bayrağına değil koda bağlanır.

Testler: `astro_audio/test/`

| Dosya | Kapsam |
|---|---|
| `test_production_hardening.py` | STT doğrulama, yankı bağışıklığı |
| `test_hybrid_tts.py` | TTS motor zinciri |
| `test_realtime_edge_fallback.py` | Realtime → Edge-TTS düşüşü |
| `test_tts_runtime_acceptance.py` | TTS çalışma zamanı kabulü |
| `test_hw_audio_ownership.py` | 🆕 Gerçek donanımla tek sahiplik (opt-in) |

### `astro_base/` — Arduino köprüsü

```
astro_base/
├── src/serial_bridge.py   Seri protokol, heartbeat, IMU, enkoder, motor güvenliği
└── msg/                   WheelCmd, HeadCmd mesaj tanımları
```

`/wheel_cmds` ve `/head_cmd` dinler; `/imu/data_raw`, `/joint_states`,
`/arduino/diagnostics` yayınlar. **`/odom` yayınlamaz ve `/cmd_vel` dinlemez** —
aradaki `base_bridge` düğümü henüz yok (Spec #2).

### `astro_vision/` — görme

```
astro_vision/astro_vision/
├── oak_perception_node.py       OAK-D RGB + derinlik
├── oak_spatial_native_node.py   VPU üzerinde çalışan uzamsal algı
├── face_detector_node.py        Yüz tespiti ve takibi
├── face_recognizer.py           Yüz tanıma
├── face_db.py                   Yüz veritabanı
├── webcam_publisher_node.py     Webcam alternatifi
└── image_utils.py               Görüntü dönüşümleri
```

`astro_vision/scripts/` altında tanınan kişilerin portrelerini indiren
yardımcı betikler bulunur.

### `astro_lidar/`, `astro_navigation/`, `astro_description/`, `astro_sim/`

```
astro_lidar/       RPLIDAR sürücüsü + scan_filter_node
astro_navigation/  slam_toolbox.yaml, nav2_params.yaml, kayıtlı haritalar
astro_description/ astro.urdf.xacro — fiziksel ölçüler, TF ağacı
astro_sim/         Gazebo dünyası, EKF yapılandırması
```

### `astro_bringup/` — başlatma

```
astro_bringup/
├── launch/
│   ├── bringup.launch.py           ⭐ Ana giriş — voice_engine burada seçilir
│   ├── sensors.launch.py           LiDAR + kamera + cascaded ses + AI
│   ├── realtime_sensors.launch.py  audio_stream_node + astro_realtime_node
│   ├── base.launch.py              serial_bridge
│   └── robot.launch.py             Minimal robot
├── config/astro_params.yaml        Tekerlek yarıçapı, ticks_per_rev, seri port
└── astro_bringup/env_utils.py      .env'i yukarı doğru arayıp bulur
```

---

## `arduino/astro_firmware/`

```
├── platformio.ini      Kart ve baud (500000) yapılandırması
├── include/pins.h      Pin haritası
├── include/protocol.h  Paket formatı, mesaj kimlikleri
└── src/main.cpp        Ana döngü, heartbeat ACK, 500 ms motor watchdog
```

---

## `scripts/`

| Betik | İş |
|---|---|
| `install.sh` | Tek komutla kurulum |
| `build.sh` | colcon derleme sarmalayıcısı |
| `install_stt_deps.sh` | STT bağımlılıkları |
| `install_xtts.sh` | XTTS kurulumu |
| `install_face_models.sh` | Yüz tanıma modelleri |
| `enroll_face.py` | Fotoğraftan/kameradan yüz kaydı |
| `enroll_speaker.py` | WAV'dan/mikrofondan ses kaydı |
| `check_env_drift.py` | `.env` ↔ kod tutarlılık denetimi |
| `test_wheels.py` | Tekerlek self-test'i |
| `validate_hybrid_tts.py` | TTS zinciri doğrulaması |
| `run_production_soak_test.py` | Uzun süreli dayanım testi |
| `acceptance_p0.sh` | 🆕 Spec #1 Kapı 2 kabul tablosu |

---

## `docs/`

| Dosya | İçerik |
|---|---|
| `PROJE-OZETI.md` | ASTRO nedir, mimari, güvenlik sınırları, nerede duruyoruz |
| `KLASOR-YAPISI.md` | Bu dosya |
| `proje-incelemesi.md` | Kod sağlığı denetimi (P0–P3 bulguları) |
| `simulasyon-ve-gercek-robot.md` | Simülasyon ↔ gerçek robot, kalibrasyon, `base_bridge` boşluğu |
| `jetson-cuda-stt.md` | Jetson'da CUDA hızlandırmalı STT |
| `superpowers/specs/` | Tasarım dokümanları (spec) |
| `superpowers/plans/` | Adım adım uygulama planları |

---

## Ana ROS topic'leri

| Topic | Tip | Yayınlayan → Dinleyen |
|---|---|---|
| `/audio/realtime_input_pcm` | `String` (b64 PCM) | `audio_stream_node` → `astro_realtime_node` |
| `/audio/realtime_output_pcm` | `String` (b64 PCM) | `astro_realtime_node` → `audio_stream_node` |
| `/audio/playback_active` | `Bool` | `audio_stream_node` → `astro_realtime_node` |
| `/tts/interrupt` | `Bool` | Barge-in sinyali |
| `/tts/say` | `String` | `ai_brain_node` → `tts_node` (cascaded) |
| `/speech/text` | `String` | `speech_recognition_node` → `ai_brain_node` |
| `/realtime/state` | `String` | `astro_realtime_node` telemetrisi |
| `/vision/recognized_person` | `String` | `face_detector_node` → beyin |
| `/arduino/diagnostics` | `DiagnosticArray` | `serial_bridge` → motor güvenlik kapısı |
| `/wheel_cmds` | `WheelCmd` | → `serial_bridge` |
| `/cmd_vel` | `Twist` | Nav2/Gazebo. **Gerçek robotta tüketicisi yok** (Spec #2) |
| `/scan` | `LaserScan` | RPLIDAR → SLAM/Nav2 |
| `/joint_states`, `/imu/data_raw` | | `serial_bridge` → odometri |

---

## Nereye ne eklenir

| Ekleme | Yer |
|---|---|
| Yeni Realtime tool | `astro_realtime_node._send_session_update()` şeması + `_execute_realtime_tool()` dalı |
| Yeni TTS motoru | `astro_audio/`, `base_tts_engine.py` arayüzü + `tts_router.py` zinciri |
| Yeni yapılandırma anahtarı | `.env.example` (zorunlu) + okuyan modül. `scripts/check_env_drift.py` sürüklenmeyi yakalar |
| Yeni düğüm | İlgili paket + `setup.py` `console_scripts` + launch dosyası |
| Turn/session mantığı | `astro_ai/realtime/` — ROS ve ağ **import edilmez** |
| Yeni test | İlgili paketin `test/` dizini; `pytest.ini` `testpaths` zaten kapsıyor |
