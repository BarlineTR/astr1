#!/usr/bin/env python3
"""ASTRO V1 — Gerçek ses donanımıyla tek sahiplik testi (opt-in).

ASTRO_HW_AUDIO_TEST=1 verilmedikçe atlanır. Mock'lu testler
"Device or resource busy" sınıfı hataları gösteremez; bu test gerçek bir
PortAudio akışı açarak davranışı yerinde ölçer.

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

    def test_second_opener_behaviour_is_observed(self):
        """Aynı cihazı ikinci kez açmanın ne yaptığını KAYDEDER.

        ALSA dmix paylaşıma izin verebilir, donanım reddedebilir. Test her iki
        sonucu da kabul eder ama hangisinin gerçekleştiğini yazdırır. Asıl nokta:
        ASTRO'nun tek sahip tasarımı bu belirsizliğe hiç girmez.
        """
        first = self.sd.RawInputStream(
            samplerate=16000, blocksize=320, channels=1, dtype="int16"
        )
        first.start()
        try:
            try:
                second = self.sd.RawInputStream(
                    samplerate=16000, blocksize=320, channels=1, dtype="int16"
                )
                second.start()
                second.stop()
                second.close()
                print("\n  ikinci açış PAYLAŞILDI (ALSA dmix) — "
                      "tek sahip tasarımı bu belirsizliği ortadan kaldırır")
            except Exception as exc:
                print(f"\n  ikinci açış REDDEDİLDİ: {exc}")
        finally:
            first.stop()
            first.close()

    def test_audio_stream_node_opens_input_without_error(self):
        """AudioStreamNode gerçek donanımda giriş akışını açabilmeli."""
        from unittest.mock import MagicMock

        import astro_audio.audio_stream_node as asn
        from astro_audio.audio_stream_node import AudioStreamNode

        node = AudioStreamNode.__new__(AudioStreamNode)
        node._in_dev_idx, node._in_device_name = asn.find_audio_device(is_input=True)
        node._input_stream = None
        node._input_stream_alive = False

        logs = []
        mock_logger = MagicMock()
        mock_logger.info = lambda m: logs.append(m)
        mock_logger.warn = lambda m: logs.append(m)
        mock_logger.error = lambda m: logs.append(m)
        node.get_logger = lambda: mock_logger
        node.create_subscription = MagicMock()
        node._process_raw_audio_chunk = lambda raw: None

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
