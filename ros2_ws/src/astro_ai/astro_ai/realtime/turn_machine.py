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
        """Gelen audio delta'nın hoparlöre gitmesi gerekip gerekmediği.

        Makine henüz hiç ``response.created`` görmemişse (``generation_id == 0``)
        kapı KAPALIDIR: geçersiz kılınacak bir önceki yanıt yoktur, dolayısıyla
        elenecek bir şey de yoktur. Bu durumda sesi düşürmek, karakterize bile
        edemediğimiz bir desync yüzünden robotu tamamen susturmak olurdu.
        Generation isolation ilk yanıt gözlemlendiği anda devreye girer.
        """
        if self.generation_id == 0:
            return True
        if response_id is None or self.active_response_id is None:
            # Karşılaştıracak kimlik yok: sesin BAYAT olduğunu kanıtlayamayız.
            # Kanıtlanamayan şüphe yüzünden susmak yerine çalıyoruz; gerçek
            # bayatlık zaten durum kontrolüyle (RESPONSE_STREAMING değilse
            # düşür) ve kimlikler mevcutken karşılaştırmayla yakalanır.
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
        if self.state in (TurnState.RESPONSE_PENDING, TurnState.IDLE):
            # IDLE de meşrudur: her yanıt kullanıcı konuşmasını takip etmez.
            # Proaktif selamlama (_trigger_proactive_greeting) ve tool sonrası
            # devam yanıtı istemci tarafından başlatılır; sunucu da kendi
            # inisiyatifiyle yanıt kurabilir. Makinenin işi sunucuyu TAKİP
            # etmektir, ne yapabileceğine karar vermek değil. Bunu yok saymak
            # selamlama boyunca makineyi desync bırakır ve barge-in'i öldürür.
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
        # Hiç yanıt gözlemlenmemişken kapı kapalı — bkz. should_publish_audio.
        if self.generation_id == 0:
            return [Action.PUBLISH_AUDIO]
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
