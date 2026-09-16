"""Local STT must be selected in the same runtime used by wake and dialogue."""

import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.astro_realtime_node import AstroRealtimeNode, _load_env

sys.modules.setdefault("faster_whisper", MagicMock())


@pytest.fixture(autouse=True)
def restore_process_env():
    """os.environ'ı test sonrası aynen geri yükler.

    `_load_env()` load_dotenv(override=True) çağırdığı için profil dosyasındaki
    anahtarlar doğrudan os.environ'a yazılır; monkeypatch bunları takip etmez.
    Sızan STT_ENGINE=faster-whisper, sonraki testlerde `_transcribe_groq_whisper`
    yamasını devre dışı bırakıp tam suite koşusunda dört testi düşürüyordu.
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def bare_node():
    node = AstroRealtimeNode.__new__(AstroRealtimeNode)
    node._local_stt_lock = threading.Lock()
    node._local_stt_model = None
    node._safe_log = MagicMock()
    node._transcribe_openai = MagicMock(side_effect=AssertionError("cloud STT"))
    node._transcribe_groq_whisper = MagicMock(side_effect=AssertionError("cloud STT"))
    node._can_use_openai = MagicMock(return_value=False)
    return node


def test_runtime_local_whisper_transcribes_wav_and_reuses_model(monkeypatch):
    monkeypatch.setenv("STT_ENGINE", "faster-whisper")
    monkeypatch.setenv("STT_FW_MODEL", "small")
    monkeypatch.setenv("STT_FW_DEVICE", "cpu")
    node = bare_node()
    model = MagicMock()
    model.transcribe.side_effect = lambda *a, **k: (iter([SimpleNamespace(text=" Astro, merhaba.")]), None)
    with patch("faster_whisper.WhisperModel", return_value=model) as factory:
        assert node._transcribe_wav(b"wav input") == "Astro, merhaba."
        assert node._transcribe_wav(b"second input") == "Astro, merhaba."
        factory.assert_called_once()
        assert model.transcribe.call_args.args[0].read() == b"second input"
        assert model.transcribe.call_args.kwargs["language"] == "tr"
        assert node._last_stt_provider == "faster_whisper"


def test_local_stt_failure_does_not_send_audio_to_cloud(monkeypatch):
    monkeypatch.setenv("STT_ENGINE", "faster-whisper")
    node = bare_node()
    with patch("faster_whisper.WhisperModel", side_effect=RuntimeError("model unavailable")):
        assert not node._transcribe_wav(b"audio")
    node._transcribe_openai.assert_not_called()
    node._transcribe_groq_whisper.assert_not_called()


def test_explicit_runtime_profile_is_loaded_without_project_credentials(tmp_path, monkeypatch):
    profile = tmp_path / "desktop.env"
    profile.write_text("STT_ENGINE=faster-whisper\nUSE_REALTIME=false\n")
    monkeypatch.setenv("ASTRO_ENV_FILE", str(profile))
    monkeypatch.setenv("USE_REALTIME", "true")
    monkeypatch.delenv("STT_ENGINE", raising=False)
    assert _load_env() == str(profile)
    assert os.environ["STT_ENGINE"] == "faster-whisper"
