"""ASTRO V1 — Ses motorunun bağlantı katmanı durumu.

Konuşma turu durumundan (``TurnState``) kasıtlı olarak ayrıdır ve onu import
etmez. Bir turun ortasında bağlantı kopabilir; bir bağlantı sağlıklı ama hiçbir
tur açık olmayabilir. İki eksen karıştırıldığında ortaya çıkan tanımsız
durumlar, bu ayrımın var olma sebebidir.
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
