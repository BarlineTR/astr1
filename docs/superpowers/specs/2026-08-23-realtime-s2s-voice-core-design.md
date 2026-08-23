# ASTRO V1 — Realtime S2S Ses Çekirdeği (Spec #1)

**Tarih:** 2026-08-23
**Branch:** `feat/realtime-s2s-voice-core` (baseline: `bab0512`)
**Kapsam:** P0-A (ses sahipliği) + P0-B (saf S2S) + P0-C (server VAD)
**Kapsam dışı:** P0-D (async perception — büyük ölçüde `bab0512`'de yapıldı), P0-E (tool bus / gerçek hareket), P0-F (fallback motoru), P1 (idle learning, persona)

---

## 1. Problem

ASTRO'nun konuşma çekirdeği, OpenAI Realtime API'yi tasarlandığı iş için
kullanmıyor. Realtime bir speech-to-speech motoru; mevcut mimaride ise metin
seslendiren pahalı bir TTS'e indirgenmiş durumda.

Mevcut (hatalı) akış:

```
Mic → STT → Groq/Gemini LLM → metin → Realtime → ses
```

Hedeflenen akış:

```
Mic PCM → Realtime WebSocket → OpenAI VAD + model → audio delta → Hoparlör
```

Bunun somut bedeli üç başlıkta toplanıyor:

1. **Gecikme.** Her tur, ses→metin→ses arasında iki ekstra ağ gidiş-dönüşü ve
   bir LLM çıkarımı taşıyor.
2. **Kayıp bilgi.** Ses tonu, duygu, prozodi STT katmanında düşüyor; Realtime'a
   yalnızca düz metin ulaşıyor.
3. **Kararsızlık.** Turn yaşam döngüsünü hem Python hem sunucu yönetmeye
   çalışıyor; barge-in için dört ayrı otorite var.

### 1.1 Kanıt — mevcut koddaki tam konumlar

| Bulgu | Konum |
|---|---|
| Cascaded metin enjeksiyonu | `astro_realtime_node.py:687` (`/tts/realtime_request` aboneliği), `:766` `_on_realtime_turn_request`, `:814` `_dispatch_turn`, `:838` `"Lütfen şu cevabı tam olarak seslendir: {text}"` |
| Çift playback sahibi | `tts_node.py:203` ve `audio_stream_node.py:162` — ikisi de `/audio/realtime_output_pcm` abonesi, ikisi de donanıma yazıyor |
| Çift mikrofon sahibi | `audio_capture_node.py:266` ve `audio_stream_node.py:246` — ikisi de `sd.*InputStream` açıyor |
| Çatışmanın kodda kabulü | `audio_stream_node.py:278` — "mikrofon meşgulse `/audio/speech_audio`'ya abone ol" yaması |
| `interrupt_response` yok | `astro_realtime_node.py:1098-1105` — yalnızca `create_response` var |
| `move_robot` güvenlik kapısı yok | `astro_realtime_node.py:1650` — heartbeat/handshake/motor_enabled kontrolü olmadan `/cmd_vel` |
| `move_robot`'un tüketicisi yok | `serial_bridge.py:141` `/wheel_cmds` dinliyor, `/cmd_vel` değil |

### 1.2 `bab0512` ile çözülmüş olanlar (bu spec'in kapsamından düşenler)

`bab0512` ("unify S2S voice architecture…") commit'i işin bir kısmını
hâlihazırda yaptı. Bu spec onların üzerine kurulur, tekrar etmez:

- `voice_engine` launch argümanı geldi; realtime modunda `audio_capture_node`,
  `speech_recognition_node`, `tts_node`, `ai_brain_node` başlatılmıyor.
- `create_response: True` (`:1104`), `silence_duration_ms: 500`, `threshold: 0.70`.
- `speech_stopped` üzerinde manuel `response.create` kaldırıldı.
- `_run_voice_identification` ve tool çalıştırma `asyncio.to_thread`'e taşındı —
  WebSocket event loop'u artık bunları beklemiyor.
- `audio_stream_node` playback worker'ı geri getirildi (kuyruk kimse tarafından
  boşaltılmıyordu; `/audio/playback_active` sonsuza kadar `True` kalıyordu).

### 1.3 `bab0512`'nin getirdiği regresyonlar ve yeni riskler

- 🔴 **Barge-in fiilen çalışmıyor.** `interrupt_response` eklenmedi, ve
  `test_realtime_barge_in_preserves_semantics` artık başarısız: barge-in'de
  `response.cancel` gönderilmiyor. Yani ne sunucu ne istemci kesme yapıyor.
- 🔴 **`move_robot` güvenlik kapısı olmadan canlıya alındı.** Motor sağlığı
  kanıtlanmadan `/cmd_vel` yayınlıyor.
- 🔴 **`move_robot` gerçek robotta hiçbir yere basmıyor.** `/cmd_vel`'in gerçek
  donanımda tüketicisi yok; tool sessizce `status: success` dönüyor ama tekerlek
  dönmüyor. (`docs/simulasyon-ve-gercek-robot.md:203` bunu "eksik `base_bridge`
  düğümü" olarak zaten kaydetmiş.)
- ⚠️ **Tek sahiplik yapısal değil, launch koşuluna bağlı.** `tts_node.py:203`
  aboneliği duruyor; `voice_engine:=cascaded` denince çift playback sahibi geri
  gelir.
- ⚠️ **Cascaded hat silinmedi, yalnızca açlığa terk edildi.** Realtime modunda
  yayıncısı yok, ama kod duruyor ve turn queue (`:1407`) hâlâ ona bağlı.

---

## 2. Tasarım ilkeleri

Bu spec'i yönlendiren, tartışmaya kapalı dört ilke:

1. **Realtime, canlı konuşmanın yürütme motorudur — sistemin sahibi değildir.**
   Görme, hafıza ve hareket ayrı alt sistemlerdir; Realtime onlara tool bus
   üzerinden erişir.
2. **Sesin tek bir sahibi vardır: `audio_stream_node`.** Giriş de çıkış da.
   Bu, launch koşuluyla değil kodla garanti altına alınır.
3. **Turn yaşam döngüsünün tek otoritesi sunucudur.** Server VAD hem yanıt
   üretimini (`create_response`) hem kesmeyi (`interrupt_response`) yönetir.
   Python yalnızca donanımsal yankı korumasından ve playback'ten sorumludur.
4. **İki state machine asla karışmaz.** Bağlantı durumu (`EngineState`) ile
   konuşma turu durumu (`TurnMachine`) ayrı modüllerdir ve birbirlerini import
   etmezler.

---

## 3. Mimari

### 3.1 Hedef ses veri yolu

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
    (24 kHz)          (24 kHz)
         │             │
         ▼             │
   ┌──────────────────────────┐
   │   astro_realtime_node    │
   │  ┌────────────────────┐  │
   │  │  EngineState       │  │  REALTIME_PRIMARY | RECONNECTING | FALLBACK_ACTIVE
   │  ├────────────────────┤  │
   │  │  TurnMachine       │  │  IDLE | USER_SPEAKING | RESPONSE_PENDING
   │  │                    │  │  | RESPONSE_STREAMING | TOOL_EXECUTING
   │  │                    │  │  | RESPONSE_CANCELLING
   │  └────────────────────┘  │
   └──────────────────────────┘
         │             ▲
         ▼             │
    OpenAI Realtime WebSocket
    (server VAD sahibi)
```

`audio_capture_node`, `speech_recognition_node`, `tts_node` realtime modunda
**hiç başlatılmaz** ve `tts_node` realtime PCM'e **kodda da abone değildir**.

### 3.2 Yeni modül yapısı

```
ros2_ws/src/astro_ai/astro_ai/realtime/
├── __init__.py
├── session_config.py   # build_session_update() → saf dict üretici
├── turn_machine.py     # TurnMachine → response yaşam döngüsü FSM
└── engine_state.py     # EngineState → bağlantı katmanı FSM
```

Üçü de **ROS'suz, ağsız, donanımsız saf Python**. `astro_realtime_node` bunları
çağıran ince adaptöre dönüşür.

Bu ayrımın gerekçesi doğrudan doğrulanabilirlik: turn state machine'in
doğruluğu, WebSocket veya ses donanımı olmadan, geliştirme laptop'unda saniyeler
içinde kanıtlanabilir hale gelir. Kabul kriterlerindeki üç hata sayacı
(§7.1) böylece Jetson'a gitmeden otomatik test altına girer.

---

## 4. Bileşen tasarımı

### 4.1 `turn_machine.py` — `TurnMachine`

**Ne yapar:** Bir konuşma turunun yaşam döngüsünü izler ve her olay için ne
yapılması gerektiğine dair *karar* döndürür.
**Nasıl kullanılır:** `machine.on_event(event_type, response_id=None)` → `list[Action]`
**Neye bağlıdır:** Hiçbir şeye. Standart kütüphane dışında import yok.

#### Durumlar

| Durum | Anlamı |
|---|---|
| `IDLE` | Aktif tur yok, kullanıcı konuşmuyor |
| `USER_SPEAKING` | `speech_started` alındı, `speech_stopped` beklenıyor |
| `RESPONSE_PENDING` | `speech_stopped` alındı, sunucunun `response.created` göndermesi bekleniyor |
| `RESPONSE_STREAMING` | `response.created` alındı, audio delta akıyor |
| `TOOL_EXECUTING` | Model tool çağırdı, sonuç bekleniyor |
| `RESPONSE_CANCELLING` | Kesme başlatıldı, `response.done` bekleniyor |

> **`RESPONSE_PENDING` neden var?** Orijinal tasarım listesinde beş durum vardı.
> `create_response: true` ile birlikte `speech_stopped` ile `response.created`
> arasında sunucunun yanıtı kurduğu gerçek bir zaman penceresi oluşuyor. Barge-in
> tam bu pencereye denk gelirse beş durumlu makine tanımsız kalır — kullanıcı
> henüz var olmayan bir response'u kesmeye çalışır. Altıncı durum bu boşluğu
> kapatır ve `may_send_cancel()` guard'ının doğru cevabı vermesini sağlar.

#### Geçişler

```
IDLE                 --speech_started-->        USER_SPEAKING
USER_SPEAKING        --speech_stopped-->        RESPONSE_PENDING
RESPONSE_PENDING     --response.created-->      RESPONSE_STREAMING
RESPONSE_STREAMING   --function_call.done-->    TOOL_EXECUTING
TOOL_EXECUTING       --tool_result_sent-->      RESPONSE_PENDING
RESPONSE_STREAMING   --speech_started-->        RESPONSE_CANCELLING
RESPONSE_PENDING     --speech_started-->        RESPONSE_CANCELLING
TOOL_EXECUTING       --speech_started-->        RESPONSE_CANCELLING
RESPONSE_CANCELLING  --response.created-->      RESPONSE_CANCELLING  (id bağlanır)
RESPONSE_STREAMING   --response.done-->         IDLE
RESPONSE_CANCELLING  --response.done-->         IDLE
```

Tabloda olmayan her (durum, olay) çifti geçersizdir: `TurnMachine` durumu
değiştirmez ve `IGNORE` döndürür. Sessizce yutmaz — düğüm bunu telemetriye yazar.

#### Kararlar (`Action`)

`PUBLISH_AUDIO` · `DROP_AUDIO` · `STOP_PLAYBACK` · `SEND_CANCEL` · `IGNORE`

FSM yan etki üretmez. Ses yayınlamaz, WebSocket'e yazmaz, log basmaz. Yalnızca
karar döndürür; yan etkileri düğüm uygular. Test edilebilirliğin kaynağı budur.

#### Guard'lar

| Guard | Kural | Karşıladığı kabul kriteri |
|---|---|---|
| `may_send_cancel()` | Yalnızca `active_response_id is not None` **ve** durum `RESPONSE_STREAMING` / `TOOL_EXECUTING` / `RESPONSE_CANCELLING` iken `True` | `response_cancel_not_active = 0` |
| FSM hiçbir koşulda `response.create` üretmez | Yanıt üretimi tamamen sunucunun (§6'daki tool istisnası hariç) | `conversation_already_has_active_response = 0` |
| `should_publish_audio(response_id)` | `response_id != active_response_id` ise `DROP_AUDIO` | Playback generation isolation |

`generation_id` her `response.created`'da artar ve o response'a bağlanır. Eski
generation'ın geç gelen audio delta'sı sessizce düşer.

#### `may_send_cancel()` ne zaman kullanılır?

Normal işleyişte **hiç kullanılmaz**: `interrupt_response: true` ile kesmeyi
sunucu yapar, istemci `response.cancel` göndermez (§6.6a). Guard iki yer için
vardır:

1. `REALTIME_INTERRUPT_RESPONSE=false` ile istemci taraflı kesmeye düşüldüğünde
   (§8'deki yedek yol).
2. Regresyon koruması olarak: kodun ileride buraya yeniden `response.cancel`
   eklemesi hâlinde guard'ın yanlış durumda göndermeyi reddetmesi.

**`RESPONSE_PENDING` neden listede yok:** O durumda sunucu henüz
`response.created` göndermemiştir, dolayısıyla `active_response_id is None`'dır.
İptal edilecek bir response yoktur; `response.cancel` göndermek tam da guard'ın
engellemesi gereken `response_cancel_not_active` hatasını üretir.

#### `RESPONSE_PENDING` sırasında barge-in

Kullanıcı, sunucu yanıtı kurarken araya girerse:

```
RESPONSE_PENDING --speech_started--> RESPONSE_CANCELLING
    Action: STOP_PLAYBACK        (çalınacak ses yoksa etkisiz)
    Action: (SEND_CANCEL YOK — active_response_id henüz None)

RESPONSE_CANCELLING --response.created--> RESPONSE_CANCELLING
    active_response_id bağlanır. interrupt_response=true ise sunucu bu
    response'u zaten kesmiştir; false ise artık may_send_cancel() True olur
    ve istemci yedek yolu SEND_CANCEL üretebilir.

RESPONSE_CANCELLING --response.done--> IDLE
```

Bu, altıncı durumun varlık sebebidir: beş durumlu makinede bu pencere
tanımsızdır.

### 4.2 `session_config.py` — `build_session_update()`

**Ne yapar:** `session.update` payload'ını üretir.
**Nasıl kullanılır:** `build_session_update(instructions=..., voice=..., tools=..., env=os.environ)` → `dict`
**Neye bağlıdır:** Yalnızca `os.environ` (parametre olarak enjekte edilir).

Doğrulanmış nesting yolu `session.audio.input.turn_detection`. Mevcut kod bu
yolu zaten doğru kullanıyor; değişen yalnızca alanların değerleri ve
yapılandırılabilirliği.

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "instructions": "<persona>",
    "audio": {
      "input": {
        "transcription": { "model": "gpt-live-transcribe", "language": "tr" },
        "turn_detection": {
          "type": "server_vad",
          "threshold": 0.70,
          "prefix_padding_ms": 300,
          "silence_duration_ms": 500,
          "create_response": true,
          "interrupt_response": true
        }
      },
      "output": { "voice": "<voice>" }
    },
    "tools": [ ... ]
  }
}
```

`type: "semantic_vad"` seçildiğinde `threshold` / `prefix_padding_ms` /
`silence_duration_ms` yerine `eagerness` alanı yazılır; `create_response` ve
`interrupt_response` her iki tipte de geçerlidir.

#### Yeni `.env` anahtarları

| Anahtar | Varsayılan | Açıklama |
|---|---|---|
| `REALTIME_VAD_TYPE` | `server_vad` | `server_vad` \| `semantic_vad` |
| `REALTIME_VAD_THRESHOLD` | `0.70` | 0–1, yalnızca `server_vad` |
| `REALTIME_VAD_SILENCE_MS` | `500` | yalnızca `server_vad` |
| `REALTIME_VAD_PREFIX_MS` | `300` | yalnızca `server_vad` |
| `REALTIME_VAD_EAGERNESS` | `auto` | `auto`\|`low`\|`medium`\|`high`, yalnızca `semantic_vad` |
| `REALTIME_INTERRUPT_RESPONSE` | `true` | Sunucu tarafı barge-in |

Kod hiçbir değeri "en iyi" varsaymaz. `silence_duration_ms` için başlangıç
noktası 500 ms'dir; 400/500/600 ve `semantic_vad(medium)` dört adaylı benchmark
Kapı 2'de gerçek Jetson üzerinde koşulur ve kazanan `.env`'e yazılır.

> **Not:** `gpt-realtime-2.1-mini` için dolaşan "%25 daha hızlı" iddiasının
> doğrulanabilir bir kaynağı yoktur. Model seçimi mimariye sabitlenmez;
> `REALTIME_MODEL` üzerinden yapılandırılır ve benchmark'la karara bağlanır.

### 4.3 `engine_state.py` — `EngineState`

**Ne yapar:** Bağlantı katmanının durumunu izler: `REALTIME_PRIMARY`,
`RECONNECTING`, `FALLBACK_ACTIVE`.
**Neye bağlıdır:** Hiçbir şeye.

Bu spec'te `EngineState` yalnızca **tanımlanır ve telemetriye bağlanır**.
Fallback motoruna geçiş mantığının kendisi P0-F'in konusudur. Buradaki amaç,
`TurnMachine` ile karışmasını yapısal olarak imkânsız kılmak.

---

## 5. Düğüm değişiklikleri

### 5.1 `astro_realtime_node.py`

**Silinecekler** (cascaded metin enjeksiyon hattı):

- `:687` `/tts/realtime_request` aboneliği
- `:766` `_on_realtime_turn_request()`
- `:814` `_dispatch_turn()`
- `_check_audio_delta_timeout()` ve ona bağlı watchdog timer
- `_turn_queue`, `_last_sent_generation_id` ve `:1407`'deki kuyruk boşaltma

`ai_brain_node`'un kendisi **silinmez**. Yalnızca Realtime'a metin enjekte etme
yolu kapanır. Node, cascaded modda ve ileride fallback bilişsel arka uç olarak
korunur.

**Devredilecekler:**

- `_send_session_update()` → `build_session_update()` çağırır
- `_handle_realtime_event()` → durum kararlarını `TurnMachine`'e delege eder

**Rütbesi düşürülecek** — `_on_input_pcm()` içindeki barge-in bloğu:

Bu blok **silinmez**. Artık state geçişi yapmaz, `response.cancel` göndermez,
generation id artırmaz. Geriye üç sorumluluk kalır:

1. Donanımsal yankı koruma penceresi (`barge_in_protection_ms`)
2. Playback durdurma (`/tts/interrupt` yayını)
3. Telemetri (`barge_in_after_ms`)

Kesme otoritesi tamamen sunucudaki `interrupt_response`'a geçer. "Donanımsal
yankı koruması ayrı kalmalı" şartı böyle karşılanır: akustik koruma yerelde,
konuşma mantığı sunucuda.

**Yerel VAD geçidi korunur.** `_on_input_pcm`'deki uyku/wake mantığı olduğu gibi
kalır. Ucuz yerel enerji eşiği yalnızca "PCM'i OpenAI'a akıt / akıtma" kararını
verir — turn başlatmaz, response tetiklemez. Sessizken sürekli ses faturası
oluşmaz; geçit açıkken akış kesintisizdir ve tüm turn kontrolü sunucudadır.

**`move_robot` güvenlik kapısı:**

Düğüm `/arduino/diagnostics`'e (`DiagnosticArray`, `serial_bridge.py:137`) abone
olur ve `arduino_alive` dahil `KeyValue`'ları okur. `move_robot` şu dördü
kanıtlanmadan çalışmaz:

```
serial_connected = true
handshake        = true
heartbeat_healthy = true
motor_enabled    = true
```

Kanıtlanmazsa `{"status": "rejected", "reason": "motor_health_unproven"}`.

Ayrıca `/cmd_vel`'in gerçek robotta tüketicisi olmadığı için, `base_bridge`
mevcut değilken tool `{"status": "rejected", "reason": "no_motion_backend"}`
döner. Model bu reddi kullanıcıya sözle iletir.

> **Neden reddetmek doğru davranış:** Tool'un sessizce `success` dönüp tekerleğin
> dönmemesi, hem kullanıcıya yalan söyler hem de modelin dünya modelini bozar.
> Açık ret, hem dürüst hem de hata ayıklanabilir. Gerçek hareket hattı
> (`base_bridge` + Nav2 köprüsü) Spec #2'nin konusudur.

### 5.2 `tts_node.py`

`:203` `/audio/realtime_output_pcm` aboneliği ve `:293` `_on_realtime_output_pcm()`
**tamamen kaldırılır**. Tek playback sahipliği böylece launch bayrağına değil koda
bağlanır: `voice_engine:=cascaded` bile çift sahip yaratamaz.

`tts_node`'un `/tts/say` üzerinden Edge-TTS/XTTS ile konuşma yeteneği aynen kalır —
cascaded mod ve P0-F fallback'i için gereklidir.

### 5.3 `audio_stream_node.py`

Yapısal değişiklik yok. Eklenen: `[AUDIO OWNERSHIP]` telemetri satırı
(`audio_input_owner`, `audio_output_owner`) — Kapı 2 kabul kriterinin kanıtı.

### 5.4 `bringup.launch.py`

`voice_engine` mantığı `bab0512`'de kurulmuş durumda. Eklenen: `realtime_sensors`
include'ının da `voice_engine == "realtime"` koşuluna bağlanması (şu an yalnızca
`use_realtime`'a bakıyor; `voice_engine:=cascaded use_realtime:=true` denirse
her iki hat da açılır).

---

## 6. Veri akışı — tam bir tur

```
1. Kullanıcı konuşur
   ReSpeaker → audio_stream_node → /audio/realtime_input_pcm (24 kHz b64)

2. astro_realtime_node._on_input_pcm()
   Yerel geçit açık mı? → evet → input_audio_buffer.append

3. Sunucu VAD konuşmayı algılar
   → input_audio_buffer.speech_started
   → TurnMachine: IDLE → USER_SPEAKING

4. Sunucu VAD sessizliği algılar
   → input_audio_buffer.speech_stopped
   → TurnMachine: USER_SPEAKING → RESPONSE_PENDING
   → asyncio.to_thread(_run_voice_identification)   [event loop bloklanmaz]
   → Python response.create GÖNDERMEZ. Sunucu create_response ile kendi üretir.

5. → response.created
   → TurnMachine: RESPONSE_PENDING → RESPONSE_STREAMING, generation_id++

6. → response.output_audio.delta (n kez)
   → TurnMachine.should_publish_audio(response_id)
      → PUBLISH_AUDIO → /audio/realtime_output_pcm → audio_stream_node → DAC
      → DROP_AUDIO    → eski generation, sessizce düşer

7. → response.done
   → TurnMachine: RESPONSE_STREAMING → IDLE
```

**Barge-in varyantı** (6. adımda kullanıcı araya girerse):

```
6a. Sunucu VAD yeni konuşma algılar
    → interrupt_response=true sayesinde SUNUCU aktif response'u keser
    → input_audio_buffer.speech_started
    → TurnMachine: RESPONSE_STREAMING → RESPONSE_CANCELLING
    → Action: STOP_PLAYBACK → /tts/interrupt → audio_stream_node kuyruğu boşaltır
    → Python response.cancel göndermez (sunucu zaten kesti)
6b. → response.done (status: cancelled)
    → TurnMachine: RESPONSE_CANCELLING → IDLE
```

**Tool varyantı** (6. adımda model tool çağırırsa):

```
6c. → response.function_call_arguments.done
    → TurnMachine: RESPONSE_STREAMING → TOOL_EXECUTING
    → await asyncio.to_thread(_execute_realtime_tool)   [event loop bloklanmaz]
    → conversation.item.create (function_call_output) + response.create
    → TurnMachine: TOOL_EXECUTING → RESPONSE_PENDING
```

> Tool sonucu döndükten sonra `response.create` göndermek, `create_response`
> kuralının **istisnası değildir**: sunucu VAD yalnızca kullanıcı konuşmasının
> bitişinde yanıt üretir; tool sonucu sonrası devam yanıtını istemci istemek
> zorundadır. `TurnMachine` bu tek meşru `response.create` yolunu
> `TOOL_EXECUTING` durumuna bağlayarak diğerlerinden ayırır.

---

## 7. Doğrulama

### 7.1 Kapı 1 — geliştirme laptop'unda otomatik

| Test | Kanıtladığı |
|---|---|
| `test_turn_machine.py` — geçiş tablosu | Tüm geçişler ve reddedilen geçişler |
| `test_turn_machine.py` — `may_send_cancel` | `response_cancel_not_active = 0` |
| `test_turn_machine.py` — `should_publish_audio` | Generation isolation; eski delta düşer |
| `test_turn_machine.py` — `response.create` üretilmez | `conversation_already_has_active_response = 0` |
| `test_turn_machine.py` — barge-in `RESPONSE_PENDING`'de | Altıncı durumun gerekçesi |
| `test_session_config.py` | `create_response` ve `interrupt_response` `true`; env override; `semantic_vad` şeması |
| `test_launch_voice_engine.py` | `voice_engine:=realtime` → yasaklı 4 node başlamıyor |
| `test_audio_ownership.py` (statik) | `/audio/realtime_output_pcm`'e paket genelinde tek abone |
| `test_audio_ownership.py` (statik) | `/tts/realtime_request` yayıncısı/abonesi kalmadı |
| `test_move_robot_safety.py` | Motor sağlığı kanıtlanmadan ret; `no_motion_backend` reddi |
| `test_audio_device_busy_is_reported_as_failure` | **Onarılacak** — şu an `NameError: mock_sd` |
| `test_realtime_barge_in_preserves_semantics` | **Yeniden yazılacak** — yeni kontrat: sunucu keser, istemci playback durdurur |
| Gerçek donanım tek-sahip testi (opt-in) | Laptop ALC294 ile `Device busy = 0` |

**Kapı 1 kriteri:** `pytest` → **2 fail**, ikisi de §7.3'teki kapsam dışı bilinen
sorunlar. Başka fail yok.

### 7.2 Kapı 2 — Jetson + ReSpeaker + Arduino'da manuel

`scripts/acceptance_p0.sh` yazılır. Launch log'unu okuyup şu tabloyu PASS/FAIL
olarak basar:

```
AUDIO OWNERSHIP
  audio_input_owner=audio_stream_node
  audio_output_owner=audio_stream_node

REALTIME
  session=CONNECTED
  session=READY

TURN
  speech_started → speech_stopped → response_created
  → audio_start → audio_done → response_done

PLAYBACK
  first_audio_ms < hedef
  playback_continuous=true

BARGE-IN
  speech_started → response_cancelled → playback_stopped

MOTION
  serial_connected=true  handshake=true
  heartbeat_healthy=true motor_enabled=true

VISION
  tool_call → camera → result → response

MEMORY
  tool_call → persistent store

NO ERRORS
  Device busy = 0
  write to closed file = 0
  conversation_already_has_active_response = 0
  response_cancel_not_active = 0
```

Ek olarak VAD benchmark'ı: `server_vad@400`, `server_vad@500`, `server_vad@600`,
`semantic_vad(medium)` — her biri için `first_audio_ms` p50/p95 ve
`barge_in_latency_ms`. Kazanan `.env`'e yazılır.

**MOTION bloğu bu spec'te beklenen sonuç:** `move_robot` reddediyor olmalı
(`no_motion_backend`), çünkü `base_bridge` henüz yok. "Tekerlek dönüyor" kriteri
Spec #2'ye aittir.

### 7.3 Bilinen baseline sorunları (kapsam dışı)

`bab0512` baseline'ında workspace source edilmiş halde 4 test başarısız. İkisi bu
spec kapsamında onarılıyor (§7.1). Kalan ikisi kapsam dışıdır ve ayrı iş olarak
ele alınacaktır:

| Test | Sebep |
|---|---|
| `test_21_migration_from_legacy_json` | Legacy JSON migration 0 fact üretiyor, 1 bekleniyor (`memory_v2`) |
| `test_xtts_client_batch_size_default_is_one` | Tek başına geçiyor → test kirliliği, sıra bağımlı (`xtts_client`) |

> **Test çalıştırma notu:** Workspace source edilmeden `pytest` 36 fail verir;
> 32'si `ModuleNotFoundError: astro_base` / `LookupError: astro_bringup` yani
> ortam kaynaklıdır. Doğru komut:
> `source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && pytest`

---

## 8. Riskler

| Risk | Etki | Karşılık |
|---|---|---|
| `interrupt_response` beklendiği gibi kesmezse | Barge-in çalışmaz | `TurnMachine.may_send_cancel()` zaten var; istemci tarafı `response.cancel` yedek yol olarak `REALTIME_INTERRUPT_RESPONSE=false` ile açılabilir |
| Sürekli PCM akışı maliyeti | Fatura | Yerel VAD geçidi korunuyor; sessizken akış durur |
| `semantic_vad` Türkçe'de kötü davranırsa | Kesik cümleler | Varsayılan `server_vad`; benchmark'la karar |
| Cascaded hattın silinmesi `ai_brain_node`'u bozarsa | Fallback kaybı | `ai_brain_node` dosyası korunuyor; yalnızca yayın hedefi kaldırılıyor. Cascaded modda `/tts/say` üzerinden çalışmaya devam eder |
| `astro_realtime_node` hâlâ 4258 satır | Bakım yükü | Bu spec ~120 satır düşürür. Asıl bölme (`_process_fallback_turn` çıkarımı) P0-F'in konusu |

---

## 9. Spec #2 ve sonrası (bu spec'in dışı)

- **Spec #2 (P0-E):** `base_bridge` düğümü (`/cmd_vel` → `/wheel_cmds` ters
  kinematik + `/joint_states` → `/odom` ileri kinematik + `odom → base_footprint`
  tf). Sonrasında `move_robot` gerçekten hareket ettirir. `tools_arbitration/`
  (şu an yalnızca testlerin kullandığı ölü kod) tool bus olarak canlandırılır.
- **Spec #3 (P0-F):** `_process_fallback_turn` (~630 satır) `fallback_engine.py`'ye
  çıkarılır; `EngineState` geçişleri bağlanır. Ses veri yolu değişmez — fallback
  de aynı `audio_stream_node`'u kullanır.
- **P1:** Idle learning, persona/memory optimizasyonu, hafıza yazma politikası
  (her cümle SQLite'a gitmez; yalnızca kalıcı olması gereken olgular).
