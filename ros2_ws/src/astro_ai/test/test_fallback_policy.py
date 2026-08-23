#!/usr/bin/env python3
"""ASTRO V1 — Realtime başarısızlık sınıflandırması ve kurtarma katmanı testleri."""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))

from astro_ai.realtime.fallback_policy import (
    FailureKind,
    RecoveryTier,
    choose_recovery,
    classify_error_event,
    classify_response_done,
    should_enter_fallback_mode,
)


class TestClassifyErrorEvent(unittest.TestCase):
    def test_rate_limit_by_code(self):
        kind = classify_error_event({"code": "rate_limit_exceeded", "type": "requests", "message": ""})
        self.assertEqual(kind, FailureKind.RATE_LIMIT)

    def test_rate_limit_by_message(self):
        kind = classify_error_event({
            "code": "none", "type": "requests",
            "message": "Rate limit reached for gpt-realtime-2.1-mini ... (RPD): Limit 1000, Used 1000",
        })
        self.assertEqual(kind, FailureKind.RATE_LIMIT)

    def test_quota_exhausted(self):
        kind = classify_error_event({"code": "insufficient_quota", "type": "billing", "message": ""})
        self.assertEqual(kind, FailureKind.QUOTA)

    def test_cancel_not_active_is_benign(self):
        kind = classify_error_event({
            "code": "response_cancel_not_active", "type": "invalid_request_error", "message": "",
        })
        self.assertEqual(kind, FailureKind.BENIGN)

    def test_unknown_error_is_server_error(self):
        kind = classify_error_event({"code": "boom", "type": "server_error", "message": "kaboom"})
        self.assertEqual(kind, FailureKind.SERVER_ERROR)

    def test_empty_event_is_unknown(self):
        self.assertEqual(classify_error_event({}), FailureKind.SERVER_ERROR)


class TestClassifyResponseDone(unittest.TestCase):
    """response.done, yanıtın NEDEN bittiğini status/status_details'te taşır.

    Bu alanlar okunmazsa 'ses gelmedi' deyip sebebini asla bilemeyiz.
    """

    def test_completed_with_audio_is_ok(self):
        kind = classify_response_done({"status": "completed"}, audio_received=True)
        self.assertEqual(kind, FailureKind.NONE)

    def test_completed_without_audio_is_silent_response(self):
        kind = classify_response_done({"status": "completed"}, audio_received=False)
        self.assertEqual(kind, FailureKind.SILENT_RESPONSE)

    def test_failed_with_rate_limit_detail(self):
        resp = {
            "status": "failed",
            "status_details": {
                "type": "failed",
                "error": {"code": "rate_limit_exceeded", "message": "Rate limit reached"},
            },
        }
        self.assertEqual(classify_response_done(resp, audio_received=False), FailureKind.RATE_LIMIT)

    def test_failed_without_detail_is_server_error(self):
        resp = {"status": "failed", "status_details": {"type": "failed"}}
        self.assertEqual(classify_response_done(resp, audio_received=False), FailureKind.SERVER_ERROR)

    def test_cancelled_is_benign(self):
        """Barge-in ile iptal edilen yanıt hata değildir — kurtarma tetiklenmemeli."""
        resp = {"status": "cancelled", "status_details": {"type": "cancelled", "reason": "turn_detected"}}
        self.assertEqual(classify_response_done(resp, audio_received=False), FailureKind.BENIGN)

    def test_incomplete_with_audio_is_ok(self):
        resp = {"status": "incomplete", "status_details": {"reason": "max_output_tokens"}}
        self.assertEqual(classify_response_done(resp, audio_received=True), FailureKind.NONE)

    def test_incomplete_without_audio_is_silent(self):
        resp = {"status": "incomplete", "status_details": {"reason": "content_filter"}}
        self.assertEqual(classify_response_done(resp, audio_received=False), FailureKind.SILENT_RESPONSE)

    def test_missing_status_falls_back_to_audio_evidence(self):
        self.assertEqual(classify_response_done({}, audio_received=True), FailureKind.NONE)
        self.assertEqual(classify_response_done({}, audio_received=False), FailureKind.SILENT_RESPONSE)


class TestShouldEnterFallbackMode(unittest.TestCase):
    """Kalıcı engeller fallback moduna geçirir; geçici olanlar geçirmez."""

    def test_rate_limit_enters_fallback(self):
        self.assertTrue(should_enter_fallback_mode(FailureKind.RATE_LIMIT))

    def test_quota_enters_fallback(self):
        self.assertTrue(should_enter_fallback_mode(FailureKind.QUOTA))

    def test_silent_response_does_not_enter_fallback(self):
        """Tek bir sessiz yanıt bağlantıyı terk etmek için sebep değil."""
        self.assertFalse(should_enter_fallback_mode(FailureKind.SILENT_RESPONSE))

    def test_benign_does_not_enter_fallback(self):
        self.assertFalse(should_enter_fallback_mode(FailureKind.BENIGN))

    def test_server_error_does_not_enter_fallback(self):
        self.assertFalse(should_enter_fallback_mode(FailureKind.SERVER_ERROR))


class TestChooseRecovery(unittest.TestCase):
    def test_assistant_text_is_spoken_directly(self):
        """En iyi durum: model ne diyeceğini yazdı, sesi gelmedi. Aynen seslendir."""
        tier = choose_recovery(assistant_text="Merhaba Baran.", user_transcript="selam")
        self.assertEqual(tier, RecoveryTier.SPEAK_ASSISTANT_TEXT)

    def test_user_transcript_drives_local_answer(self):
        tier = choose_recovery(assistant_text="", user_transcript="nasılsın")
        self.assertEqual(tier, RecoveryTier.ANSWER_USER_TEXT)

    def test_nothing_known_waits(self):
        """Kullanıcı metni response.done'dan SONRA gelebiliyor — hemen pes etme."""
        tier = choose_recovery(assistant_text="", user_transcript="")
        self.assertEqual(tier, RecoveryTier.WAIT_FOR_TRANSCRIPT)

    def test_whitespace_is_not_text(self):
        self.assertEqual(
            choose_recovery(assistant_text="   ", user_transcript="  \n "),
            RecoveryTier.WAIT_FOR_TRANSCRIPT,
        )

    def test_benign_failure_needs_no_recovery(self):
        tier = choose_recovery(assistant_text="", user_transcript="", kind=FailureKind.BENIGN)
        self.assertEqual(tier, RecoveryTier.NONE)

    def test_no_failure_needs_no_recovery(self):
        tier = choose_recovery(assistant_text="x", user_transcript="y", kind=FailureKind.NONE)
        self.assertEqual(tier, RecoveryTier.NONE)

    def test_assistant_text_wins_over_user_transcript(self):
        tier = choose_recovery(assistant_text="cevap", user_transcript="soru")
        self.assertEqual(tier, RecoveryTier.SPEAK_ASSISTANT_TEXT)


if __name__ == "__main__":
    unittest.main()
