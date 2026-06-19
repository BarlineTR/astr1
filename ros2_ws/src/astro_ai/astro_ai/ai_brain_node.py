#!/usr/bin/env python3
import os
import asyncio
import threading
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from dotenv import load_dotenv
from openai import AsyncOpenAI
import re

class AiBrainNode(Node):
    def __init__(self):
        super().__init__('ai_brain_node')
        
        # Load environment variables from .env
        env_path = os.path.join(os.getcwd(), '.env')
        load_dotenv(env_path)
        
        self.api_key = os.getenv("AI_API_KEY")
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model_name = os.getenv("AI_MODEL", "gpt-4o")
        
        if not self.api_key:
            self.get_logger().error("AI_API_KEY bulunamadi! Lutfen .env dosyasini kontrol edin.")
            # Node'un calismasini durdurmayalim ama islem de yapmayacak
        else:
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            self.get_logger().info(f"✅ [AI] API Baglantisi Hazir. Model: {self.model_name}")

        self.system_prompt = (
            "Sen Astro adinda cana yakin, yardimsever ve cok akilli bir asistansin. "
            "Kullaniciya kisa, net ve konusma diline uygun sekilde Turkce cevap vermelisin. "
            "Bilgisayar kodlarindan cok, sohbet formatinda (gundelik dil) konusmalisin."
        )

        self.conversation_history = [
            {"role": "system", "content": self.system_prompt}
        ]
        self.max_history = 10 # Keep last 10 messages

        self.pub_tts = self.create_publisher(String, '/tts/say', 10)
        self.sub_speech = self.create_subscription(String, '/speech/text', self.speech_callback, 10)
        
        self.ai_loop = asyncio.new_event_loop()
        self.ai_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.ai_thread.start()

    def _run_async_loop(self):
        asyncio.set_event_loop(self.ai_loop)
        self.ai_loop.run_forever()

    def speech_callback(self, msg: String):
        user_text = msg.data.strip()
        if not user_text:
            return
            
        self.get_logger().info(f"🚀 [AI] API'ye gönderiliyor...")
        self.conversation_history.append({"role": "user", "content": user_text})
        
        # Keep history bounded
        if len(self.conversation_history) > self.max_history:
            # Keep system prompt at [0], and last N items
            self.conversation_history = [self.conversation_history[0]] + self.conversation_history[-(self.max_history-1):]

        if self.api_key:
            # Asenkron LLM cagrisini baslat
            asyncio.run_coroutine_threadsafe(self.process_ai_request(), self.ai_loop)
        else:
            self.get_logger().error("API Key eksik, LLM cagirisi yapilamadi.")

    async def process_ai_request(self):
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=self.conversation_history,
                temperature=0.7,
                max_tokens=256
            )
            
            ai_text = response.choices[0].message.content.strip()
            self.get_logger().info(f"🧠 [AI] Cevap: {ai_text}")
            
            # Kaydet
            self.conversation_history.append({"role": "assistant", "content": ai_text})
            
            # Cumle cumle ayirip TTS'e yolla (re modulu ile basitce ayiriyoruz, nltk scipy hatasini onlemek icin)
            sentences = re.split(r'(?<=[.!?]) +', ai_text)
            for sentence in sentences:
                if sentence.strip():
                    tts_msg = String()
                    tts_msg.data = sentence.strip()
                    self.pub_tts.publish(tts_msg)
                    
        except Exception as e:
            self.get_logger().error(f"❌ [AI] LLM API Baglanti Hatasi! Lutfen API Key'i ve interneti kontrol edin. Hata Detayi: {e}")

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

if __name__ == '__main__':
    main()
