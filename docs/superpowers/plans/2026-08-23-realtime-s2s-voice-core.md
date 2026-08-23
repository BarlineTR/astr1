# Realtime S2S Ses Çekirdeği — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ASTRO'nun konuşma çekirdeğini cascaded (STT→LLM→Realtime-as-TTS) mimariden saf speech-to-speech'e döndürmek; sesin tek donanım sahibini kodla garanti altına almak; turn ve kesme otoritesini OpenAI server VAD'e devretmek.

**Architecture:** Turn yaşam döngüsü, session yapılandırması ve motor durumu `astro_ai/realtime/` altında ROS'suz/ağsız/donanımsız saf Python modüllere çıkarılır. `astro_realtime_node` bunları çağıran ince adaptöre dönüşür. Kesme otoritesi `interrupt_response: true` ile sunucuya geçer; Python tarafında yalnızca akustik yankı koruması ve playback durdurma kalır. `tts_node`'un realtime PCM aboneliği koddan silinerek tek playback sahipliği launch bayrağından bağımsız hale getirilir.

**Tech Stack:** Python 3.10, ROS 2 Humble (rclpy), `websockets`, `sounddevice`, `numpy`, pytest + unittest.mock. OpenAI Realtime API (`gpt-realtime-2.1-mini`).

**Spec:** `docs/superpowers/specs/2026-08-23-realtime-s2s-voice-core-design.md`

## Global Constraints

- **Branch:** `feat/realtime-s2s-voice-core`. `feat/lidar-slam-gazebo-simulation` commit almaz.
- **Test komutu — workspace source edilmeden çalıştırma.** Doğru komut her zaman:
  `source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && .venv/bin/python -m pytest`
  Source edilmezse 32 test `ModuleNotFoundError: astro_base` / `LookupError: astro_bringup` ile ortam kaynaklı olarak düşer.
- **Bilinen baseline fail'leri (kapsam dışı, düzeltilmeyecek, sayıya dahil):**
  `test_21_migration_from_legacy_json` ve `test_xtts_client_batch_size_default_is_one`.
  Plan sonunda beklenen: **2 fail**. Başka fail kabul edilmez.
- **`ai_brain_node.py` silinmez.** Yalnızca Realtime'a metin enjekte etme yolu kapanır.
- **`tts_node.py`'nin `/tts/say` yeteneği silinmez.** Yalnızca `/audio/realtime_output_pcm` aboneliği kaldırılır.
- **`astro_ai/realtime/` altındaki modüller hiçbir koşulda `rclpy`, `websockets`, `numpy` veya `sounddevice` import etmez.** Yalnızca standart kütüphane.
- **Türkçe log/mesaj metinleri korunur.** Repo Türkçe log kullanıyor; yeni loglar da Türkçe olur.
- `setup.py` değişikliği gerekmez: `find_packages(exclude=['test'])` `astro_ai.realtime` alt paketini otomatik bulur (`__init__.py` yeterli).

---

## Task 1: `TurnMachine` — turn yaşam döngüsü FSM

Saf Python durum makinesi. Kabul kriterlerindeki üç hata sayacını (`response_cancel_not_active`, `conversation_already_has_active_response`, generation isolation) donanım olmadan test edilebilir hale getirir.

**Files:**
- Create: `ros2_ws/src/astro_ai/astro_ai/realtime/__init__.py`
- Create: `ros2_ws/src/astro_ai/astro_ai/realtime/turn_machine.py`
- Test: `ros2_ws/src/astro_ai/test/test_turn_machine.py`

**Interfaces:**
- Consumes: hiçbir şey (ilk task)
- Produces:
  - `TurnState` (Enum): `IDLE`, `USER_SPEAKING`, `RESPONSE_PENDING`, `RESPONSE_STREAMING`, `TOOL_EXECUTING`, `RESPONSE_CANCELLING`
  - `Action` (Enum): `PUBLISH_AUDIO`, `DROP_AUDIO`, `STOP_PLAYBACK`, `SEND_CANCEL`, `IGNORE`
  - `TurnMachine(client_side_cancel: bool = False)`
  - `TurnMachine.state -> TurnState`
  - `TurnMachine.active_response_id -> Optional[str]`
  - `TurnMachine.generation_id -> int`
  - `TurnMachine.on_event(event_type: str, response_id: Optional[str] = None) -> list[Action]`
  - `TurnMachine.may_send_cancel() -> bool`
  - `TurnMachine.should_publish_audio(response_id: Optional[str] = None) -> bool`

- [ ] **Step 1: Paket iskeletini oluştur**

```bash
mkdir -p ros2_ws/src/astro_ai/astro_ai/realtime
cat > ros2_ws/src/astro_ai/astro_ai/realtime/__init__.py <<'PY'
"""ASTRO V1 — Realtime S2S çekirdeği.

Bu paketteki modüller ROS'suz, ağsız ve donanımsızdır: yalnızca standart
kütüphaneye bağlıdırlar. Amaç, konuşma turu mantığının Jetson veya WebSocket
olmadan test edilebilmesidir.
"""
PY
```

- [ ] **Step 2: Başarısız testi yaz**

`ros2_ws/src/astro_ai/test/test_turn_machine.py`:

```python
#!/usr/bin/env python3
"""ASTRO V1 — TurnMachine birim testleri (ROS'suz, donanımsız)."""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))

from astro_ai.realtime.turn_machine import Action, TurnMachine, TurnState


class TestHappyPath(unittest.TestCase):
    def setUp(self):
        self.m = TurnMachine()

    def test_starts_idle(self):
        self.assertEqual(self.m.state, TurnState.IDLE)
        self.assertIsNone(self.m.active_response_id)
        self.assertEqual(self.m.generation_id, 0)

    def test_full_turn_cycle(self):
        self.assertEqual(self.m.on_event("input_audio_buffer.speech_started"), [])
        self.assertEqual(self.m.state, TurnState.USER_SPEAKING)

        self.assertEqual(self.m.on_event("input_audio_buffer.speech_stopped"), [])
        self.assertEqual(self.m.state, TurnState.RESPONSE_PENDING)

        self.assertEqual(self.m.on_event("response.created", "resp_1"), [])
        self.assertEqual(self.m.state, TurnState.RESPONSE_STREAMING)
        self.assertEqual(self.m.active_response_id, "resp_1")
        self.assertEqual(self.m.generation_id, 1)

        self.assertEqual(
            self.m.on_event("response.output_audio.delta", "resp_1"),
            [Action.PUBLISH_AUDIO],
        )

        self.assertEqual(self.m.on_event("response.done", "resp_1"), [])
        self.assertEqual(self.m.state, TurnState.IDLE)
        self.assertIsNone(self.m.active_response_id)

    def test_generation_id_increments_per_response(self):
        for expected in (1, 2, 3):
            self.m.on_event("input_audio_buffer.speech_started")
            self.m.on_event("input_audio_buffer.speech_stopped")
            self.m.on_event("response.created", f"resp_{expected}")
            self.assertEqual(self.m.generation_id, expected)
            self.m.on_event("response.done")


class TestGenerationIsolation(unittest.TestCase):
    def setUp(self):
        self.m = TurnMachine()
        self.m.on_event("input_audio_buffer.speech_started")
        self.m.on_event("input_audio_buffer.speech_stopped")
        self.m.on_event("response.created", "resp_new")

    def test_stale_generation_audio_is_dropped(self):
        self.assertEqual(
            self.m.on_event("response.output_audio.delta", "resp_old"),
            [Action.DROP_AUDIO],
        )

    def test_audio_after_done_is_dropped(self):
        self.m.on_event("response.done")
        self.assertEqual(
            self.m.on_event("response.output_audio.delta", "resp_new"),
            [Action.DROP_AUDIO],
        )

    def test_should_publish_audio_false_without_active_response(self):
        self.m.on_event("response.done")
        self.assertFalse(self.m.should_publish_audio("resp_new"))


class TestCancelGuard(unittest.TestCase):
    """response_cancel_not_active = 0 kriterinin kanıtı."""

    def test_cancel_forbidden_when_idle(self):
        m = TurnMachine()
        self.assertFalse(m.may_send_cancel())

    def test_cancel_forbidden_while_user_speaking(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        self.assertFalse(m.may_send_cancel())

    def test_cancel_forbidden_in_response_pending(self):
        """Sunucu henüz response.created göndermedi — iptal edilecek response yok."""
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        self.assertEqual(m.state, TurnState.RESPONSE_PENDING)
        self.assertIsNone(m.active_response_id)
        self.assertFalse(m.may_send_cancel())

    def test_cancel_allowed_while_streaming(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        self.assertTrue(m.may_send_cancel())

    def test_cancel_forbidden_after_done(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        m.on_event("response.done")
        self.assertFalse(m.may_send_cancel())


class TestBargeIn(unittest.TestCase):
    def test_server_side_barge_in_stops_playback_without_cancel(self):
        """interrupt_response=true varsayılanı: sunucu keser, istemci yalnızca çalmayı durdurur."""
        m = TurnMachine(client_side_cancel=False)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")

        actions = m.on_event("input_audio_buffer.speech_started")
        self.assertEqual(actions, [Action.STOP_PLAYBACK])
        self.assertEqual(m.state, TurnState.RESPONSE_CANCELLING)

    def test_client_side_barge_in_also_sends_cancel(self):
        """REALTIME_INTERRUPT_RESPONSE=false yedek yolu."""
        m = TurnMachine(client_side_cancel=True)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")

        actions = m.on_event("input_audio_buffer.speech_started")
        self.assertEqual(actions, [Action.STOP_PLAYBACK, Action.SEND_CANCEL])

    def test_barge_in_during_response_pending_sends_no_cancel(self):
        """RESPONSE_PENDING'de active_response_id None — SEND_CANCEL üretilmemeli."""
        m = TurnMachine(client_side_cancel=True)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")

        actions = m.on_event("input_audio_buffer.speech_started")
        self.assertEqual(actions, [Action.STOP_PLAYBACK])
        self.assertNotIn(Action.SEND_CANCEL, actions)
        self.assertEqual(m.state, TurnState.RESPONSE_CANCELLING)

    def test_response_created_while_cancelling_binds_id_and_may_cancel(self):
        m = TurnMachine(client_side_cancel=True)
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("input_audio_buffer.speech_started")

        actions = m.on_event("response.created", "resp_late")
        self.assertEqual(m.state, TurnState.RESPONSE_CANCELLING)
        self.assertEqual(m.active_response_id, "resp_late")
        self.assertEqual(actions, [Action.SEND_CANCEL])

    def test_audio_during_cancelling_is_dropped(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        m.on_event("input_audio_buffer.speech_started")

        self.assertEqual(
            m.on_event("response.output_audio.delta", "resp_1"),
            [Action.DROP_AUDIO],
        )

    def test_cancelling_returns_to_idle_on_done(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("response.done")
        self.assertEqual(m.state, TurnState.IDLE)
        self.assertIsNone(m.active_response_id)


class TestToolFlow(unittest.TestCase):
    def test_tool_call_cycle(self):
        m = TurnMachine()
        m.on_event("input_audio_buffer.speech_started")
        m.on_event("input_audio_buffer.speech_stopped")
        m.on_event("response.created", "resp_1")

        m.on_event("response.function_call_arguments.done")
        self.assertEqual(m.state, TurnState.TOOL_EXECUTING)

        m.on_event("response.done")
        self.assertEqual(m.state, TurnState.TOOL_EXECUTING)
        self.assertIsNone(m.active_response_id)

        m.on_event("tool_result_sent")
        self.assertEqual(m.state, TurnState.RESPONSE_PENDING)

        m.on_event("response.created", "resp_2")
        self.assertEqual(m.state, TurnState.RESPONSE_STREAMING)
        self.assertEqual(m.generation_id, 2)


class TestInvalidTransitions(unittest.TestCase):
    """Tabloda olmayan her (durum, olay) çifti IGNORE döndürür, durum değişmez."""

    def test_speech_stopped_while_idle_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("input_audio_buffer.speech_stopped"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)

    def test_response_created_while_idle_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("response.created", "resp_x"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)
        self.assertIsNone(m.active_response_id)

    def test_unknown_event_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("some.unknown.event"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)

    def test_tool_result_while_idle_ignored(self):
        m = TurnMachine()
        self.assertEqual(m.on_event("tool_result_sent"), [Action.IGNORE])
        self.assertEqual(m.state, TurnState.IDLE)


class TestNeverCreatesResponse(unittest.TestCase):
    """conversation_already_has_active_response = 0 kriterinin kanıtı."""

    def test_no_action_ever_means_create_response(self):
        valid = {
            Action.PUBLISH_AUDIO,
            Action.DROP_AUDIO,
            Action.STOP_PLAYBACK,
            Action.SEND_CANCEL,
            Action.IGNORE,
        }
        self.assertEqual(set(Action), valid)

    def test_full_cycle_emits_no_creation_action(self):
        m = TurnMachine(client_side_cancel=True)
        seen = []
        for ev, rid in [
            ("input_audio_buffer.speech_started", None),
            ("input_audio_buffer.speech_stopped", None),
            ("response.created", "r1"),
            ("response.output_audio.delta", "r1"),
            ("input_audio_buffer.speech_started", None),
            ("response.done", None),
        ]:
            seen.extend(m.on_event(ev, rid))
        self.assertTrue(all(a in set(Action) for a in seen))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Testi çalıştır, başarısız olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_turn_machine.py -v
```

Beklenen: `ModuleNotFoundError: No module named 'astro_ai.realtime.turn_machine'` ile collection error.

- [ ] **Step 4: `turn_machine.py`'yi yaz**

`ros2_ws/src/astro_ai/astro_ai/realtime/turn_machine.py`:

```python
"""ASTRO V1 — Realtime konuşma turu durum makinesi.

Yan etki üretmez: ses yayınlamaz, WebSocket'e yazmaz, log basmaz. Yalnızca
`Action` kararları döndürür; yan etkileri çağıran düğüm uygular. Testlerin
donanım ve ağ olmadan koşabilmesinin sebebi budur.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional


class TurnState(str, Enum):
    IDLE = "IDLE"
    USER_SPEAKING = "USER_SPEAKING"
    RESPONSE_PENDING = "RESPONSE_PENDING"
    RESPONSE_STREAMING = "RESPONSE_STREAMING"
    TOOL_EXECUTING = "TOOL_EXECUTING"
    RESPONSE_CANCELLING = "RESPONSE_CANCELLING"


class Action(str, Enum):
    PUBLISH_AUDIO = "PUBLISH_AUDIO"
    DROP_AUDIO = "DROP_AUDIO"
    STOP_PLAYBACK = "STOP_PLAYBACK"
    SEND_CANCEL = "SEND_CANCEL"
    IGNORE = "IGNORE"


#: Bir response'a bağlıyken iptal göndermenin meşru olduğu durumlar.
_CANCELLABLE = (
    TurnState.RESPONSE_STREAMING,
    TurnState.TOOL_EXECUTING,
    TurnState.RESPONSE_CANCELLING,
)


class TurnMachine:
    """Tek bir Realtime oturumundaki konuşma turlarını izler.

    :param client_side_cancel: ``REALTIME_INTERRUPT_RESPONSE=false`` iken True.
        Varsayılan False'ta kesmeyi sunucu yapar ve makine hiç
        :data:`Action.SEND_CANCEL` üretmez.
    """

    def __init__(self, client_side_cancel: bool = False) -> None:
        self.state: TurnState = TurnState.IDLE
        self.active_response_id: Optional[str] = None
        self.generation_id: int = 0
        self._client_side_cancel = bool(client_side_cancel)

    # --- Guard'lar ---------------------------------------------------------

    def may_send_cancel(self) -> bool:
        """``response.cancel`` göndermenin güvenli olup olmadığı.

        ``RESPONSE_PENDING`` bilerek dışarıdadır: orada sunucu henüz
        ``response.created`` göndermemiştir, dolayısıyla iptal edilecek bir
        response yoktur ve istek ``response_cancel_not_active`` hatası üretir.
        """
        return self.active_response_id is not None and self.state in _CANCELLABLE

    def should_publish_audio(self, response_id: Optional[str] = None) -> bool:
        """Gelen audio delta'nın hoparlöre gitmesi gerekip gerekmediği."""
        if self.active_response_id is None:
            return False
        if response_id is None:
            return True
        return response_id == self.active_response_id

    # --- Olay girişi -------------------------------------------------------

    def on_event(
        self, event_type: str, response_id: Optional[str] = None
    ) -> List[Action]:
        """Bir sunucu olayını işler ve uygulanacak kararları döndürür.

        Boş liste "yapılacak bir şey yok" demektir; :data:`Action.IGNORE` ise
        "olay bu durumda geçersiz" demektir. Çağıran, IGNORE'u telemetriye yazar.
        """
        handler = {
            "input_audio_buffer.speech_started": self._on_speech_started,
            "input_audio_buffer.speech_stopped": self._on_speech_stopped,
            "response.created": self._on_response_created,
            "response.output_audio.delta": self._on_audio_delta,
            "response.function_call_arguments.done": self._on_function_call_done,
            "tool_result_sent": self._on_tool_result_sent,
            "response.done": self._on_response_done,
        }.get(event_type)
        if handler is None:
            return [Action.IGNORE]
        return handler(response_id)

    # --- Olay işleyicileri -------------------------------------------------

    def _on_speech_started(self, response_id: Optional[str]) -> List[Action]:
        if self.state in (TurnState.IDLE, TurnState.USER_SPEAKING):
            self.state = TurnState.USER_SPEAKING
            return []
        if self.state == TurnState.RESPONSE_CANCELLING:
            return []
        # RESPONSE_PENDING / RESPONSE_STREAMING / TOOL_EXECUTING → barge-in
        actions = [Action.STOP_PLAYBACK]
        self.state = TurnState.RESPONSE_CANCELLING
        if self._client_side_cancel and self.may_send_cancel():
            actions.append(Action.SEND_CANCEL)
        return actions

    def _on_speech_stopped(self, response_id: Optional[str]) -> List[Action]:
        if self.state != TurnState.USER_SPEAKING:
            return [Action.IGNORE]
        self.state = TurnState.RESPONSE_PENDING
        return []

    def _on_response_created(self, response_id: Optional[str]) -> List[Action]:
        if self.state == TurnState.RESPONSE_PENDING:
            self.active_response_id = response_id
            self.generation_id += 1
            self.state = TurnState.RESPONSE_STREAMING
            return []
        if self.state == TurnState.RESPONSE_CANCELLING:
            # Sunucu, barge-in'den önce yanıtı zaten kurmuştu. Id'yi bağla ki
            # istemci yedek yolu iptali doğru response'a gönderebilsin.
            self.active_response_id = response_id
            self.generation_id += 1
            if self._client_side_cancel and self.may_send_cancel():
                return [Action.SEND_CANCEL]
            return []
        return [Action.IGNORE]

    def _on_audio_delta(self, response_id: Optional[str]) -> List[Action]:
        if self.state == TurnState.RESPONSE_STREAMING and self.should_publish_audio(
            response_id
        ):
            return [Action.PUBLISH_AUDIO]
        return [Action.DROP_AUDIO]

    def _on_function_call_done(self, response_id: Optional[str]) -> List[Action]:
        if self.state != TurnState.RESPONSE_STREAMING:
            return [Action.IGNORE]
        self.state = TurnState.TOOL_EXECUTING
        return []

    def _on_tool_result_sent(self, response_id: Optional[str]) -> List[Action]:
        if self.state != TurnState.TOOL_EXECUTING:
            return [Action.IGNORE]
        self.state = TurnState.RESPONSE_PENDING
        return []

    def _on_response_done(self, response_id: Optional[str]) -> List[Action]:
        if self.state == TurnState.TOOL_EXECUTING:
            # Tool çağrısını taşıyan response bitti, ama tool hâlâ çalışıyor.
            self.active_response_id = None
            return []
        if self.state in (TurnState.RESPONSE_STREAMING, TurnState.RESPONSE_CANCELLING):
            self.active_response_id = None
            self.state = TurnState.IDLE
            return []
        return [Action.IGNORE]
```

- [ ] **Step 5: Testi çalıştır, geçtiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_turn_machine.py -v
```

Beklenen: tüm testler PASS.

- [ ] **Step 6: Commit**

```bash
git add ros2_ws/src/astro_ai/astro_ai/realtime/__init__.py \
        ros2_ws/src/astro_ai/astro_ai/realtime/turn_machine.py \
        ros2_ws/src/astro_ai/test/test_turn_machine.py
git commit -m "feat(realtime): TurnMachine — ROS'suz turn yaşam döngüsü durum makinesi"
```

---

## Task 2: `session_config` — yapılandırılabilir server VAD

`session.update` payload'ını üreten saf fonksiyon. `interrupt_response` burada devreye girer.

**Files:**
- Create: `ros2_ws/src/astro_ai/astro_ai/realtime/session_config.py`
- Test: `ros2_ws/src/astro_ai/test/test_session_config.py`
- Modify: `.env.example` (yeni anahtarlar)

**Interfaces:**
- Consumes: Task 1'in `realtime/__init__.py` paketi
- Produces:
  - `build_turn_detection(env: Optional[Mapping[str, str]] = None) -> dict`
  - `build_session_update(*, instructions: str, voice: str, tools: list, transcribe_model: str = "gpt-live-transcribe", language: str = "tr", env: Optional[Mapping[str, str]] = None) -> dict`

- [ ] **Step 1: Başarısız testi yaz**

`ros2_ws/src/astro_ai/test/test_session_config.py`:

```python
#!/usr/bin/env python3
"""ASTRO V1 — session.update payload üretici birim testleri."""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))

from astro_ai.realtime.session_config import build_session_update, build_turn_detection


class TestTurnDetectionDefaults(unittest.TestCase):
    def test_defaults_are_server_vad_500ms(self):
        td = build_turn_detection(env={})
        self.assertEqual(td["type"], "server_vad")
        self.assertEqual(td["threshold"], 0.70)
        self.assertEqual(td["prefix_padding_ms"], 300)
        self.assertEqual(td["silence_duration_ms"], 500)

    def test_create_response_is_true(self):
        """Yanıt üretimi sunucunun: manuel response.create kaldırıldı."""
        self.assertIs(build_turn_detection(env={})["create_response"], True)

    def test_interrupt_response_is_true(self):
        """Kesme otoritesi sunucuda: bab0512 regresyonunun onarımı."""
        self.assertIs(build_turn_detection(env={})["interrupt_response"], True)


class TestTurnDetectionOverrides(unittest.TestCase):
    def test_env_overrides_server_vad_fields(self):
        td = build_turn_detection(env={
            "REALTIME_VAD_THRESHOLD": "0.55",
            "REALTIME_VAD_PREFIX_MS": "250",
            "REALTIME_VAD_SILENCE_MS": "400",
        })
        self.assertEqual(td["threshold"], 0.55)
        self.assertEqual(td["prefix_padding_ms"], 250)
        self.assertEqual(td["silence_duration_ms"], 400)

    def test_interrupt_response_can_be_disabled(self):
        td = build_turn_detection(env={"REALTIME_INTERRUPT_RESPONSE": "false"})
        self.assertIs(td["interrupt_response"], False)

    def test_semantic_vad_shape(self):
        td = build_turn_detection(env={
            "REALTIME_VAD_TYPE": "semantic_vad",
            "REALTIME_VAD_EAGERNESS": "medium",
        })
        self.assertEqual(td["type"], "semantic_vad")
        self.assertEqual(td["eagerness"], "medium")
        self.assertIs(td["create_response"], True)
        self.assertIs(td["interrupt_response"], True)
        # semantic_vad server_vad alanlarını taşımaz
        self.assertNotIn("threshold", td)
        self.assertNotIn("silence_duration_ms", td)
        self.assertNotIn("prefix_padding_ms", td)

    def test_semantic_vad_eagerness_defaults_to_auto(self):
        td = build_turn_detection(env={"REALTIME_VAD_TYPE": "semantic_vad"})
        self.assertEqual(td["eagerness"], "auto")

    def test_unknown_vad_type_falls_back_to_server_vad(self):
        td = build_turn_detection(env={"REALTIME_VAD_TYPE": "magic_vad"})
        self.assertEqual(td["type"], "server_vad")

    def test_malformed_numeric_falls_back_to_default(self):
        td = build_turn_detection(env={"REALTIME_VAD_SILENCE_MS": "abc"})
        self.assertEqual(td["silence_duration_ms"], 500)


class TestSessionUpdateShape(unittest.TestCase):
    def setUp(self):
        self.payload = build_session_update(
            instructions="Sen ASTRO'sun.",
            voice="echo",
            tools=[{"type": "function", "name": "noop", "parameters": {}}],
            env={},
        )

    def test_top_level_shape(self):
        self.assertEqual(self.payload["type"], "session.update")
        self.assertEqual(self.payload["session"]["type"], "realtime")
        self.assertEqual(self.payload["session"]["instructions"], "Sen ASTRO'sun.")

    def test_turn_detection_nesting_path(self):
        """Doğrulanmış yol: session.audio.input.turn_detection"""
        td = self.payload["session"]["audio"]["input"]["turn_detection"]
        self.assertEqual(td["type"], "server_vad")

    def test_voice_and_transcription(self):
        audio = self.payload["session"]["audio"]
        self.assertEqual(audio["output"]["voice"], "echo")
        self.assertEqual(audio["input"]["transcription"]["model"], "gpt-live-transcribe")
        self.assertEqual(audio["input"]["transcription"]["language"], "tr")

    def test_tools_passed_through(self):
        self.assertEqual(len(self.payload["session"]["tools"]), 1)
        self.assertEqual(self.payload["session"]["tools"][0]["name"], "noop")

    def test_is_json_serializable(self):
        import json
        json.dumps(self.payload)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_session_config.py -v
```

Beklenen: `ModuleNotFoundError: No module named 'astro_ai.realtime.session_config'`.

- [ ] **Step 3: `session_config.py`'yi yaz**

`ros2_ws/src/astro_ai/astro_ai/realtime/session_config.py`:

```python
"""ASTRO V1 — OpenAI Realtime `session.update` payload üreticisi.

Doğrulanmış nesting yolu: ``session.audio.input.turn_detection``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional

DEFAULT_THRESHOLD = 0.70
DEFAULT_PREFIX_PADDING_MS = 300
DEFAULT_SILENCE_DURATION_MS = 500
DEFAULT_EAGERNESS = "auto"
DEFAULT_TRANSCRIBE_MODEL = "gpt-live-transcribe"
DEFAULT_LANGUAGE = "tr"


def _env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if env is None else env


def _as_float(raw: str, fallback: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _as_int(raw: str, fallback: int) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return fallback


def build_turn_detection(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Server VAD yapılandırmasını üretir.

    ``create_response`` her zaman True: yanıtı sunucu üretir, istemci
    ``response.create`` göndermez (tool sonucu istisnası hariç).
    """
    src = _env(env)
    interrupt = str(src.get("REALTIME_INTERRUPT_RESPONSE", "true")).strip().lower() != "false"
    vad_type = str(src.get("REALTIME_VAD_TYPE", "server_vad")).strip() or "server_vad"

    if vad_type == "semantic_vad":
        eagerness = str(src.get("REALTIME_VAD_EAGERNESS", DEFAULT_EAGERNESS)).strip()
        return {
            "type": "semantic_vad",
            "eagerness": eagerness or DEFAULT_EAGERNESS,
            "create_response": True,
            "interrupt_response": interrupt,
        }

    return {
        "type": "server_vad",
        "threshold": _as_float(src.get("REALTIME_VAD_THRESHOLD", ""), DEFAULT_THRESHOLD),
        "prefix_padding_ms": _as_int(
            src.get("REALTIME_VAD_PREFIX_MS", ""), DEFAULT_PREFIX_PADDING_MS
        ),
        "silence_duration_ms": _as_int(
            src.get("REALTIME_VAD_SILENCE_MS", ""), DEFAULT_SILENCE_DURATION_MS
        ),
        "create_response": True,
        "interrupt_response": interrupt,
    }


def build_session_update(
    *,
    instructions: str,
    voice: str,
    tools: List[Dict[str, Any]],
    transcribe_model: str = DEFAULT_TRANSCRIBE_MODEL,
    language: str = DEFAULT_LANGUAGE,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Tam `session.update` payload'ını üretir."""
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": instructions,
            "audio": {
                "input": {
                    "transcription": {"model": transcribe_model, "language": language},
                    "turn_detection": build_turn_detection(env),
                },
                "output": {"voice": voice},
            },
            "tools": tools,
        },
    }
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_session_config.py -v
```

Beklenen: tüm testler PASS.

- [ ] **Step 5: `.env.example`'a yeni anahtarları ekle**

`.env.example` içinde `REALTIME_TRANSCRIBE_MODEL` satırının hemen altına ekle:

```bash
# --- Realtime VAD (turn detection) ---
# Tip: 'server_vad' (sessizlik süresine bakar) | 'semantic_vad' (cümle
# tamamlanmasına bakar). Türkçe doğal konuşmada duraksamalar server_vad'i
# erken tetikleyebilir; semantic_vad bunu azaltır ama gecikmesi değişkendir.
# Kazanan gerçek Jetson benchmark'ıyla belirlenir — varsayılan sabit değil.
REALTIME_VAD_TYPE='server_vad'
# server_vad alanları:
REALTIME_VAD_THRESHOLD='0.70'
REALTIME_VAD_PREFIX_MS='300'
REALTIME_VAD_SILENCE_MS='500'
# semantic_vad alanı: auto | low | medium | high  ('auto' = medium)
REALTIME_VAD_EAGERNESS='auto'
# Barge-in otoritesi sunucuda. 'false' yaparsan istemci response.cancel
# göndermeye geri döner (yedek yol).
REALTIME_INTERRUPT_RESPONSE='true'
```

- [ ] **Step 6: Commit**

```bash
git add ros2_ws/src/astro_ai/astro_ai/realtime/session_config.py \
        ros2_ws/src/astro_ai/test/test_session_config.py .env.example
git commit -m "feat(realtime): yapılandırılabilir server VAD + interrupt_response"
```

---

## Task 3: `EngineState` — bağlantı katmanı durumu

Turn state machine'den ayrı tutulan bağlantı durumu. Bu spec'te yalnızca tanımlanır ve telemetriye bağlanır; fallback geçiş mantığı P0-F'in konusudur.

**Files:**
- Create: `ros2_ws/src/astro_ai/astro_ai/realtime/engine_state.py`
- Test: `ros2_ws/src/astro_ai/test/test_engine_state.py`

**Interfaces:**
- Consumes: Task 1'in `realtime/` paketi
- Produces:
  - `EngineState` (Enum): `REALTIME_PRIMARY`, `RECONNECTING`, `FALLBACK_ACTIVE`
  - `EngineStateTracker()`
  - `EngineStateTracker.state -> EngineState`
  - `EngineStateTracker.transition_to(new_state: EngineState) -> bool`

- [ ] **Step 1: Başarısız testi yaz**

`ros2_ws/src/astro_ai/test/test_engine_state.py`:

```python
#!/usr/bin/env python3
"""ASTRO V1 — Ses motoru bağlantı durumu birim testleri."""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))

from astro_ai.realtime.engine_state import EngineState, EngineStateTracker


class TestEngineStateTracker(unittest.TestCase):
    def test_starts_realtime_primary(self):
        self.assertEqual(EngineStateTracker().state, EngineState.REALTIME_PRIMARY)

    def test_all_pairwise_transitions_allowed(self):
        for src in EngineState:
            for dst in EngineState:
                if src == dst:
                    continue
                t = EngineStateTracker()
                t.state = src
                self.assertTrue(t.transition_to(dst), f"{src} -> {dst} reddedildi")
                self.assertEqual(t.state, dst)

    def test_self_transition_is_noop_and_returns_false(self):
        t = EngineStateTracker()
        self.assertFalse(t.transition_to(EngineState.REALTIME_PRIMARY))
        self.assertEqual(t.state, EngineState.REALTIME_PRIMARY)


class TestSeparationFromTurnMachine(unittest.TestCase):
    """İki durum makinesi asla karışmaz — yapısal garanti."""

    def test_engine_state_module_does_not_import_turn_machine(self):
        import astro_ai.realtime.engine_state as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("turn_machine", source)

    def test_turn_machine_module_does_not_import_engine_state(self):
        import astro_ai.realtime.turn_machine as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("engine_state", source)

    def test_state_names_do_not_overlap(self):
        from astro_ai.realtime.turn_machine import TurnState
        self.assertEqual(
            {s.value for s in EngineState} & {s.value for s in TurnState},
            set(),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_engine_state.py -v
```

Beklenen: `ModuleNotFoundError: No module named 'astro_ai.realtime.engine_state'`.

- [ ] **Step 3: `engine_state.py`'yi yaz**

`ros2_ws/src/astro_ai/astro_ai/realtime/engine_state.py`:

```python
"""ASTRO V1 — Ses motorunun bağlantı katmanı durumu.

Konuşma turu durumundan (``turn_machine.TurnState``) kasıtlı olarak ayrıdır ve
onu import etmez. Bir turun ortasında bağlantı kopabilir; bir bağlantı sağlıklı
ama hiçbir tur açık olmayabilir. İki eksen karıştırıldığında ortaya çıkan
tanımsız durumlar, bu ayrımın var olma sebebidir.
"""

from __future__ import annotations

from enum import Enum


class EngineState(str, Enum):
    REALTIME_PRIMARY = "REALTIME_PRIMARY"
    RECONNECTING = "RECONNECTING"
    FALLBACK_ACTIVE = "FALLBACK_ACTIVE"


class EngineStateTracker:
    """Bağlantı durumunu izler.

    Üç durum arasındaki tüm geçişler meşrudur: yeniden bağlanma başarısız olup
    fallback'e, fallback ağ dönünce doğrudan primary'ye geçebilir.
    """

    def __init__(self) -> None:
        self.state: EngineState = EngineState.REALTIME_PRIMARY

    def transition_to(self, new_state: EngineState) -> bool:
        """Durumu değiştirir. Aynı duruma geçiş no-op'tur ve False döner."""
        if new_state == self.state:
            return False
        self.state = new_state
        return True
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_engine_state.py -v
```

Beklenen: tüm testler PASS.

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/astro_ai/astro_ai/realtime/engine_state.py \
        ros2_ws/src/astro_ai/test/test_engine_state.py
git commit -m "feat(realtime): EngineState — turn durumundan ayrık bağlantı durumu"
```

---

## Task 4: Cascaded metin enjeksiyon hattını sök

`/tts/realtime_request` → `conversation.item.create(input_text)` → `response.create` yolunu kaldırır. Realtime artık "metni seslendiren TTS" olarak çağrılamaz.

**Files:**
- Modify: `ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py:687` (abonelik), `:766-812` (`_on_realtime_turn_request`), `:814-...` (`_dispatch_turn`), `_check_audio_delta_timeout`, `:1407` (turn queue boşaltma)
- Test: `ros2_ws/src/astro_ai/test/test_audio_ownership.py` (yeni, statik kaynak analizi)

**Interfaces:**
- Consumes: hiçbir şey
- Produces: `astro_realtime_node` artık `/tts/realtime_request` abonesi değil. `_turn_queue`, `_last_sent_generation_id`, `_watchdog_timer` alanları kalkar.

- [ ] **Step 1: Başarısız testi yaz**

`ros2_ws/src/astro_ai/test/test_audio_ownership.py`:

```python
#!/usr/bin/env python3
"""ASTRO V1 — Ses sahipliği ve cascaded hat sökümü statik testleri.

Bu testler kaynağı metin olarak okur. Sebep: "kimse bu topic'e abone
olmamalı" ve "bu kod yolu kalmamalı" gibi mimari değişmezler, çalışma zamanı
mock'larıyla değil kaynağın kendisiyle kanıtlanır.
"""

import os
import re
import unittest

SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
REALTIME_NODE = os.path.join(SRC, "astro_ai", "astro_ai", "astro_realtime_node.py")
TTS_NODE = os.path.join(SRC, "astro_audio", "astro_audio", "tts_node.py")
AUDIO_STREAM = os.path.join(SRC, "astro_audio", "astro_audio", "audio_stream_node.py")


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestCascadedPathRemoved(unittest.TestCase):
    def setUp(self):
        self.src = read(REALTIME_NODE)

    def test_no_realtime_request_subscription(self):
        self.assertNotIn("/tts/realtime_request", self.src)

    def test_no_turn_request_handler(self):
        self.assertNotIn("_on_realtime_turn_request", self.src)

    def test_no_dispatch_turn(self):
        self.assertNotIn("_dispatch_turn", self.src)

    def test_no_text_injection_prompt(self):
        """Realtime'a 'şunu seslendir' diye metin enjekte eden yol kalmamalı."""
        self.assertNotIn("Lütfen şu cevabı tam olarak seslendir", self.src)

    def test_no_audio_delta_watchdog(self):
        self.assertNotIn("_check_audio_delta_timeout", self.src)

    def test_no_turn_queue(self):
        self.assertNotIn("_turn_queue", self.src)


class TestAiBrainPreserved(unittest.TestCase):
    """ai_brain_node silinmez — cascaded mod ve gelecekteki fallback için durur."""

    def test_ai_brain_node_file_exists(self):
        self.assertTrue(
            os.path.isfile(os.path.join(SRC, "astro_ai", "astro_ai", "ai_brain_node.py"))
        )

    def test_tts_node_file_exists(self):
        self.assertTrue(os.path.isfile(TTS_NODE))


class TestSinglePlaybackOwner(unittest.TestCase):
    """Task 5'te yeşile döner."""

    def test_only_audio_stream_node_subscribes_to_output_pcm(self):
        subscribers = []
        for path in (TTS_NODE, AUDIO_STREAM):
            src = read(path)
            for line in src.splitlines():
                if "create_subscription" in line and "realtime_output_pcm" in line:
                    subscribers.append(os.path.basename(path))
        self.assertEqual(subscribers, ["audio_stream_node.py"])

    def test_tts_node_has_no_realtime_pcm_handler(self):
        self.assertNotIn("_on_realtime_output_pcm", read(TTS_NODE))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_audio_ownership.py -v
```

Beklenen: `TestCascadedPathRemoved`'ın 6 testi ve `TestSinglePlaybackOwner`'ın 2 testi FAIL; `TestAiBrainPreserved` PASS.

- [ ] **Step 3: Aboneliği ve turn dispatch kodunu sil**

`astro_realtime_node.py` içinde:

1. `:687` satırını sil:
```python
        self.create_subscription(String, "/tts/realtime_request", self._on_realtime_turn_request, 10)
```

2. `_on_realtime_turn_request` metodunun tamamını sil (`def _on_realtime_turn_request(self, msg: String):` satırından `_dispatch_turn` tanımının başladığı yere kadar).

3. `_dispatch_turn` metodunun tamamını sil.

4. `_check_audio_delta_timeout` metodunun tamamını sil.

5. `__init__` içindeki şu alan tanımlarını sil (grep ile bul):
```python
        self._turn_queue = []
        self._last_sent_generation_id = ...
        self._watchdog_timer = None
```

6. `response.done` işleyicisinde (`:1400` civarı) kuyruk boşaltmayı sil:
```python
            # Check if there are queued turns waiting to be dispatched
            if self._turn_queue:
                next_turn = self._turn_queue.pop(0)
                self._dispatch_turn(next_turn["generation_id"], next_turn["text"])
```

7. Aynı işleyicideki watchdog iptalini sil:
```python
            if self._watchdog_timer:
                try:
                    self._watchdog_timer.cancel()
                except Exception:
                    pass
                self._watchdog_timer = None
```

- [ ] **Step 4: Kalan referansları doğrula**

```bash
grep -n "_turn_queue\|_dispatch_turn\|_on_realtime_turn_request\|_check_audio_delta_timeout\|_last_sent_generation_id\|_watchdog_timer\|realtime_request" \
  ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py
```

Beklenen: **çıktı yok**. Varsa kalan referansları da temizle.

- [ ] **Step 5: `ai_brain_node`'un yayıncısını temizle**

`ros2_ws/src/astro_ai/astro_ai/ai_brain_node.py:336` satırını sil:
```python
        self.pub_realtime_req = self.create_publisher(String, "/tts/realtime_request", 10)
```

Ardından kalan kullanımları bul ve `self.pub_tts` (yani `/tts/say`) ile değiştir:

```bash
grep -n "pub_realtime_req" ros2_ws/src/astro_ai/astro_ai/ai_brain_node.py
```

Her kullanım için: `self.pub_realtime_req.publish(x)` → `self.pub_tts.publish(x)`.
Gerekçe: cascaded modda `ai_brain_node` metnini `tts_node`'a göndermeye devam
etmeli; kaybolmamalı.

- [ ] **Step 6: Testi çalıştır**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_audio_ownership.py -v
```

Beklenen: `TestCascadedPathRemoved` ve `TestAiBrainPreserved` PASS. `TestSinglePlaybackOwner`'ın 2 testi hâlâ FAIL (Task 5'te düzelecek).

- [ ] **Step 7: Tam suite'i çalıştır ve regresyon olmadığını doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest -q 2>&1 | tail -15
```

Beklenen fail listesi: 2 bilinen baseline + `test_audio_device_busy_is_reported_as_failure` +
`test_realtime_barge_in_preserves_semantics` + `TestSinglePlaybackOwner`'ın 2 testi.
Cascaded hattı kullanan başka bir test kırılırsa (ör. `/tts/realtime_request`
bekleyen), o testi yeni kontrata göre güncelle: `ai_brain_node` artık
`/tts/say`'e yayınlar.

- [ ] **Step 8: Commit**

```bash
git add ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py \
        ros2_ws/src/astro_ai/astro_ai/ai_brain_node.py \
        ros2_ws/src/astro_ai/test/test_audio_ownership.py
git commit -m "refactor(realtime): cascaded metin enjeksiyon hattını sök

Realtime artık 'metni seslendiren TTS' olarak çağrılamaz.
ai_brain_node korunuyor; cascaded modda /tts/say üzerinden konuşuyor."
```

---

## Task 5: `tts_node` — tek playback sahipliğini kodla garanti et

**Files:**
- Modify: `ros2_ws/src/astro_audio/astro_audio/tts_node.py:203` (abonelik), `:293-334` (`_on_realtime_output_pcm`)
- Test: `ros2_ws/src/astro_ai/test/test_audio_ownership.py` (Task 4'te yazıldı, burada yeşile döner)

**Interfaces:**
- Consumes: Task 4'ün `test_audio_ownership.py` dosyası
- Produces: `tts_node` artık `/audio/realtime_output_pcm` abonesi değil. `/tts/say` yeteneği değişmeden durur.

- [ ] **Step 1: Testin hâlâ başarısız olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_audio_ownership.py::TestSinglePlaybackOwner -v
```

Beklenen: 2 test FAIL.

- [ ] **Step 2: Aboneliği ve işleyiciyi sil**

`tts_node.py:203` satırını sil:
```python
        self.sub_realtime_pcm = self.create_subscription(String, "/audio/realtime_output_pcm", self._on_realtime_output_pcm, 50)
```

`_on_realtime_output_pcm` metodunun tamamını sil (`:293`'ten `:334`'e kadar olan blok).

Yerine `__init__` içinde, silinen abonelik satırının olduğu yere bir açıklama bırak:

```python
        # /audio/realtime_output_pcm'e BİLEREK abone olunmuyor. Realtime PCM'in
        # tek sahibi audio_stream_node'dur (giriş de çıkış da). Buraya bir
        # abonelik geri eklenirse aynı ALSA cihazına iki süreç yazar ve
        # "Device or resource busy" / "write to closed file" hataları döner.
        # Bkz. docs/superpowers/specs/2026-08-23-realtime-s2s-voice-core-design.md §5.2
```

- [ ] **Step 3: Kalan referansları doğrula**

```bash
grep -n "realtime_output_pcm\|_on_realtime_output_pcm" ros2_ws/src/astro_audio/astro_audio/tts_node.py
```

Beklenen: yalnızca Step 2'de eklenen açıklama satırları.

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_audio_ownership.py -v
```

Beklenen: tüm testler PASS.

- [ ] **Step 5: `tts_node`'un `/tts/say` yolunun bozulmadığını doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_audio/test/ -q 2>&1 | tail -10
```

Beklenen: yalnızca bilinen `test_xtts_client_batch_size_default_is_one` fail'i.

- [ ] **Step 6: Commit**

```bash
git add ros2_ws/src/astro_audio/astro_audio/tts_node.py
git commit -m "fix(audio): tts_node'un realtime PCM aboneliğini kaldır

Tek playback sahipliği artık launch bayrağına değil koda bağlı:
voice_engine:=cascaded bile çift sahip yaratamaz."
```

---

## Task 6: `TurnMachine`'i düğüme bağla + barge-in otoritesini sunucuya devret

**Files:**
- Modify: `ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py` — `__init__`, `_send_session_update`, `_handle_realtime_event`, `_on_input_pcm`
- Modify: `ros2_ws/src/astro_ai/test/test_provider_and_fallback.py:723-741` (`test_realtime_barge_in_preserves_semantics` yeniden yazılır)

**Interfaces:**
- Consumes: `TurnMachine`, `Action`, `TurnState` (Task 1); `build_session_update` (Task 2); `EngineStateTracker`, `EngineState` (Task 3)
- Produces: `AstroRealtimeNode.turn_machine` (`TurnMachine` örneği), `AstroRealtimeNode.engine_state` (`EngineStateTracker` örneği)

- [ ] **Step 1: Eski barge-in testini yeni kontrata göre yeniden yaz**

`test_provider_and_fallback.py` içindeki `test_realtime_barge_in_preserves_semantics`
metodunu tamamen şununla değiştir:

```python
    def test_realtime_barge_in_stops_playback_without_client_cancel(self):
        """Sunucu tarafı barge-in: interrupt_response=true iken istemci response.cancel GÖNDERMEZ.

        Eski kontrat istemcinin cancel göndermesini bekliyordu. Kesme otoritesi
        artık sunucuda (session.audio.input.turn_detection.interrupt_response),
        istemcinin tek işi çalmayı durdurmak.
        """
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.realtime.turn_machine import TurnState

        node = AstroRealtimeNode()
        node.turn_machine._client_side_cancel = False
        node._is_playback_active = True
        node.pub_interrupt = MagicMock()

        # Sunucu bir yanıt akıtıyor
        node.turn_machine.on_event("input_audio_buffer.speech_started")
        node.turn_machine.on_event("input_audio_buffer.speech_stopped")
        node.turn_machine.on_event("response.created", "resp_1")

        mock_ws = AsyncMock()
        asyncio.run(node._handle_realtime_event(
            mock_ws, {"type": "input_audio_buffer.speech_started"}
        ))

        self.assertEqual(node.turn_machine.state, TurnState.RESPONSE_CANCELLING)
        node.pub_interrupt.publish.assert_called_once()
        mock_ws.send.assert_not_called()

    def test_realtime_barge_in_client_fallback_sends_cancel(self):
        """REALTIME_INTERRUPT_RESPONSE=false yedek yolu: istemci cancel gönderir."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = AstroRealtimeNode()
        node.turn_machine._client_side_cancel = True
        node._is_playback_active = True
        node.pub_interrupt = MagicMock()

        node.turn_machine.on_event("input_audio_buffer.speech_started")
        node.turn_machine.on_event("input_audio_buffer.speech_stopped")
        node.turn_machine.on_event("response.created", "resp_1")

        mock_ws = AsyncMock()
        asyncio.run(node._handle_realtime_event(
            mock_ws, {"type": "input_audio_buffer.speech_started"}
        ))

        node.pub_interrupt.publish.assert_called_once()
        mock_ws.send.assert_called_once_with(json.dumps({"type": "response.cancel"}))

    def test_realtime_never_sends_manual_response_create_on_speech_stopped(self):
        """create_response=true: yanıtı sunucu üretir, istemci response.create göndermez."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = AstroRealtimeNode()
        node._is_sleeping = False
        node.turn_machine.on_event("input_audio_buffer.speech_started")

        mock_ws = AsyncMock()
        asyncio.run(node._handle_realtime_event(
            mock_ws, {"type": "input_audio_buffer.speech_stopped"}
        ))

        for call in mock_ws.send.call_args_list:
            self.assertNotIn("response.create", str(call))
```

- [ ] **Step 2: Testleri çalıştır, başarısız olduklarını doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_provider_and_fallback.py -k "barge_in or manual_response_create" -v
```

Beklenen: `AttributeError: 'AstroRealtimeNode' object has no attribute 'turn_machine'`.

- [ ] **Step 3: `__init__` içinde makineleri kur**

`astro_realtime_node.py` `__init__` içinde, publisher tanımlarının hemen ardına ekle:

```python
        from astro_ai.realtime.engine_state import EngineState, EngineStateTracker
        from astro_ai.realtime.turn_machine import Action, TurnMachine, TurnState

        # Kesme otoritesi sunucuda; istemci yedek yolu yalnızca
        # REALTIME_INTERRUPT_RESPONSE=false iken devreye girer.
        _client_cancel = os.getenv("REALTIME_INTERRUPT_RESPONSE", "true").strip().lower() == "false"
        self.turn_machine = TurnMachine(client_side_cancel=_client_cancel)
        self.engine_state = EngineStateTracker()
        self.get_logger().info(
            f"[VOICE ENGINE STATE]\n"
            f"state={self.engine_state.state.value}\n"
            f"cancel_authority={'client' if _client_cancel else 'server'}"
        )
```

Ayrıca `_publish_realtime_state` metodunun içine, mevcut yayın kodunun ardına
motor durumunu da ekle ki iki eksen tek yerde görünsün:

```python
        self.get_logger().debug(
            f"[VOICE ENGINE STATE] engine={self.engine_state.state.value} "
            f"turn={self.turn_machine.state.value}"
        )
```

`_websocket_worker`'daki yeniden bağlanma döngüsünde, bağlantı koptuğunda ve
geri geldiğinde motoru güncelle:

```python
        # Bağlantı koptuğunda (except / reconnect dalında):
        self.engine_state.transition_to(EngineState.RECONNECTING)

        # session.created / session.updated alındığında:
        self.engine_state.transition_to(EngineState.REALTIME_PRIMARY)

        # _fallback_mode True'ya çekildiğinde:
        self.engine_state.transition_to(EngineState.FALLBACK_ACTIVE)
```

`Action`, `TurnState`, `EngineState` isimlerinin modül seviyesinde de gerekli
olacağı için, dosyanın üst kısmındaki import bloğuna (satır ~40 civarı,
`from std_msgs.msg import ...` satırlarının ardına) ekle:

```python
from astro_ai.realtime.engine_state import EngineState, EngineStateTracker
from astro_ai.realtime.turn_machine import Action, TurnMachine, TurnState
```

ve `__init__` içindeki yerel import satırlarını sil.

- [ ] **Step 4: `_send_session_update`'i `build_session_update`'e devret**

`_send_session_update` içindeki `session_config = { ... }` sözlük literalini,
`tools` listesini bir yerel değişkene çıkararak şununla değiştir:

```python
    async def _send_session_update(self, ws):
        """Persona, tool'lar ve turn detection ile oturumu yapılandırır."""
        from astro_ai.realtime.session_config import build_session_update

        identity = self._get_active_biometric_identity()
        system_prompt = self._build_current_system_prompt()

        tools = [
            # ... mevcut tools listesi buraya OLDUĞU GİBİ taşınır ...
        ]

        session_config = build_session_update(
            instructions=system_prompt,
            voice=self.realtime_voice,
            tools=tools,
            transcribe_model=self.realtime_transcribe_model,
            language="tr",
        )

        await ws.send(json.dumps(session_config))
        td = session_config["session"]["audio"]["input"]["turn_detection"]
        self.get_logger().info(
            f"✨ [Realtime WS] Oturum Yapılandırıldı. "
            f"Kişilik: [{self.persona_name.upper()}], Ses: [{self.realtime_voice}], "
            f"Kimlik: [{identity.get('name')}]"
        )
        self.get_logger().info(
            f"[REALTIME VAD]\n"
            f"type={td['type']}\n"
            f"create_response={td['create_response']}\n"
            f"interrupt_response={td['interrupt_response']}\n"
            f"silence_duration_ms={td.get('silence_duration_ms', 'n/a')}\n"
            f"eagerness={td.get('eagerness', 'n/a')}"
        )
```

> Mevcut `tools` listesi (`get_live_weather`, `set_reminder`, `save_user_memory`,
> `search_memory`, `inspect_camera_view`, `move_robot`, `enroll_user_biometrics`,
> `change_persona`, `delete_user_biometrics`) hiçbir şeyi değiştirmeden taşınır.

- [ ] **Step 5: `_handle_realtime_event`'i `TurnMachine`'e devret**

`speech_started` dalını tamamen şununla değiştir:

```python
        # 3. User Speech Started
        elif event_type == "input_audio_buffer.speech_started":
            actions = self.turn_machine.on_event("input_audio_buffer.speech_started")
            if Action.STOP_PLAYBACK in actions:
                self.get_logger().info(
                    "⚡ [Realtime Barge-In] Kullanıcı lafa girdi — çalma durduruluyor "
                    "(kesmeyi sunucu yapıyor)."
                )
                self._is_responding = False
                intr_msg = Bool()
                intr_msg.data = True
                self.pub_interrupt.publish(intr_msg)
            if Action.SEND_CANCEL in actions:
                try:
                    await ws.send(json.dumps({"type": "response.cancel"}))
                except Exception as ce:
                    self.get_logger().debug(f"response.cancel gönderilemedi: {ce}")
            if Action.IGNORE in actions:
                self.get_logger().debug(
                    f"[REALTIME EVENT IGNORED] event=speech_started state={self.turn_machine.state.value}"
                )
```

`speech_stopped` dalını şununla değiştir:

```python
        # 3b. User Speech Stopped
        elif event_type == "input_audio_buffer.speech_stopped":
            if self._is_sleeping:
                return
            self.turn_machine.on_event("input_audio_buffer.speech_stopped")
            self.get_logger().info("🤫 [Realtime] Cümle bitti, yanıtı sunucu üretecek...")
            # Biyometri doğrulaması WebSocket event loop'unu BLOKLAMAZ.
            try:
                asyncio.create_task(asyncio.to_thread(self._run_voice_identification))
            except Exception:
                threading.Thread(target=self._run_voice_identification, daemon=True).start()
```

`response.created` dalında, mevcut alan atamalarının başına ekle:

```python
        elif event_type == "response.created":
            _rid = event.get("response", {}).get("id")
            _actions = self.turn_machine.on_event("response.created", _rid)
            if Action.SEND_CANCEL in _actions:
                try:
                    await ws.send(json.dumps({"type": "response.cancel"}))
                except Exception as ce:
                    self.get_logger().debug(f"response.cancel gönderilemedi: {ce}")
            self.active_response_id = _rid
            self.active_generation_id = self.turn_machine.generation_id
            self.realtime_current_generation_id = self.turn_machine.generation_id
            # ... mevcut telemetri alanları (_response_start_time, _packets_for_gen,
            #     _bytes_for_gen, _first_audio_time, realtime_response_state,
            #     _is_responding) DEĞİŞMEDEN kalır ...
```

`response.done` / `response.cancelled` dalında, mevcut telemetri log'undan sonra
durum sıfırlamayı `TurnMachine`'e devret:

```python
            self.turn_machine.on_event("response.done")
            self._is_responding = False
            self.realtime_response_state = "IDLE"
            self.active_response_id = None
            self.active_generation_id = None
```

Audio delta dalında (`response.output_audio.delta` / `response.audio.delta`),
yayın kararını makineye sor. Mevcut yayın kodunu şu kontrolle sar:

```python
            _rid = event.get("response_id")
            if Action.PUBLISH_AUDIO not in self.turn_machine.on_event(
                "response.output_audio.delta", _rid
            ):
                self.get_logger().debug(
                    f"[REALTIME AUDIO DROPPED] response_id={_rid} "
                    f"active={self.turn_machine.active_response_id}"
                )
                return
            # ... mevcut base64 çözme + pub_output_pcm.publish(...) kodu ...
```

Tool çağrısı dalında (`response.function_call_arguments.done`), `_execute_realtime_tool`
çağrısından önce ve tool sonucu gönderildikten sonra makineyi bilgilendir:

```python
            self.turn_machine.on_event("response.function_call_arguments.done")
            try:
                tool_result = await asyncio.to_thread(self._execute_realtime_tool, func_name, args)
            except Exception as te:
                self.get_logger().error(f"❌ [Tool Hatası]: {te}")
                tool_result = {"status": "error", "message": str(te)}
            # ... mevcut conversation.item.create + response.create gönderimi ...
            self.turn_machine.on_event("tool_result_sent")
```

> Tool sonrası `response.create` gönderimi `create_response` kuralının istisnası
> değildir: sunucu VAD yalnızca kullanıcı konuşmasının bitişinde yanıt üretir,
> tool sonucu sonrası devam yanıtını istemci istemek zorundadır.

- [ ] **Step 6: `_on_input_pcm`'deki barge-in bloğunun rütbesini düşür**

`_on_input_pcm` içindeki `if self._barge_in_latched: return` satırından sonra
gelen bloğu bul. Şu satırları **sil**:

```python
            self.state_machine.transition_to(RobotState.INTERRUPTED)
            self._is_responding = False
            self._is_playback_active = False
            self._fallback_generation_id += 1
```

ve

```python
            self.state_machine.transition_to(RobotState.LISTENING)
```

Geriye kalan (yankı koruma penceresi, `pub_interrupt.publish`, TTS motoru
`cancel()` çağrıları, telemetri log'u) **olduğu gibi durur**. Log mesajının
başına gerekçeyi ekle:

```python
            self.get_logger().info(
                f"⚡ [Akustik Yankı Koruması] Yerel eşik aşıldı — yalnızca çalma "
                f"durduruluyor. Turn durumu sunucunun VAD'ine ait. "
                f"(RMS: {local_rms:.0f}, Peak: {peak_val}, barge_in_after_ms={barge_in_after_ms})"
            )
```

- [ ] **Step 7: Testleri çalıştır**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_provider_and_fallback.py -k "barge_in or manual_response_create" -v
```

Beklenen: 3 test de PASS.

- [ ] **Step 8: Tam suite'i çalıştır**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest -q 2>&1 | tail -15
```

Beklenen fail'ler: 2 bilinen baseline + `test_audio_device_busy_is_reported_as_failure`.
Başka fail varsa düzelt.

- [ ] **Step 9: Commit**

```bash
git add ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py \
        ros2_ws/src/astro_ai/test/test_provider_and_fallback.py
git commit -m "feat(realtime): turn ve kesme otoritesini sunucuya devret

TurnMachine düğüme bağlandı; interrupt_response ile barge-in artık
sunucunun işi. _on_input_pcm'deki yerel barge-in yalnızca akustik
yankı koruması ve playback durdurma yapıyor."
```

---

## Task 7: Bozuk `Device busy` testini onar

Test `mock_sd` adlı tanımsız bir isme başvuruyor (`NameError`). Kapı 1'in "Device busy = 0" kriterinin tek otomatik kanıtı bu test.

**Files:**
- Modify: `ros2_ws/src/astro_ai/test/test_p0_runtime_stabilization.py:1611-1631`

**Interfaces:**
- Consumes: hiçbir şey
- Produces: hiçbir şey (yalnızca test onarımı)

- [ ] **Step 1: Mevcut hatayı gör**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest "ros2_ws/src/astro_ai/test/test_p0_runtime_stabilization.py::TestP02RealtimeTurnPipelineAndHardwareCorrection::test_audio_device_busy_is_reported_as_failure" -v
```

Beklenen: `NameError: name 'mock_sd' is not defined`.

- [ ] **Step 2: Testi onar**

`test_audio_device_busy_is_reported_as_failure` metodunu tamamen şununla değiştir:

```python
    def test_audio_device_busy_is_reported_as_failure(self):
        """7. Error Handling: Cihaz meşgulse [AUDIO ERROR] direction=input reason=device_unavailable loglanır."""
        import astro_audio.audio_stream_node as asn
        from astro_audio.audio_stream_node import AudioStreamNode

        node = AudioStreamNode.__new__(AudioStreamNode)
        node._in_dev_idx = 0
        node._in_device_name = "ReSpeaker 4 Mic Array (hw:0,0)"
        node._input_stream = None
        node._input_stream_alive = False

        logs = []
        mock_logger = MagicMock()
        mock_logger.warn = lambda msg: logs.append(msg)
        mock_logger.error = lambda msg: logs.append(msg)
        mock_logger.info = lambda msg: logs.append(msg)
        node.get_logger = lambda: mock_logger
        node.create_subscription = MagicMock()

        fake_sd = MagicMock()
        fake_sd.__name__ = "fake_sounddevice"
        fake_sd.RawInputStream.side_effect = Exception("Device or resource busy")

        with patch.object(asn, "sd", fake_sd):
            node._start_input_stream()

        self.assertFalse(node._input_stream_alive)
        log_text = "\n".join(logs)
        self.assertIn("[AUDIO ERROR]", log_text)
        self.assertIn("direction=input", log_text)
        self.assertIn("reason=device_unavailable", log_text)
```

> `fake_sd.__name__` bilerek `"sounddevice"` DEĞİL: `_start_input_stream`,
> pytest altında `getattr(sd, "__name__", "") == "sounddevice"` ise gerçek
> donanıma dokunmamak için erken çıkar (`audio_stream_node.py:243`). Sahte adla
> o koruma devre dışı kalır ve hata yolu gerçekten test edilir.

- [ ] **Step 3: Testi çalıştır, geçtiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest "ros2_ws/src/astro_ai/test/test_p0_runtime_stabilization.py::TestP02RealtimeTurnPipelineAndHardwareCorrection::test_audio_device_busy_is_reported_as_failure" -v
```

Beklenen: PASS.

- [ ] **Step 4: Commit**

```bash
git add ros2_ws/src/astro_ai/test/test_p0_runtime_stabilization.py
git commit -m "test(audio): Device busy testindeki tanımsız mock_sd referansını onar"
```

---

## Task 8: `move_robot` güvenlik kapısı

`bab0512` bu tool'u motor sağlığı kontrolü olmadan canlıya aldı. Ayrıca `/cmd_vel`'in gerçek robotta tüketicisi yok — tool sessizce `success` dönüp tekerlek dönmüyor.

**Files:**
- Modify: `ros2_ws/src/astro_base/src/serial_bridge.py:422-446` (`publish_diag` alanları) ve `__init__` (periyodik diag timer)
- Modify: `ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py` (`/arduino/diagnostics` aboneliği, `move_robot` kapısı)
- Test: `ros2_ws/src/astro_ai/test/test_move_robot_safety.py`

**Interfaces:**
- Consumes: hiçbir şey
- Produces:
  - `serial_bridge` `/arduino/diagnostics` içinde şu `KeyValue` anahtarlarını yayınlar: `serial_connected`, `handshake`, `heartbeat_healthy`, `motor_enabled` (hepsi `"True"`/`"False"` metni)
  - `AstroRealtimeNode.motor_health -> dict` (anahtarlar: `serial_connected`, `handshake`, `heartbeat_healthy`, `motor_enabled`, `updated_at`)
  - `AstroRealtimeNode._motor_health_ok() -> tuple[bool, str]`
  - `AstroRealtimeNode.MOTOR_HEALTH_STALE_S = 2.0`

- [ ] **Step 1: Başarısız testi yaz**

`ros2_ws/src/astro_ai/test/test_move_robot_safety.py`:

```python
#!/usr/bin/env python3
"""ASTRO V1 — move_robot güvenlik kapısı testleri."""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"


def _healthy(node, **overrides):
    health = {
        "serial_connected": True,
        "handshake": True,
        "heartbeat_healthy": True,
        "motor_enabled": True,
        "updated_at": time.monotonic(),
    }
    health.update(overrides)
    node.motor_health = health


class TestMoveRobotSafetyGate(unittest.TestCase):
    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()
        self.node.pub_cmd_vel = MagicMock()
        self.node.has_motion_backend = True

    def test_rejected_when_no_health_received_at_all(self):
        self.node.motor_health = {}
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["reason"], "motor_health_unproven")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_serial_disconnected(self):
        _healthy(self.node, serial_connected=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_handshake_missing(self):
        _healthy(self.node, handshake=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_heartbeat_unhealthy(self):
        _healthy(self.node, heartbeat_healthy=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_motor_disabled(self):
        _healthy(self.node, motor_enabled=False)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_health_is_stale(self):
        """Arduino ölürse son 'sağlıklı' mesaj hareketi yetkilendirmemeli."""
        _healthy(self.node, updated_at=time.monotonic() - 30.0)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["reason"], "motor_health_stale")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_rejected_when_no_motion_backend(self):
        """base_bridge yokken /cmd_vel'i kimse dinlemiyor — sessizce başarı DÖNMEZ."""
        _healthy(self.node)
        self.node.has_motion_backend = False
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(res["reason"], "no_motion_backend")
        self.node.pub_cmd_vel.publish.assert_not_called()

    def test_allowed_when_fully_healthy(self):
        _healthy(self.node)
        res = self.node._execute_realtime_tool("move_robot", {"direction": "forward"})
        self.assertEqual(res["status"], "success")
        self.node.pub_cmd_vel.publish.assert_called()

    def test_stop_is_always_allowed(self):
        """Durdurma komutu güvenlik kapısına takılmaz — durmak her zaman güvenlidir."""
        self.node.motor_health = {}
        res = self.node._execute_realtime_tool("move_robot", {"direction": "stop"})
        self.assertEqual(res["status"], "success")
        self.node.pub_cmd_vel.publish.assert_called()


class TestMotorHealthParsing(unittest.TestCase):
    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()

    def test_diagnostics_message_populates_health(self):
        # SimpleNamespace kullanılıyor: MagicMock'ta `name=` özel bir kwarg'dır
        # (mock'un adını ayarlar, attribute yaratmaz) ve sessizce yanıltır.
        from types import SimpleNamespace

        kv = [
            SimpleNamespace(key="serial_connected", value="True"),
            SimpleNamespace(key="handshake", value="True"),
            SimpleNamespace(key="heartbeat_healthy", value="True"),
            SimpleNamespace(key="motor_enabled", value="False"),
        ]
        status = SimpleNamespace(name="arduino", values=kv)
        msg = SimpleNamespace(status=[status])

        self.node._on_arduino_diagnostics(msg)

        self.assertTrue(self.node.motor_health["serial_connected"])
        self.assertTrue(self.node.motor_health["handshake"])
        self.assertTrue(self.node.motor_health["heartbeat_healthy"])
        self.assertFalse(self.node.motor_health["motor_enabled"])
        self.assertGreater(self.node.motor_health["updated_at"], 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_move_robot_safety.py -v
```

Beklenen: `AttributeError: 'AstroRealtimeNode' object has no attribute 'motor_health'`.

- [ ] **Step 3: `serial_bridge` diagnostics alanlarını genişlet**

`serial_bridge.py` `publish_diag` içindeki `st.values` listesini şununla değiştir:

```python
        motors_disabled = bool(flags & 0x01)
        st.values = [
            KeyValue(key="vbat_mV", value=str(vbat_mV)),
            KeyValue(key="mcu_temp_c", value=str(temp_cX100 / 100.0)),
            KeyValue(key="flags", value=hex(flags)),
            KeyValue(key="arduino_alive", value=str(self.arduino_alive)),
            KeyValue(key="port", value=str(self.port or "disconnected")),
            # move_robot güvenlik kapısının okuduğu dört alan:
            KeyValue(
                key="serial_connected",
                value=str(bool(self.ser is not None and self.ser.is_open)),
            ),
            KeyValue(key="handshake", value=str(bool(self.handshake_ok))),
            KeyValue(key="heartbeat_healthy", value=str(bool(self.arduino_alive))),
            KeyValue(key="motor_enabled", value=str(bool(self.arduino_alive and not motors_disabled))),
        ]
```

- [ ] **Step 4: `serial_bridge`'e periyodik diagnostics ekle**

`publish_diag` yalnızca Arduino'dan STATUS paketi geldiğinde çağrılıyor. Arduino
ölürse hiç mesaj gelmez ve tüketici son "sağlıklı" mesajı sonsuza kadar görür.
`__init__` içinde `self.hb_timer = ...` satırının hemen ardına ekle:

```python
        # Arduino sussa bile sağlık durumu yayınlanmalı: aksi hâlde tüketiciler
        # son 'sağlıklı' mesajı sonsuza kadar taze sanır.
        self.diag_timer = self.create_timer(0.5, self._publish_heartbeat_diag)
```

Ve `publish_diag` metodunun hemen ardına ekle:

```python
    def _publish_heartbeat_diag(self):
        """Bağlantı kopukken bile sağlık durumunu yayınlar (0.5 s)."""
        if self.arduino_alive:
            return  # Canlıyken STATUS paketleri zaten publish_diag'ı çağırıyor.
        self.publish_diag(0, 0, 0x01)
```

- [ ] **Step 5: Realtime düğümüne diagnostics aboneliği ve kapı ekle**

`astro_realtime_node.py` üst import bloğuna ekle:

```python
try:
    from diagnostic_msgs.msg import DiagnosticArray
except ImportError:
    DiagnosticArray = None  # type: ignore
```

`__init__` içinde, `self.pub_cmd_vel = ...` satırının ardına ekle:

```python
        #: Motor sağlığı kanıtlanmadan hareket yok. Alanlar
        #: /arduino/diagnostics'ten gelir (serial_bridge.publish_diag).
        self.motor_health: Dict[str, Any] = {}
        #: base_bridge yoksa /cmd_vel'i kimse dinlemiyor demektir.
        self.has_motion_backend = os.getenv("ASTRO_MOTION_BACKEND", "").strip().lower() in ("base_bridge", "nav2", "sim")
        if DiagnosticArray is not None:
            self.create_subscription(
                DiagnosticArray, "/arduino/diagnostics", self._on_arduino_diagnostics, 10
            )
```

`Dict` ve `Any` zaten `typing`'den import edilmiş durumda (dosya başı).

Sınıf gövdesine, `__init__`'in hemen öncesine sabit ekle:

```python
    #: Bu süreden eski sağlık mesajı hareketi yetkilendirmez.
    MOTOR_HEALTH_STALE_S = 2.0
```

Ve şu iki metodu `_execute_realtime_tool`'un hemen öncesine ekle:

```python
    def _on_arduino_diagnostics(self, msg: Any):
        """/arduino/diagnostics'ten motor sağlık alanlarını okur."""
        try:
            for status in getattr(msg, "status", []):
                values = {kv.key: kv.value for kv in getattr(status, "values", [])}
                if "heartbeat_healthy" not in values:
                    continue
                self.motor_health = {
                    "serial_connected": values.get("serial_connected", "False") == "True",
                    "handshake": values.get("handshake", "False") == "True",
                    "heartbeat_healthy": values.get("heartbeat_healthy", "False") == "True",
                    "motor_enabled": values.get("motor_enabled", "False") == "True",
                    "updated_at": time.monotonic(),
                }
                return
        except Exception as exc:
            self.get_logger().debug(f"_on_arduino_diagnostics: yok sayılan hata ({exc})")

    def _motor_health_ok(self) -> Tuple[bool, str]:
        """Hareketin güvenli olup olmadığını ve değilse sebebini döndürür."""
        if not self.has_motion_backend:
            return False, "no_motion_backend"
        health = self.motor_health
        if not health:
            return False, "motor_health_unproven"
        age = time.monotonic() - float(health.get("updated_at", 0.0))
        if age > self.MOTOR_HEALTH_STALE_S:
            return False, "motor_health_stale"
        for key in ("serial_connected", "handshake", "heartbeat_healthy", "motor_enabled"):
            if not health.get(key, False):
                return False, "motor_health_unproven"
        return True, "ok"
```

`Tuple` zaten `typing`'den import edilmiş durumda.

- [ ] **Step 6: `move_robot` dalına kapıyı yerleştir**

`_execute_realtime_tool` içindeki `elif name == "move_robot":` dalının en başına,
`direction` okunduktan hemen sonra ekle:

```python
        elif name == "move_robot":
            direction = args.get("direction", "stop").lower().strip()

            # Durmak her zaman güvenlidir; kapıya takılmaz.
            if direction != "stop":
                ok, reason = self._motor_health_ok()
                if not ok:
                    self.get_logger().warn(
                        f"[MOTOR SAFETY BLOCK]\nreason={reason}\ntool=move_robot\ndirection={direction}"
                    )
                    messages = {
                        "no_motion_backend": "Hareket sürücüm bağlı değil, tekerleklerimi süremiyorum.",
                        "motor_health_stale": "Arduino'dan sağlık bilgisi gelmiyor, güvenlik için hareket etmiyorum.",
                        "motor_health_unproven": "Motor sağlığım doğrulanmadı, güvenlik için hareket etmiyorum.",
                    }
                    return {
                        "status": "rejected",
                        "reason": reason,
                        "message": messages.get(reason, "Güvenlik için hareket etmiyorum."),
                    }

            speed = float(args.get("speed", 0.2))
            # ... mevcut speed/duration clamp ve Twist yayınlama kodu DEĞİŞMEDEN devam eder ...
```

- [ ] **Step 7: `.env.example`'a hareket arka ucu anahtarını ekle**

```bash
# --- Hareket arka ucu ---
# BOŞ bırakılırsa move_robot tool'u 'no_motion_backend' ile REDDEDER.
# Sebep: /cmd_vel'i gerçek robotta kimse dinlemiyor (serial_bridge /wheel_cmds
# bekliyor). base_bridge düğümü yazılana kadar (Spec #2) boş kalmalı —
# sessizce başarı dönüp tekerleğin dönmemesi kullanıcıya yalan söylemektir.
# Geçerli değerler: base_bridge | nav2 | sim
ASTRO_MOTION_BACKEND=''
```

- [ ] **Step 8: Testi çalıştır, geçtiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_move_robot_safety.py -v
```

Beklenen: tüm testler PASS.

- [ ] **Step 9: Commit**

```bash
git add ros2_ws/src/astro_base/src/serial_bridge.py \
        ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py \
        ros2_ws/src/astro_ai/test/test_move_robot_safety.py .env.example
git commit -m "fix(safety): move_robot motor sağlığı kanıtlanmadan hareket etmiyor

serial_bridge artık serial_connected/handshake/heartbeat_healthy/
motor_enabled yayınlıyor ve Arduino sussa bile 0.5 s'de bir sağlık
basıyor. base_bridge yokken tool no_motion_backend ile açıkça
reddediyor — sessizce success dönmüyor."
```

---

## Task 9: Launch — `voice_engine` bağlamını tamamla ve test et

`bab0512` cascaded node'ları `voice_engine`'e bağladı, ama `realtime_sensors` include'ı hâlâ yalnızca `use_realtime`'a bakıyor. `voice_engine:=cascaded use_realtime:=true` denirse her iki hat da açılır.

**Files:**
- Modify: `ros2_ws/src/astro_bringup/launch/bringup.launch.py`
- Test: `ros2_ws/src/astro_ai/test/test_launch_voice_engine.py`

**Interfaces:**
- Consumes: hiçbir şey
- Produces: `bringup.launch.py`'de `is_realtime` koşulu hem cascaded node'ları kapatır hem `realtime_sensors` include'ını yönetir.

- [ ] **Step 1: Başarısız testi yaz**

`ros2_ws/src/astro_ai/test/test_launch_voice_engine.py`:

```python
#!/usr/bin/env python3
"""ASTRO V1 — voice_engine launch ayrımı testleri.

Kapı 1'in ses sahipliği kanıtı: realtime modunda donanıma dokunan eski
düğümlerin hiç başlatılmadığını launch açıklamasından doğrular.
"""

import os
import unittest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BRINGUP = os.path.join(SRC, "astro_bringup", "launch", "bringup.launch.py")

FORBIDDEN_IN_REALTIME = (
    "audio_capture_node",
    "speech_recognition_node",
    "tts_node",
    "ai_brain_node",
)


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestVoiceEngineArgument(unittest.TestCase):
    def setUp(self):
        self.src = read(BRINGUP)

    def test_voice_engine_argument_declared(self):
        self.assertIn('"voice_engine"', self.src)

    def test_default_is_realtime(self):
        idx = self.src.index('"voice_engine"')
        window = self.src[idx: idx + 400]
        self.assertIn('default_value="realtime"', window)

    def test_cascaded_audio_gated_on_realtime(self):
        self.assertIn("is_cascaded_audio", self.src)
        self.assertIn('"enable_audio": is_cascaded_audio', self.src)

    def test_cascaded_ai_gated_on_realtime(self):
        self.assertIn("is_cascaded_ai", self.src)
        self.assertIn('"enable_ai": is_cascaded_ai', self.src)

    def test_realtime_sensors_gated_on_voice_engine(self):
        """realtime_sensors yalnızca use_realtime'a değil, voice_engine'e de bağlı olmalı."""
        self.assertIn("realtime_sensors.launch.py", self.src)
        idx = self.src.index("realtime_sensors.launch.py")
        window = self.src[idx: idx + 400]
        self.assertIn("is_realtime", window)


class TestRealtimeLaunchComposition(unittest.TestCase):
    """realtime_sensors yalnızca tek ses sahibini ve realtime düğümünü başlatır."""

    def setUp(self):
        self.src = read(
            os.path.join(SRC, "astro_bringup", "launch", "realtime_sensors.launch.py")
        )

    def test_starts_audio_stream_node(self):
        self.assertIn('executable="audio_stream_node"', self.src)

    def test_starts_realtime_node(self):
        self.assertIn('executable="astro_realtime_node"', self.src)

    def test_starts_no_legacy_audio_nodes(self):
        for name in FORBIDDEN_IN_REALTIME:
            self.assertNotIn(f'executable="{name}"', self.src)


class TestAudioLaunchIsCascadedOnly(unittest.TestCase):
    """audio.launch.py yalnızca cascaded modda include edilir; içeriği değişmez."""

    def test_audio_launch_still_defines_cascaded_nodes(self):
        src = read(os.path.join(SRC, "astro_audio", "launch", "audio.launch.py"))
        self.assertIn('executable="audio_capture_node"', src)
        self.assertIn('executable="speech_recognition_node"', src)
        self.assertIn('executable="tts_node"', src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_launch_voice_engine.py -v
```

Beklenen: `test_realtime_sensors_gated_on_voice_engine` FAIL, diğerleri PASS.

- [ ] **Step 3: `realtime_sensors` include'ını `is_realtime`'a bağla**

`bringup.launch.py` sonundaki include'u şununla değiştir:

```python
            # OpenAI Realtime WebSocket Node — yalnızca voice_engine=realtime iken.
            # use_realtime tek başına yetmez: voice_engine:=cascaded use_realtime:=true
            # denirse her iki ses hattı birden açılır ve donanım çakışır.
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(bringup_pkg, "launch", "realtime_sensors.launch.py")
                ),
                condition=IfCondition(is_realtime),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_ai/test/test_launch_voice_engine.py -v
```

Beklenen: tüm testler PASS.

- [ ] **Step 5: Launch dosyasının sözdizimsel olarak geçerli olduğunu doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('bl', 'ros2_ws/src/astro_bringup/launch/bringup.launch.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
ld = mod.generate_launch_description()
print('launch entities:', len(ld.entities))
"
```

Beklenen: hata yok, entity sayısı basılır.

- [ ] **Step 6: Commit**

```bash
git add ros2_ws/src/astro_bringup/launch/bringup.launch.py \
        ros2_ws/src/astro_ai/test/test_launch_voice_engine.py
git commit -m "fix(launch): realtime_sensors'ı voice_engine'e bağla

voice_engine:=cascaded use_realtime:=true her iki ses hattını birden
açıyordu; artık tek hat açılıyor."
```

---

## Task 10: Ses sahipliği telemetrisi + Kapı 2 kabul betiği

**Files:**
- Modify: `ros2_ws/src/astro_audio/astro_audio/audio_stream_node.py` (`__init__` sonu)
- Create: `scripts/acceptance_p0.sh`
- Modify: `README.md` (Realtime mode bölümü)

**Interfaces:**
- Consumes: Task 1-9'un tamamı
- Produces: `[AUDIO OWNERSHIP]` log bloğu; `scripts/acceptance_p0.sh` PASS/FAIL tablosu

- [ ] **Step 1: `audio_stream_node`'a sahiplik telemetrisi ekle**

`audio_stream_node.py` `__init__` sonunda, `self.create_timer(0.1, self._publish_status)`
satırının hemen öncesine ekle:

```python
        # Kapı 2 kabul kriterinin kanıtı: bu düğüm hem girişin hem çıkışın
        # tek sahibidir. Log'da iki satır da görünmüyorsa sahiplik bozulmuştur.
        self.get_logger().info(
            f"[AUDIO OWNERSHIP]\n"
            f"audio_input_owner=audio_stream_node\n"
            f"audio_output_owner=audio_stream_node\n"
            f"input_device=[{self._in_dev_idx}] {self._in_device_name}\n"
            f"output_device=[{self._out_dev_idx}] {self._out_device_name}"
        )
```

- [ ] **Step 2: Kabul betiğini yaz**

`scripts/acceptance_p0.sh`:

```bash
#!/usr/bin/env bash
# ASTRO V1 — Spec #1 (Realtime S2S Ses Çekirdeği) Kapı 2 kabul betiği.
#
# Kullanım:
#   1) Robotu başlat ve log'u dosyaya yaz:
#        ros2 launch astro_bringup bringup.launch.py 2>&1 | tee /tmp/astro_run.log
#   2) Bir tur konuş, robotun sözünü kes (barge-in), "ne görüyorsun" diye sor,
#      bir bilgi kaydettir, "ileri git" de.
#   3) Bu betiği çalıştır:
#        ./scripts/acceptance_p0.sh /tmp/astro_run.log
set -uo pipefail

LOG="${1:-/tmp/astro_run.log}"
if [[ ! -f "$LOG" ]]; then
  echo "Log dosyası bulunamadı: $LOG" >&2
  exit 2
fi

PASS=0
FAIL=0

check() {  # check <etiket> <grep-deseni>
  local label="$1" pattern="$2"
  if grep -qE -- "$pattern" "$LOG"; then
    printf '  \033[32mPASS\033[0m  %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  \033[31mFAIL\033[0m  %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

absent() {  # absent <etiket> <grep-deseni>
  local label="$1" pattern="$2"
  local n
  n=$(grep -cE -- "$pattern" "$LOG" || true)
  if [[ "$n" -eq 0 ]]; then
    printf '  \033[32mPASS\033[0m  %s (0 kez)\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  \033[31mFAIL\033[0m  %s (%s kez)\n' "$label" "$n"
    FAIL=$((FAIL + 1))
  fi
}

echo "AUDIO OWNERSHIP"
check "audio_input_owner=audio_stream_node"  "audio_input_owner=audio_stream_node"
check "audio_output_owner=audio_stream_node" "audio_output_owner=audio_stream_node"

echo "REALTIME"
check "session CONNECTED" "REALTIME (SESSION READY|CONNECTING)"
check "VAD yapılandırıldı" "\[REALTIME VAD\]"
check "interrupt_response=True" "interrupt_response=True"
check "create_response=True"    "create_response=True"

echo "TURN"
check "speech_started"   "speech_started|Kullanıcı konuşmaya başladı"
check "speech_stopped"   "Cümle bitti"
check "response_created" "\[REALTIME RESPONSE CREATED\]"
check "audio_done"       "\[REALTIME AUDIO DONE\]"
check "response_done"    "\[REALTIME AUDIO SUMMARY\]"

echo "PLAYBACK"
check "first_audio_ms ölçüldü" "first_audio_ms=[0-9]"
if grep -qE "first_audio_ms=[0-9]" "$LOG"; then
  echo "        first_audio_ms değerleri:"
  grep -oE "first_audio_ms=[0-9.]+" "$LOG" | sed 's/^/          /'
fi

echo "BARGE-IN"
check "barge-in algılandı" "Barge-In|Akustik Yankı Koruması"

echo "MOTION"
check "serial_connected"   "\[SERIAL CONNECTED\]|serial_connected=True"
check "handshake success"  "\[ARDUINO HANDSHAKE\] status=success"
check "heartbeat ACK"      "\[HEARTBEAT ACK\]"
echo "  NOT: base_bridge yazılana kadar (Spec #2) move_robot'un"
echo "       'no_motion_backend' ile REDDETMESİ BEKLENEN davranıştır."

echo "VISION"
check "kamera tool çağrısı" "inspect_camera_view"

echo "MEMORY"
check "hafıza tool çağrısı" "save_user_memory|search_memory"

echo "NO ERRORS"
absent "Device busy"                            "Device or resource busy"
absent "write to closed file"                   "write to closed file"
absent "conversation_already_has_active_response" "conversation_already_has_active_response"
absent "response_cancel_not_active"             "response_cancel_not_active"

echo
echo "================================"
printf 'PASS: %s   FAIL: %s\n' "$PASS" "$FAIL"
echo "================================"
[[ "$FAIL" -eq 0 ]] || exit 1
```

- [ ] **Step 3: Betiği çalıştırılabilir yap ve sözdizimini doğrula**

```bash
chmod +x scripts/acceptance_p0.sh
bash -n scripts/acceptance_p0.sh && echo "sözdizimi OK"
printf 'audio_input_owner=audio_stream_node\naudio_output_owner=audio_stream_node\n' > /tmp/astro_fake.log
./scripts/acceptance_p0.sh /tmp/astro_fake.log; echo "çıkış kodu: $?"
```

Beklenen: sözdizimi OK; ilk iki satır PASS, geri kalanı FAIL; çıkış kodu 1.

- [ ] **Step 4: `README.md`'yi güncelle**

`## 🎙️ Realtime mode (OpenAI speech-to-speech)` bölümünün altına ekle:

```markdown
### Voice engine selection

The robot has one audio hardware owner: `audio_stream_node`. Which brain sits
behind it is chosen with `voice_engine`:

```bash
# Pure speech-to-speech (default). audio_capture_node, speech_recognition_node,
# tts_node and ai_brain_node are NOT started.
ros2 launch astro_bringup bringup.launch.py voice_engine:=realtime

# Classic cascaded pipeline (Whisper -> LLM -> Edge-TTS).
ros2 launch astro_bringup bringup.launch.py voice_engine:=cascaded
```

Turn taking and barge-in belong to the OpenAI server VAD
(`create_response` + `interrupt_response`). Tune it in `.env` via
`REALTIME_VAD_TYPE`, `REALTIME_VAD_SILENCE_MS` and `REALTIME_VAD_EAGERNESS`.
The client never sends `response.create` on `speech_stopped`.

### Acceptance run

```bash
ros2 launch astro_bringup bringup.launch.py 2>&1 | tee /tmp/astro_run.log
# talk, interrupt it mid-sentence, ask what it sees, tell it a fact, ask it to move
./scripts/acceptance_p0.sh /tmp/astro_run.log
```
```

- [ ] **Step 5: Tam suite'i son kez çalıştır**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest -q 2>&1 | tail -10
```

Beklenen: **tam olarak 2 fail** — `test_21_migration_from_legacy_json` ve
`test_xtts_client_batch_size_default_is_one`. Başka fail varsa Kapı 1 kapanmamıştır.

- [ ] **Step 6: Workspace'in derlendiğini doğrula**

```bash
source /opt/ros/humble/setup.bash && cd ros2_ws && \
colcon build --packages-select astro_ai astro_audio astro_base astro_bringup 2>&1 | tail -15
```

Beklenen: `Summary: 4 packages finished` — hata yok.

- [ ] **Step 7: Commit**

```bash
git add ros2_ws/src/astro_audio/astro_audio/audio_stream_node.py \
        scripts/acceptance_p0.sh README.md
git commit -m "feat(audio): ses sahipliği telemetrisi + Kapı 2 kabul betiği"
```

---

## Task 11: Gerçek donanım tek-sahip testi (opt-in)

Mock'lu testler "Device busy" sınıfı hataları gösteremez — tam da şu an
yaşanan problem bu. Bu test geliştirme laptop'unun dahili ses kartını (ALC294)
kullanarak iki sürecin aynı cihazı açmasının gerçekten engellendiğini kanıtlar.

Varsayılan olarak **atlanır**: CI'da ve ses donanımı olmayan makinelerde
`ASTRO_HW_AUDIO_TEST=1` verilmedikçe çalışmaz.

**Files:**
- Create: `ros2_ws/src/astro_audio/test/test_hw_audio_ownership.py`

**Interfaces:**
- Consumes: Task 5'in tek playback sahibi değişikliği
- Produces: hiçbir şey (yalnızca doğrulama)

- [ ] **Step 1: Testi yaz**

`ros2_ws/src/astro_audio/test/test_hw_audio_ownership.py`:

```python
#!/usr/bin/env python3
"""ASTRO V1 — Gerçek ses donanımıyla tek sahiplik testi (opt-in).

ASTRO_HW_AUDIO_TEST=1 verilmedikçe atlanır. Mock'lu testler
"Device or resource busy" sınıfı hataları gösteremez; bu test gerçek bir
PortAudio akışı açarak ikinci sahibin engellendiğini kanıtlar.

Çalıştırma:
    ASTRO_HW_AUDIO_TEST=1 .venv/bin/python -m pytest \
        ros2_ws/src/astro_audio/test/test_hw_audio_ownership.py -v -s
"""

import os
import unittest

HW = os.getenv("ASTRO_HW_AUDIO_TEST", "").strip() == "1"


@unittest.skipUnless(HW, "ASTRO_HW_AUDIO_TEST=1 gerekli (gerçek ses donanımı)")
class TestRealHardwareSingleOwner(unittest.TestCase):
    def setUp(self):
        import sounddevice as sd
        self.sd = sd

    def test_default_input_device_exists(self):
        devices = self.sd.query_devices()
        inputs = [d for d in devices if d["max_input_channels"] > 0]
        self.assertGreater(len(inputs), 0, "Hiç giriş cihazı yok")
        print(f"\n  giriş cihazları: {[d['name'] for d in inputs]}")

    def test_exclusive_input_stream_blocks_second_opener(self):
        """Aynı cihazı exclusive açan ikinci akış başarısız olmalı veya paylaşmalı.

        Bu test her iki sonucu da kabul eder ama hangisinin gerçekleştiğini
        yazdırır: ALSA dmix paylaşıma izin verebilir. Önemli olan, ASTRO'nun
        tek sahip tasarımının bu belirsizliğe HİÇ girmemesi.
        """
        first = self.sd.RawInputStream(
            samplerate=16000, blocksize=320, channels=1, dtype="int16"
        )
        first.start()
        try:
            shared = True
            try:
                second = self.sd.RawInputStream(
                    samplerate=16000, blocksize=320, channels=1, dtype="int16"
                )
                second.start()
                second.stop()
                second.close()
            except Exception as exc:
                shared = False
                print(f"\n  ikinci açış REDDEDİLDİ: {exc}")
            if shared:
                print("\n  ikinci açış PAYLAŞILDI (ALSA dmix) — "
                      "tek sahip tasarımı bu belirsizliği ortadan kaldırır")
        finally:
            first.stop()
            first.close()

    def test_audio_stream_node_opens_input_without_error(self):
        """AudioStreamNode gerçek donanımda giriş akışını açabilmeli."""
        import astro_audio.audio_stream_node as asn
        from astro_audio.audio_stream_node import AudioStreamNode

        node = AudioStreamNode.__new__(AudioStreamNode)
        node._in_dev_idx, node._in_device_name = asn.find_audio_device(is_input=True)
        node._input_stream = None
        node._input_stream_alive = False

        logs = []
        class _L:
            info = warn = error = staticmethod(lambda m: logs.append(m))
        node.get_logger = lambda: _L()
        node.create_subscription = lambda *a, **k: None

        # _under_pytest() koruması gerçek donanıma dokunmayı engelliyor;
        # bu test bilerek donanım istiyor, o yüzden geçici olarak devre dışı.
        original = AudioStreamNode._under_pytest
        AudioStreamNode._under_pytest = staticmethod(lambda: False)
        try:
            node._start_input_stream()
        finally:
            AudioStreamNode._under_pytest = original
            if node._input_stream is not None:
                try:
                    node._input_stream.stop()
                    node._input_stream.close()
                except Exception:
                    pass

        log_text = "\n".join(logs)
        print(f"\n  cihaz: [{node._in_dev_idx}] {node._in_device_name}")
        self.assertNotIn("Device or resource busy", log_text)
        self.assertTrue(
            node._input_stream_alive,
            f"Giriş akışı açılamadı:\n{log_text}",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Varsayılan olarak atlandığını doğrula**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
.venv/bin/python -m pytest ros2_ws/src/astro_audio/test/test_hw_audio_ownership.py -v
```

Beklenen: 3 test de `SKIPPED`. Tam suite'in fail sayısını değiştirmez.

- [ ] **Step 3: Gerçek donanımla çalıştır**

```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
ASTRO_HW_AUDIO_TEST=1 .venv/bin/python -m pytest \
  ros2_ws/src/astro_audio/test/test_hw_audio_ownership.py -v -s
```

Beklenen: 3 test de PASS; çıktıda cihaz adı ve ikinci açışın reddedilip
reddedilmediği görünür.

> Bu makinede yalnızca `card 0: PCH [HDA Intel PCH] ALC294 Analog` var. Jetson'da
> aynı test ReSpeaker ile koşulduğunda cihaz adı farklı olacaktır — test cihaz
> adına değil, akışın açılabilmesine bakar.

- [ ] **Step 4: Commit**

```bash
git add ros2_ws/src/astro_audio/test/test_hw_audio_ownership.py
git commit -m "test(audio): gerçek donanımla tek sahiplik testi (opt-in)"
```

---

## Kapı 1 kapanış kontrol listesi

Tüm task'lar bittiğinde şunların hepsi doğrulanmış olmalı:

- [ ] `pytest` → tam olarak 2 fail (ikisi de kapsam dışı bilinen sorun), 3 skip (Task 11)
- [ ] `ASTRO_HW_AUDIO_TEST=1 pytest .../test_hw_audio_ownership.py` → 3 PASS
- [ ] `colcon build` → 4 paket hatasız
- [ ] `grep -rn "/tts/realtime_request" ros2_ws/src --include="*.py" | grep -v test` → çıktı yok
- [ ] `grep -rn "realtime_output_pcm" ros2_ws/src/astro_audio/astro_audio/tts_node.py` → yalnızca açıklama satırı
- [ ] `./scripts/acceptance_p0.sh` sahte log ile çalışıyor, çıkış kodu doğru

## Kapı 2 (Jetson — kullanıcı çalıştırır)

- [ ] `ros2 launch astro_bringup bringup.launch.py 2>&1 | tee /tmp/astro_run.log`
- [ ] Bir tur konuş, sözünü kes, "ne görüyorsun" sor, bilgi kaydettir, "ileri git" de
- [ ] `./scripts/acceptance_p0.sh /tmp/astro_run.log`
- [ ] VAD benchmark'ı: `REALTIME_VAD_SILENCE_MS` 400/500/600 ve
      `REALTIME_VAD_TYPE=semantic_vad` — her biri için `first_audio_ms` p50/p95
      topla, kazananı `.env`'e yaz
