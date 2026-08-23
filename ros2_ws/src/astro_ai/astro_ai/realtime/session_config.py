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
