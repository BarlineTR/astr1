#!/usr/bin/env python3
"""ASTRO V1 — AI Brain Node.

Manages the wake-word state machine and LLM interaction:
  IDLE   → listens passively, only activates on wake word
  ACTIVE → forwards user speech to LLM (or local echo), resets timeout on each interaction
"""
import os
import asyncio
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import re


class AiBrainNode(Node):
    def __init__(self):
        super().__init__("ai_brain_node")

        # Load .env
        if load_dotenv is not None:
            load_dotenv(os.path.join(os.getcwd(), ".env"))

        # ── AI Mode ──────────────────────────────────────────────
        self.ai_mode = os.getenv("AI_MODE", "local").lower().strip()

        # ── Wake Word & State Machine ────────────────────────────
        self.wake_word = os.getenv("WAKE_WORD", "hey astro").lower().strip()
        self.conv_timeout = float(os.getenv("CONVERSATION_TIMEOUT", "15"))
        self._state = "IDLE"  # "IDLE" or "ACTIVE"
        self._last_interaction = 0.0  # monotonic timestamp

        # ── LLM Client ──────────────────────────────────────────
        self.api_key = os.getenv("AI_API_KEY")
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model_name = os.getenv("AI_MODEL", "gpt-4o")
        self.client = None

        if self.ai_mode == "api":
            if not self.api_key:
                self.get_logger().error(
                    "❌ [AI] AI_MODE=api ama AI_API_KEY bulunamadı! .env'yi kontrol edin."
                )
                self.get_logger().warn("⚠️  [AI] Yerel moda düşürüldü.")
                self.ai_mode = "local"
            else:
                from openai import AsyncOpenAI

                self.client = AsyncOpenAI(
                    api_key=self.api_key, base_url=self.base_url
                )
                self.get_logger().info(
                    f"✅ [AI] API Modu Aktif — Model: {self.model_name}"
                )

        if self.ai_mode == "local":
            self.get_logger().info(
                "✅ [AI] Yerel Mod Aktif — API çağrısı yapılmayacak."
            )

        self.get_logger().info(
            f"🎯 [AI] Wake word: \"{self.wake_word}\"  "
            f"| Sohbet süresi: {self.conv_timeout}s"
        )

        # ── System prompt ────────────────────────────────────────
        self.system_prompt = (
            "Sen Astro adında cana yakın, yardımsever ve çok akıllı bir robot asistansın. "
            "Kullanıcıya kısa, net ve konuşma diline uygun şekilde Türkçe cevap vermelisin. "
            "Cevaplarını 2-3 cümleyi geçmeyecek şekilde kısa tut çünkü sesli olarak okunacaklar. "
            "Emoji veya özel karakter kullanma."
        )

        self.conversation_history = [
            {"role": "system", "content": self.system_prompt}
        ]
        self.max_history = 20  # system + 9 turn pairs

        # ── Processing queue ─────────────────────────────────────
        self.pending_user_text = ""
        self.is_processing = False
        self._lock = threading.Lock()

        # ── TTS mute awareness ───────────────────────────────────
        self._tts_speaking = False

        # ── ROS interfaces ───────────────────────────────────────
        self.pub_tts = self.create_publisher(String, "/tts/say", 10)
        self.sub_speech = self.create_subscription(
            String, "/speech/text", self._on_speech, 10
        )
        self.sub_tts_speaking = self.create_subscription(
            Bool, "/tts/speaking", self._on_tts_speaking, 10
        )

        # ── Async event loop (API mode only) ─────────────────────
        if self.ai_mode == "api":
            self._ai_loop = asyncio.new_event_loop()
            self._ai_thread = threading.Thread(
                target=self._run_async_loop, daemon=True
            )
            self._ai_thread.start()

    def _run_async_loop(self):
        asyncio.set_event_loop(self._ai_loop)
        self._ai_loop.run_forever()

    # ------------------------------------------------------------------
    # TTS mute callback — ignore our own voice
    # ------------------------------------------------------------------
    def _on_tts_speaking(self, msg: Bool):
        self._tts_speaking = msg.data

    # ------------------------------------------------------------------
    # Main speech callback — wake word state machine
    # ------------------------------------------------------------------
    def _on_speech(self, msg: String):
        user_text = msg.data.strip()
        if not user_text:
            return

        # Ignore input while robot is speaking (echo prevention)
        if self._tts_speaking:
            return

        text_lower = user_text.lower()
        now = time.monotonic()

        # ── Timeout check ────────────────────────────────────────
        if self._state == "ACTIVE":
            if (now - self._last_interaction) > self.conv_timeout:
                self._state = "IDLE"
                self.get_logger().info(
                    "💤 [AI] Sohbet zaman aşımı — uyku moduna dönüldü."
                )

        # ── IDLE: only react to wake word ────────────────────────
        if self._state == "IDLE":
            idx = text_lower.find(self.wake_word)
            if idx == -1:
                # Not for us — silently ignore
                return

            self._state = "ACTIVE"
            self._last_interaction = now
            self.get_logger().info(
                f"✨ [AI] Wake word algılandı! ACTIVE moda geçildi."
            )

            # Extract the part after the wake word
            clean_text = user_text[idx + len(self.wake_word) :].strip()

            if not clean_text:
                # Just said "hey astro" with nothing after
                self._publish_tts("Efendim?")
                return
            else:
                user_text = clean_text

        # ── ACTIVE: process the command ──────────────────────────
        self._last_interaction = now

        if self.ai_mode == "local":
            self.get_logger().info(f'🎤 [Yerel] Duyulan: "{user_text}"')
            self._publish_tts(f"{user_text} — anladım.")
            return

        # API mode — queue for LLM
        with self._lock:
            if self.pending_user_text:
                self.pending_user_text += " " + user_text
            else:
                self.pending_user_text = user_text

            if not self.is_processing:
                if self.client:
                    self.is_processing = True
                    asyncio.run_coroutine_threadsafe(
                        self._process_queue(), self._ai_loop
                    )
                else:
                    self.get_logger().error(
                        "API Key eksik, LLM çağrısı yapılamadı."
                    )

    # ------------------------------------------------------------------
    # Helper — publish to TTS
    # ------------------------------------------------------------------
    def _publish_tts(self, text: str):
        msg = String()
        msg.data = text
        self.pub_tts.publish(msg)

    # ------------------------------------------------------------------
    # LLM processing loop
    # ------------------------------------------------------------------
    async def _process_queue(self):
        while True:
            with self._lock:
                if not self.pending_user_text:
                    self.is_processing = False
                    break
                current_text = self.pending_user_text
                self.pending_user_text = ""

            self.get_logger().info(f"🚀 [AI] API'ye gönderiliyor: {current_text}")
            self.conversation_history.append(
                {"role": "user", "content": current_text}
            )

            # Keep history bounded
            if len(self.conversation_history) > self.max_history:
                self.conversation_history = (
                    [self.conversation_history[0]]
                    + self.conversation_history[-(self.max_history - 1) :]
                )

            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=self.conversation_history,
                    temperature=0.7,
                    max_tokens=256,
                )

                ai_text = response.choices[0].message.content.strip()
                self.get_logger().info(f"🧠 [AI] Cevap: {ai_text}")

                self.conversation_history.append(
                    {"role": "assistant", "content": ai_text}
                )

                # Split into sentences and send to TTS
                sentences = re.split(r"(?<=[.!?])\s+", ai_text)
                for sentence in sentences:
                    s = sentence.strip()
                    if s:
                        self._publish_tts(s)

                # Update interaction time after AI responds
                self._last_interaction = time.monotonic()

            except Exception as e:
                self.get_logger().error(
                    f"❌ [AI] API Hatası: {e}"
                )
                await asyncio.sleep(2)


def main():
    rclpy.init()
    node = AiBrainNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
