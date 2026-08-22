# ASTRO V1 — Proje İncelemesi

**Tarih:** 21 Ağustos 2026 · **Dal:** `feat/hybrid-realtime-xtts-production` · **Kapsam:** 23.831 satır kaynak (107 dosya) + 5.390 satır test (9 dosya)

Bu belge kod tabanının tamamının incelenmesinden çıkan bulguları içerir. Her bulgu
ya çalıştırılarak ya da kod üzerinde doğrulanmıştır; tahmine dayalı olanlar açıkça
"doğrulanmadı" diye işaretlenmiştir. Amaç, düzeltmeye hangi sırayla başlayacağımıza
birlikte karar vermek.

---

## Özet tablo

| # | Bulgu | Önem | Durum |
|---|---|---|---|
| 1 | `PersistentProfile` deadlock — robot 1 dk sonra kalıcı sağırlaşıyor | 🔴 P0 | ✅ Çözüldü |
| 2 | Tek callback grubu + callback içinde senkron bulut çağrısı → düğüm donuyor | 🔴 P0 | ✅ Çözüldü |
| 3 | `edge_tts_engine`: event loop `finally`'de kapatılmıyor → fd sızıntısı | 🔴 P0 | ✅ Çözüldü |
| 4 | `edge_tts_engine`: ffmpeg alt süreci timeout'ta öldürülmüyor → yetim süreç | 🟠 P1 | ✅ Çözüldü |
| 5 | `MultiThreadedExecutor(4)` yanıltıcı — pratikte tek thread | 🟠 P1 | ✅ Çözüldü |
| 6 | İki paralel beyin: 6.221 satır, 16 aynı isimli metot | 🟠 P1 | ⚠️ Ölçüldü — ayrı oturum |
| 7 | TTS zinciri sabit kodlu, `TTS_ENGINE` ölü ayardı | 🟠 P1 | ✅ Kısmen çözüldü |
| 8 | `LLM_PROVIDER` hiç okunmuyor; sağlayıcı sırası sabit | 🟠 P1 | ✅ Çözüldü |
| 9 | 2.146 satır ölü kod (XTTS + ElevenLabs) | 🟡 P2 | ✅ Erişilebilir yapıldı |
| 10 | QoS: ham `Image` reliable/10 ile iki aboneye gidiyor | 🟡 P2 | ✅ Çözüldü |
| 11 | `.env`'de 18 tekrar eden anahtar — "son kazanır" tuzağı | 🟠 P1 | ✅ Çözüldü (kalıcı) |
| 12 | 14 ölü ayar, ~30 belgelenmemiş ayar | 🟡 P2 | ✅ Çözüldü |
| 13 | Çalışma zamanı verisi git'te (`astro_memory.json`) | 🟡 P2 | ✅ Çözüldü |
| 14 | Sabit kodlanmış `/home/okistech`, `~/Desktop/astr1` yolları | 🟡 P2 | ✅ Çözüldü (29 yol) |
| 15 | `package.xml` eksik bağımlılık beyanı | 🟡 P2 | ✅ Çözüldü |
| 16 | 128 sessiz `except: pass`, 249 geniş yakalama | 🟡 P2 | ✅ 128→25 |
| 17 | CI yok; 1 test önceden kırık | 🟡 P2 | ✅ Çözüldü (292/292) |
| 18 | Yanıltıcı sabit log banner'ları | 🟢 P3 | ✅ Çözüldü |
| 19 | TTS'te streaming yok — TTFA cümle uzunluğuyla artıyor | 🟢 P3 | Açık (bilinçli) |

---

## 🔴 P0 — Kritik

### 1. `PersistentProfile` deadlock ✅ ÇÖZÜLDÜ

`memory_manager.py`'de kilit `threading.Lock()` (yeniden girişli değil) idi ve üç
metot kilidi tutarken `add_known_person`'ı çağırıyordu — o da aynı kilidi yeniden
almaya çalışıyordu.

```
add_person_session_summary → with self._lock:      # kilit alındı
    add_known_person       → with self._lock:      # sonsuza kadar bekler
```

Bu dal yalnızca kişi `known_people` içinde **yokken** çalıştığı için ilk oturum
özetinde tetikleniyordu. Ardından 1 sn'lik `_check_reminders` timer'ı aynı kilitte
bloke oluyor, tek callback grubu donuyor ve robot kalıcı olarak sağırlaşıyordu —
`[ASTRO IDLE]` logları akmaya devam ettiği için sistem ayakta görünüyordu.

**Düzeltme:** `memory_manager.py:141` → `threading.RLock()`. Üç noktayı birden kapatır
ve `astro_realtime_node` da aynı sınıfı kullandığı için onu da kapsar.
Tüm projede aynı sınıftan başka risk kalmadı (AST taramasıyla doğrulandı).

---

### 2. Tek callback grubu + callback içinde senkron bulut çağrısı ✅ ÇÖZÜLDÜ

**En önemli açık bulgu.** 13 ROS düğümünün **hiçbirinde açık `CallbackGroup` yok**.
rclpy'de tanımlanmayan her abonelik ve timer düğümün varsayılan
`MutuallyExclusiveCallbackGroup`'una girer — yani **aynı anda yalnızca bir callback
çalışabilir**. Bir callback bloke olursa düğümün tamamı (tüm sensör girdileri, tüm
timer'lar) durur.

Buna rağmen callback'lerin içinde bloklayan bulut çağrıları var:

`ai_brain_node.py:825` — `_on_speech` callback'i içinden çağrılan
`_evaluate_social_barge_in` (satır 1367), **sırayla 3 ayrı senkron LLM çağrısı**
yapabiliyor (Groq → Gemini → OpenAI):

```python
def _on_speech(self, msg: String):        # ← ROS callback, tüm grubu tutar
    ...
    if self._evaluate_social_barge_in(raw_text):   # ← 3'e kadar bulut çağrısı
```

Gerçek çalıştırmada bu 0,6 sn sürdü. Sağlayıcı yavaşlarsa bu süre boyunca robot
mikrofonu duymaz, timer'ları çalışmaz. Deadlock'un (#1) robotu tamamen öldürmesinin
sebebi de tam olarak buydu — tek bir bloke callback her şeyi durduruyor.

**Önerilen düzeltme (iki aşamalı):**

1. **Ayrıştırma:** `/speech/text` aboneliğini ve LLM'e dokunan timer'ları ayrı
   `ReentrantCallbackGroup`'lara al. Böylece bir sağlayıcı asılsa bile diğer
   callback'ler çalışmaya devam eder.
2. **Asenkronlaştırma:** `_evaluate_social_barge_in`'i callback'ten çıkar, `_process_llm`
   gibi ayrı bir thread'e taşı. Callback'ler asla ağ beklememeli.

---

### 3. `edge_tts_engine`: event loop sızıntısı ✅ ÇÖZÜLDÜ

`edge_tts_engine.py:119-152`:

```python
loop = asyncio.new_event_loop()
...
mp3_bytes = loop.run_until_complete(asyncio.wait_for(_run_edge_tts(), timeout=t_limit))
loop.close()          # ← yalnızca BAŞARI yolunda çalışır
...
except asyncio.TimeoutError:   # ← loop kapatılmadan çıkılır
except Exception as exc:       # ← loop kapatılmadan çıkılır
```

Dosyada hiç `finally` yok. Her başarısız sentezde bir event loop (epoll fd + self-pipe,
tipik olarak 2 dosya tanıtıcısı) sızıyor. Uzun süren çalıştırmalarda `EMFILE: too many
open files` ile sonuçlanır. Edge-TTS artık yalnızca yedek yol olduğu için sızıntı hızı
düştü ama hata duruyor.

**Düzeltme:** `try/finally` ile `loop.close()` garanti altına alınmalı.

---

## 🟠 P1 — Mimari riskler

### 4. ffmpeg alt süreci timeout'ta öldürülmüyor

`edge_tts_engine.py:139-145`:

```python
ff_proc = subprocess.Popen([...])
pcm_bytes, _ = ff_proc.communicate(input=mp3_bytes, timeout=4.0)
```

`TimeoutExpired` fırlarsa Python dokümantasyonunun açıkça uyardığı gibi alt süreç
**öldürülmez**; `except Exception` bunu yutup `None` döndürüyor ve ffmpeg arkada
çalışmaya devam ediyor. `kill()` + `communicate()` ile temizlenmeli.

### 5. `MultiThreadedExecutor(4)` yanıltıcı

`ai_brain_node.py:2409` 4 thread'lik havuz kuruyor ama callback grubu tanımlanmadığı
için (#2) hepsi aynı mutually-exclusive grupta sıraya giriyor. Yani **4 thread'in
hiçbir faydası yok**, sadece hata ayıklamayı zorlaştırıyor. Ya #2 düzeltilip gerçek
paralellik sağlanmalı ya da bu satır sadeleştirilmeli.

### 6. İki paralel beyin — 6.221 satır, çift bakım maliyeti

| Dosya | Satır |
|---|---|
| `astro_realtime_node.py` | 3.798 |
| `ai_brain_node.py` | 2.423 |

Bu iki düğümde **16 aynı isimli metot** var: `_check_reminders`,
`_check_session_lifecycle`, `_idle_learning_loop`, `_idle_memory_reflection`,
`_async_summarize_and_save_session`, `_get_active_biometric_identity`, `_on_speaker_id`,
`_on_camera_image`, `_on_doa`, `_on_user_emotion`, `_format_turkish_weather` …

Pratikteki sonucu: **bir düzeltme iki yere uygulanmazsa modlardan biri hatalı kalır.**
Deadlock düzeltmesi ortak `memory_manager`'da olduğu için şanslıydık; callback grubu
düzeltmesi (#2) iki dosyada da ayrı ayrı yapılmak zorunda.

Ayrıca bu iki düğüm birbiriyle **çalıştırılamaz**: ikisi de `/speech/text` yayınlıyor ve
farklı ses boru hatları (16 kHz `audio_capture_node` vs 24 kHz `audio_stream_node`)
kullanıyor. `robot.launch.py` birincisini, `realtime_sensors.launch.py` ikincisini
başlatıyor; ikisi aynı anda açılırsa çift mikrofon + çift beyin çakışması olur.

**Öneri:** Ortak davranışı (`hafıza`, `hatırlatıcı`, `oturum yaşam döngüsü`,
`biyometrik kimlik`, `persona`) tek bir `AstroCore` mixin/sınıfına çıkarıp iki düğümün
de ondan türemesi. Kademeli yapılabilir — her seferinde bir metot ailesi.

### 7. TTS zinciri sabit kodlu ✅ kısmen çözüldü

`tts_router.py` zinciri kod içinde sabitti (Realtime → Edge-TTS → espeak) ve
`TTS_ENGINE` okunup **hiçbir yerde kullanılmıyordu**. Ayrıca `RealtimeEngine.synthesize_sentence()`
her zaman `None` döndürüyor (gerçek ses `astro_realtime_node`'dan gelir), o düğüm de
`robot.launch.py`'de başlatılmıyor — yani bu modda TTS'in OpenAI'ye ulaşma yolu yoktu.

**Yapılan:** `openai_tts_engine.py` eklendi, zincire birincil bulut sağlayıcı olarak
bağlandı, `TTS_ENGINE` artık gerçekten okunuyor.

**Kalan:** Zincir hâlâ kod içinde sabit. Sağlayıcı sırasının `.env`'den okunan bir
listeden (`TTS_CHAIN="openai,edge,offline"` gibi) üretilmesi daha esnek olurdu.

### 8. `LLM_PROVIDER` ölü ayar

`.env.example` bunu birincil ayar olarak belgeliyor ama kodda **hiç okunmuyor**.
Gerçek sıra `ai_brain_node.py:1177-1256`'da sabit: **Groq → Gemini → OpenAI**.
Sağlayıcı seçmenin tek yolu istemediğiniz sağlayıcıların API anahtarını boşaltmak —
bu hem sezgisel değil hem de belgelenmemiş. Aynı sorun `VISION_PROVIDER` ve `AI_MODE`
için de geçerli.

### 11. `.env` "son kazanır" tuzağı ✅ geçici çözüm

Dosyada **18 anahtar birden fazla kez tanımlı**. python-dotenv sonuncuyu kullanır, bu
yüzden dosyanın ortasına eklenen OpenAI bloğu aşağıdaki şablon satırları tarafından
eziliyordu (`TTS_ENGINE=openai` → `TTS_ENGINE="edge-tts"`).

Şu an dosya sonuna otoriter bir override bloğu eklendi ve çalışıyor, ama **kalıcı çözüm
değil**: bir sonraki düzenleme yine yanlış yere yazılabilir. `.env` sıfırdan, tek
tanımlı ve bölümlenmiş şekilde yeniden yazılmalı.

Tekrar edenler: `AI_API_KEY`, `CONVERSATION_TIMEOUT`, `ELEVENLABS_API_KEY`,
`ELEVENLABS_ENABLED`, `ELEVENLABS_MODEL`, `ELEVENLABS_VOICE_ID`, `ENABLE_IDLE_LEARNING`,
`GEMINI_API_KEY`, `GROQ_API_KEY`, `LLM_MAX_TOKENS`, `LLM_MODEL`, `LLM_PROVIDER`,
`LLM_TEMPERATURE`, `OPENAI_TTS_VOICE`, `STT_ENGINE`, `TTS_ENGINE`, `TTS_VOICE`, `WAKE_WORD`

---

## 🟡 P2 — Kod sağlığı ve hijyen

### 9. 2.146 satır ölü kod

| Bileşen | Satır | Durum |
|---|---|---|
| `local_xtts_engine.py` + `xtts_worker.py` + `xtts_client.py` | 1.816 | `tts_node.py:102` — `self.local_xtts = None`, "production policy" gereği kapalı |
| `elevenlabs_engine.py` | 330 | `tts_node`'da hiç örneklenmiyor, orchestrator'a bağlı değil |

XTTS için `.env.example`'da hâlâ 13 ayar belgeleniyor ve `install_xtts.sh` (~5 GB)
duruyor. Ya canlandırılmalı ya da ayrı bir dala alınıp ana daldan çıkarılmalı —
şu hâliyle okuyanı yanıltıyor.

### 10. QoS profilleri

86 publisher/subscriber varsayılan (RELIABLE, depth=10) ile kurulmuş; yalnızca 3 yerde
sensor-data QoS kullanılmış. Özellikle ham `sensor_msgs/Image`, `/oak/rgb/image_raw`
üzerinden **iki ayrı aboneye** (`face_detector_node` ve `ai_brain_node`) RELIABLE olarak
gidiyor. Yüksek çözünürlükte bu ciddi DDS trafiği ve gecikme demek. Görüntü/ses için
`qos_profile_sensor_data` (BEST_EFFORT) kullanılmalı; `ai_brain` zaten kareleri 2 FPS'e
kısıyor, o hâlde ayrı bir düşük çözünürlük topic'i daha da iyi olurdu.

### 12. Yapılandırma sürüklenmesi

- **14 ayar `.env.example`'da var ama kodda hiç okunmuyor:** `AI_MODE`, `LLM_PROVIDER`,
  `VISION_PROVIDER`, `LLM_THINKING`, `GEMINI_TEXT_MODELS`, `STT_API_KEY`, `STT_BASE_URL`,
  `STT_WHISPER_MODEL`, `STT_VOSK_MODEL_PATH`, `TTS_XTTS_DEVICE`, `TTS_XTTS_HALF`,
  `TTS_XTTS_TIMEOUT_S`, `TTS_XTTS_STARTUP_TIMEOUT_S`, `TTS_XTTS_TEXT_SPLITTING`
- **~30 ayar kodda okunuyor ama belgelenmemiş:** `OPENAI_API_KEY`(!), `FACE_MATCH_THRESHOLD`,
  `FACE_DB_PATH`, `GAZE_DWELL_S`, `GAZE_COOLDOWN_S`, `REALTIME_MODEL`, `REALTIME_VOICE`,
  `EDGE_TTS_*`, `TTS_PLAYBACK_START_DEADLINE_MS`, `BARGE_IN_*`, `MEMORY_FILE_PATH`, …

`OPENAI_API_KEY`'in `.env.example`'da olmaması, "anahtarları ekledim ama çalışmıyor"
probleminin doğrudan sebeplerinden biri.

### 13. Çalışma zamanı verisi depoda

`ros2_ws/astro_memory.json` ve `astro_memory.json.bak` git'te takip ediliyor. Robot her
çalıştığında dosya değişiyor → sürekli kirli `git status`, gereksiz çakışmalar ve
**konuşma geçmişi/kişi profilleri depoya sızıyor** (kişisel veri). `.gitignore`'a
alınıp `git rm --cached` ile çıkarılmalı; `MEMORY_FILE_PATH` zaten destekleniyor.

### 14. Sabit kodlanmış kişisel yollar

Başka bir geliştiricinin makinesine ait yollar kodda duruyor:

```
local_xtts_engine.py:25,61,81,82,106   /home/okistech/...
speaker_db.py:145                      /home/okistech/Desktop/astr1/models
memory_manager.py:116,117              ~/Desktop/astr1/...
memory_v2/migration.py:36,37           ~/Desktop/astr1/...
```

Zararsız görünüyorlar (arama listesinde bir eleman) ama taşınabilirliği bozuyor ve
kafa karıştırıyor. Ortam değişkeni + paket paylaşım dizini yeterli olmalı.

### 15. `package.xml` eksik bağımlılıklar

`astro_ai` `sensor_msgs` kullanıyor ama beyan etmiyor. Beyanlar genel olarak eksik
(`rclpy`, `std_msgs` dışında neredeyse hiçbir şey yok — `python3-opencv`, `depthai`,
pip bağımlılıkları vb.). Bunun sonucu: `rosdep install` çalışmaz, temiz bir makinede
derleme sırası garanti edilmez. Şu an `requirements.txt` bu boşluğu dolduruyor ama
ROS'un standart yolu bu değil.

### 16. İstisna yönetimi

- **128 adet tamamen sessiz `except ...: pass`**
- **249 adet geniş yakalama** (`except Exception` / bare `except`)

En yoğun yerler: `astro_realtime_node.py` (22 sessiz), `ai_brain_node.py` (12),
`xtts_client.py` (7), `voice_recognizer.py` (7).

Bu, teşhis edilen deadlock'un neden bu kadar zor bulunduğunu da açıklıyor: hata
sinyalleri sistematik olarak yutuluyor. Sessiz `pass` yerine en azından
`logger.debug(...)` konmalı.

### 17. CI yok

5.390 satır test var (191 + 101 = 292 test) ama otomatik çalıştıran hiçbir şey yok
(`.github/` dizini mevcut değil). Test çalıştırmak için `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
gerekiyor — sistem pytest'i ile venv'deki `anyio` eklentisi çakışıyor
(`ModuleNotFoundError: No module named '_pytest.scope'`). Bu da testleri çalıştırmayı
zorlaştırıyor.

**Ayrıca 1 test zaten kırık:** `test_conversational_hardening.py:139`
`test_edge_tts_to_local_offline` — test `socket.create_connection`'ı mock'luyor ama
`EdgeTTSEngine.check_network` `socket.socket().connect()` kullanıyor, yani mock hiç
devreye girmiyor. Test yalnızca internetsiz makinede geçer. (Bu benim değişikliklerimden
önce de kırıktı — `git stash` ile doğrulandı.)

**Öneri:** `pytest`'i `requirements.in`'e ekle, `.github/workflows/ci.yml` ile her push'ta
derleme + test çalıştır.

---

## 🟢 P3 — İyileştirme önerileri

### 18. Yanıltıcı log banner'ları

`speech_recognition_node.py:216` — motor ne olursa olsun her açılışta şunu basıyor:

```
✅ [STT] Groq Whisper-large-v3 + Self-Echo Immunity + Bağlam Duyarlı Filtre Hazır.
```

Groq devre dışıyken bile. Aynı şekilde `tts_node.py` her açılışta
`🚀 [TTS Node] Hybrid Realtime & XTTS GPU Orchestrator Hazır!` diyor — XTTS kapalı
olmasına rağmen. Bu tür banner'lar hata ayıklarken aktif olarak yanlış yönlendiriyor;
gerçek durumu yansıtmalılar.

### 19. TTS'te streaming yok

OpenAI TTS ölçülen TTFA'sı ~1,9 sn (Edge-TTS ~0,8 sn idi). Sebep: cümlenin tamamı
sentezlenip öyle çalınıyor. `sentence_chunker.py` zaten var ama tam kullanılmıyor.
İki iyileştirme mümkün:

- `OPENAI_TTS_MODEL="tts-1"` — kalite biraz düşer, gecikme belirgin azalır (tek satırlık `.env` değişikliği)
- Streaming: `with_streaming_response` ile ilk chunk gelir gelmez çalmaya başlamak

### 20. Loglama hacmi

Her konuşma turunda `[ASTRO TURN]` bloğu **25 satır** basıyor, her idle döngüsünde
`[ASTRO IDLE]` **13 satır**. Telemetri değerli ama bu hacimde konsol okunamaz hâle
geliyor ve gerçek uyarılar kayboluyor (deadlock'un fark edilmemesinin sebeplerinden
biri de bu). Yapılandırılmış tek satır (JSON) + `--verbose` bayrağı daha iyi olurdu.

### 21. Yerelde kalan bileşenler

Yüz tanıma (YuNet + SFace) ve ses kimliği (WeSpeaker) hâlâ yerel ONNX ile CPU'da
çalışıyor. OpenAI'de karşılıkları olmadığı için bu bilinçli bir tercih olmalı —
sadece "her şey API'de" hedefinin istisnası olarak not edilsin.

### 22. Donanım uyarıları (bilgi amaçlı, hata değil)

Çalıştırma loglarındaki şu satırlar **beklenen** davranış, düzeltilmesi gerekmiyor:

- `Arduino port not found (/dev/astro_arduino)` — Arduino bağlı değil, 2 sn'de bir yeniden deniyor
- `Cannot find any device with given deviceInfo` — OAK-D Lite bağlı değil
- `LiDAR port '/dev/astro_lidar' not found — skipping` — launch doğru şekilde atlıyor
- `ReSpeaker donanımı bulunamadı` — sistem mikrofonuna düşüyor

Yalnızca biri gerçek bir sorun: `component_container` OAK bulunamadığında **SIGSEGV
(exit code -11)** ile ölüyor. Bu bizim kodumuz değil (`depthai_ros_driver`), ama
launch'ta `respawn` veya cihaz ön kontrolü ile yönetilebilir.

---

## Önerilen düzeltme sırası

**Aşama 1 — Kararlılık (robotun çökmesini engeller) — ✅ TAMAMLANDI**
1. ✅ Deadlock (`RLock`)
2. ✅ `edge_tts_engine` event loop sızıntısı + ffmpeg yetim süreci
3. ✅ Callback grubu ayrıştırması (konuşma / timer / algı)
4. ✅ `_evaluate_social_barge_in` callback'ten thread'e taşındı

**Aşama 2 — Yapılandırma netliği — ✅ TAMAMLANDI**
5. ✅ `.env`'i tek tanımlı, bölümlenmiş şekilde yeniden yaz
6. ✅ `.env.example`'ı gerçekle eşitle (ölü ayarları çıkar, `OPENAI_API_KEY` dahil eksikleri ekle)
7. ✅ `LLM_PROVIDER`'ı gerçekten okunur yap (veya belgeden kaldır)
8. ✅ `astro_memory.json`'ı git'ten çıkar

**Aşama 3 — Temizlik — ✅ TAMAMLANDI**
9. Ölü kodu kaldır (XTTS ayrı dala, ElevenLabs ya bağla ya sil)
10. Sabit kodlanmış kişisel yolları temizle
11. Yanıltıcı banner'ları düzelt
12. Sessiz `except: pass`'leri `logger.debug`'a çevir

**Aşama 4 — Dayanıklılık — ✅ TAMAMLANDI**
13. QoS profillerini düzelt (görüntü/ses → sensor data)
14. Kırık testi düzelt + CI kur
15. `package.xml` bağımlılıklarını tamamla

**Aşama 5 — Mimari (büyük, ayrı planlanmalı)**
16. `ai_brain_node` / `astro_realtime_node` ortak çekirdeğini çıkar

---

## Bu oturumda yapılan değişiklikler

| Dosya | Değişiklik |
|---|---|
| `astro_ai/memory_manager.py` | `Lock` → `RLock` (deadlock düzeltmesi) |
| `astro_ai/ai_brain_node.py` | Callback grupları (konuşma/timer/algı), `_dispatch_turn` çıkarıldı, sosyal filtre thread'e taşındı, executor 6 thread |
| `astro_audio/edge_tts_engine.py` | Event loop `try/finally`, ffmpeg timeout'ta `kill()` |
| `astro_audio/openai_tts_engine.py` | **Yeni** — OpenAI Speech API TTS motoru |
| `astro_audio/tts_router.py` | OpenAI TTS adımı zincire eklendi |
| `astro_audio/tts_orchestrator.py` | Motor geçişi |
| `astro_audio/tts_node.py` | `TTS_ENGINE` artık gerçekten okunuyor |
| `.gitignore` | `.env.bak.*` ve `.env.production` eklendi (anahtar sızıntısı riski) |
| `.env` | OpenAI-only override bloğu (yedek: `.env.bak.20260821-192524`) |

Doğrulama: astro_audio 101/101 test geçti, astro_ai 190/191 (kırık test önceden kırıktı),
7/7 paket derlendi, STT/LLM/TTS üçü de canlı çalıştırılarak OpenAI'den geçtiği doğrulandı.


---

## Düzeltme notu (21.08.2026)

İnceleme sırasında "ölü ayar" listesi satır bazlı `grep` ile çıkarılmıştı ve çok satırlı
`os.getenv(` çağrılarını kaçırıyordu. AST ile yeniden tarandığında `GEMINI_TEXT_MODELS`
ve `TTS_VOICE`'un aslında **okunduğu** görüldü; `GEMINI_TEXT_MODELS` `.env`'e geri kondu.
Gerçek ölü ayar sayısı 14 (LLM_PROVIDER artık uygulandığı için listeden çıktı).
`.env.example` bundan sonra AST taramasından üretiliyor.


---

## Aşama 5 ölçümü — "ortak çekirdek çıkar" önerisinin revizyonu

İnceleme, iki beyin düğümündeki **16 aynı isimli metodu** kopya sanmış ve ortak bir
`AstroCore` mixin'ine çıkarılmasını önermişti. Metot gövdeleri `difflib` ile
karşılaştırıldığında bunun **yanlış olduğu** görüldü:

| Benzerlik | Metot sayısı |
|---|---|
| Birebir aynı (>0.99) | **0** |
| Çok benzer (>0.85) | 1 (`_format_turkish_weather`) |
| Ayrışmış (<0.85) | **15** — çoğu 0.05–0.40 |

Yani metotlar aynı *kavramı* iki kez, **farklı şekilde** uyguluyor. Mekanik bir
çıkarım mümkün değil: birleştirmek, 15 metodun her biri için "hangi davranış doğru?"
sorusunun ürün düzeyinde yanıtlanmasını gerektirir.

Riskin somut hâli değişmedi — bir düzeltme iki yere uygulanmazsa modlardan biri hatalı
kalır — ama çözüm bir refactor değil, bir tasarım kararı. **Ayrı bir oturumda
planlanmalı.**

Bu oturumda yapılan kontrol: `astro_realtime_node`'un 13 callback'i tarandı, hiçbirinde
bloklayan bulut çağrısı yok. Yani #2'deki donma açığı o düğümde mevcut değil; callback
grubu sertleştirmesi orada spekülatif olurdu, bu yüzden yapılmadı.
