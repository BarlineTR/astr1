#!/usr/bin/env python3
"""ASTRO V1 — Dedicated Live OpenAI Realtime Smoke Test.

IMPORTANT CONTRACT:
- This file is EXCLUDED from standard offline test runs and continuous integration.
- It will ONLY execute when the environment variable ASTRO_LIVE_API_TEST=1 is explicitly set
  and a valid OPENAI_API_KEY is present in the environment.
- Standard unit/acceptance tests MUST NEVER import or invoke this live test.
"""

import os
import unittest

LIVE_TEST_FLAG = os.environ.get("ASTRO_LIVE_API_TEST", "0") in ("1", "true", "True")
REALTIME_MODEL = os.environ.get("REALTIME_MODEL", "gpt-realtime-2.1-mini")


@unittest.skipUnless(
    LIVE_TEST_FLAG and bool(os.environ.get("OPENAI_API_KEY", "").strip()) and not os.environ.get("OPENAI_API_KEY", "").startswith("sk-test"),
    "Live OpenAI Realtime smoke test skipped. Explicit opt-in required: ASTRO_LIVE_API_TEST=1 with valid OPENAI_API_KEY."
)
class TestRealtimeLiveSmoke(unittest.TestCase):
    """Opt-in live smoke test verifying real WebSocket handshake against OpenAI Realtime API."""

    def test_live_websocket_connection_and_handshake(self):
        """Validates real WebSocket connectivity with gpt-realtime-2.1-mini when opt-in is enabled."""
        import asyncio
        import websockets
        import json

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        ws_url = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

        async def _run_smoke():
            async with websockets.connect(ws_url, extra_headers=headers, open_timeout=5.0) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)
                return data.get("type") == "session.created"

        success = asyncio.run(_run_smoke())
        self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
