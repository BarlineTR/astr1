"""ASTRO V1 — Waypoint & Social Navigation Manager.

Manages geographic locations, semantic destination aliases, and welcome/arrival messages
for Office Greeter and Restaurant Host robot modes.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional


def _normalize_text(text: str) -> str:
    """Normalizes Turkish characters and punctuation for robust alias matching."""
    if not text:
        return ""
    t = text.lower().strip()
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    t = t.translate(tr_map)
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


@dataclass
class Waypoint:
    key: str
    name: str
    aliases: List[str]
    x: float
    y: float
    yaw_deg: float
    description: str = ""
    arrival_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "aliases": self.aliases,
            "x": self.x,
            "y": self.y,
            "yaw_deg": self.yaw_deg,
            "description": self.description,
            "arrival_message": self.arrival_message,
        }


DEFAULT_OFFICE_WAYPOINTS = {
    "reception": {
        "name": "Danışma / Karşılama",
        "aliases": ["danisma", "reception", "giris", "karsilama"],
        "x": 0.0,
        "y": 0.0,
        "yaw_deg": 0.0,
        "description": "Ana giriş ve misafir karşılama masası.",
        "arrival_message": "Danışma alanındayız. Size nasıl yardımcı olabilirim?",
    },
    "meeting_room_a": {
        "name": "Toplantı Odası A",
        "aliases": ["toplanti odasi a", "toplanti a", "buyuk toplanti odasi"],
        "x": 4.5,
        "y": 2.0,
        "yaw_deg": 90.0,
        "description": "Büyük konferans ve sunum odası.",
        "arrival_message": "Toplantı Odası A'ya ulaştık. Buyrun lütfen, iyi toplantılar dilerim.",
    },
    "meeting_room_b": {
        "name": "Toplantı Odası B",
        "aliases": ["toplanti odasi b", "toplanti b", "kucuk toplanti odasi"],
        "x": 4.5,
        "y": -2.0,
        "yaw_deg": -90.0,
        "description": "Küçük toplantı ve görüşme odası.",
        "arrival_message": "Toplantı Odası B'ye geldik. Buyrun, verimli bir görüşme dilerim.",
    },
    "kitchen": {
        "name": "Mutfak / Dinlenme Alanı",
        "aliases": ["mutfak", "cay ocagi", "kahve alani", "dinlenme alani"],
        "x": 2.0,
        "y": 3.5,
        "yaw_deg": 180.0,
        "description": "Çay, kahve ve mola alanı.",
        "arrival_message": "Mutfak ve kahve alanına geldik. Afiyet olsun!",
    },
    "waiting_lounge": {
        "name": "Bekleme Salonu",
        "aliases": ["bekleme salonu", "bekleme alani", "lobi", "lounge"],
        "x": 1.5,
        "y": -1.5,
        "yaw_deg": 0.0,
        "description": "Misafir koltukları ve dinlenme köşesi.",
        "arrival_message": "Bekleme salonundayız. Lütfen rahatınıza bakın, ev sahibinize haber veriyorum.",
    },
    "manager_office": {
        "name": "Yönetici Ofisi",
        "aliases": ["yonetici ofisi", "mudur odasi", "baskan odasi"],
        "x": 6.0,
        "y": 0.0,
        "yaw_deg": 0.0,
        "description": "Genel Müdür ve Yönetici Odası.",
        "arrival_message": "Yönetici ofisinin kapısındayız. Buyrun lütfen.",
    },
    "charging_dock": {
        "name": "Şarj İstasyonu",
        "aliases": ["sarj istasyonu", "sarj noktasi", "yuva", "dock"],
        "x": -0.5,
        "y": 0.0,
        "yaw_deg": 180.0,
        "description": "Robot otomatik şarj istasyonu.",
        "arrival_message": "Şarj istasyonuna döndüm. Bekleme moduna geçiyorum.",
    },
}

DEFAULT_RESTAURANT_WAYPOINTS = {
    "entrance": {
        "name": "Restoran Girişi",
        "aliases": ["giris", "kapi", "karsilama", "entrance"],
        "x": 0.0,
        "y": 0.0,
        "yaw_deg": 0.0,
        "description": "Misafir karşılama ve bekleme noktası.",
        "arrival_message": "Giriş karşılama noktasına döndüm. Yeni misafirleri bekliyorum.",
    },
    "table_1": {
        "name": "Masa 1",
        "aliases": ["masa 1", "birinci masa", "1 numarali masa", "table 1", "1"],
        "x": 2.5,
        "y": 1.5,
        "yaw_deg": 45.0,
        "description": "2 kişilik cam kenarı masa.",
        "arrival_message": "Masa 1'e ulaştık. Buyrun lütfen, afiyet olsun!",
    },
    "table_2": {
        "name": "Masa 2",
        "aliases": ["masa 2", "ikinci masa", "2 numarali masa", "table 2", "2"],
        "x": 2.5,
        "y": -1.5,
        "yaw_deg": -45.0,
        "description": "4 kişilik aile masası.",
        "arrival_message": "Masa 2'ye geldik. Buyrun lütfen, keyifli bir yemek dilerim!",
    },
    "table_3": {
        "name": "Masa 3",
        "aliases": ["masa 3", "ucuncu masa", "3 numarali masa", "table 3", "3"],
        "x": 5.0,
        "y": 1.5,
        "yaw_deg": 45.0,
        "description": "6 kişilik geniş grup masası.",
        "arrival_message": "Masa 3'e geldik. Masanız hazır, şimdiden afiyet olsun!",
    },
    "table_4": {
        "name": "Masa 4",
        "aliases": ["masa 4", "dorduncu masa", "4 numarali masa", "table 4", "4"],
        "x": 5.0,
        "y": -1.5,
        "yaw_deg": -45.0,
        "description": "2 kişilik bahçe manzaralı masa.",
        "arrival_message": "Masa 4'e ulaştık. Buyrun lütfen, harika bir akşam dilerim!",
    },
    "bar": {
        "name": "Bar / İçecek Alanı",
        "aliases": ["bar", "icecek bolumu", "kokteyl bari"],
        "x": 3.5,
        "y": 3.0,
        "yaw_deg": 90.0,
        "description": "İçecek ve bar tezgahı.",
        "arrival_message": "Bar alanına geldik. İçecek servisi için barmenimiz size yardımcı olacaktır.",
    },
    "cashier": {
        "name": "Kasa / Ödeme Noktası",
        "aliases": ["kasa", "odeme noktasi", "hesap"],
        "x": 1.0,
        "y": -2.0,
        "yaw_deg": -90.0,
        "description": "Hesap ödeme ve ayrılış noktası.",
        "arrival_message": "Kasaya ulaştık. Bizi tercih ettiğiniz için teşekkür ederiz, yine bekleriz!",
    },
    "kitchen": {
        "name": "Mutfak Servis Çıkışı",
        "aliases": ["mutfak", "servis", "yemek cikisi"],
        "x": 6.0,
        "y": 0.0,
        "yaw_deg": 180.0,
        "description": "Personel ve servis mutfağı.",
        "arrival_message": "Mutfak servis noktasına ulaştım.",
    },
}


class WaypointManager:
    """Authoritative Waypoint and Destination Resolver."""

    def __init__(self, mode: Optional[str] = None, config_path: Optional[str] = None):
        env_mode = os.getenv("ROBOT_MODE", "").lower().strip()
        self.mode = (mode if mode is not None else env_mode).lower().strip()
        self.config_path = config_path
        self.waypoints: Dict[str, Waypoint] = {}
        self.default_home_key: Optional[str] = None
        self._load_waypoints()

    def _find_config_file(self) -> Optional[Path]:
        if self.config_path and Path(self.config_path).exists():
            return Path(self.config_path)

        # Check candidate locations relative to package and repo root
        cur_file = Path(__file__).resolve()
        # Candidate 1: repo_root/config/waypoints_<mode>.json
        repo_root = cur_file.parents[4]  # ros2_ws/src/astro_ai/astro_ai/navigation -> repo
        candidates = [
            repo_root / "config" / f"waypoints_{self.mode}.json",
            Path.cwd() / "config" / f"waypoints_{self.mode}.json",
            Path.home() / ".astro" / f"waypoints_{self.mode}.json",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _load_waypoints(self) -> None:
        self.waypoints.clear()
        cfg_file = self._find_config_file()
        raw_data = None

        if cfg_file is not None:
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            except Exception as e:
                print(f"⚠️ [WaypointManager] Config file {cfg_file} read error: {e}")

        if raw_data is None:
            # Fallback based on mode
            if self.mode == "office":
                raw_data = {"mode": "office", "default_home": "reception", "waypoints": DEFAULT_OFFICE_WAYPOINTS}
            elif self.mode == "restaurant":
                raw_data = {"mode": "restaurant", "default_home": "entrance", "waypoints": DEFAULT_RESTAURANT_WAYPOINTS}
            else:
                raw_data = {"mode": "general", "default_home": None, "waypoints": {}}

        self.default_home_key = raw_data.get("default_home")
        wp_dict = raw_data.get("waypoints", {})

        for key, info in wp_dict.items():
            self.waypoints[key] = Waypoint(
                key=key,
                name=info.get("name", key),
                aliases=info.get("aliases", []),
                x=float(info.get("x", 0.0)),
                y=float(info.get("y", 0.0)),
                yaw_deg=float(info.get("yaw_deg", 0.0)),
                description=info.get("description", ""),
                arrival_message=info.get("arrival_message", f"{info.get('name', key)} noktasına ulaştık."),
            )

    def resolve(self, query: str) -> Optional[Waypoint]:
        """Resolves user query (e.g. 'toplantı odası a', 'masa 2', 'mutfak') to Waypoint."""
        if not query or not self.waypoints:
            return None

        q_norm = _normalize_text(query)

        # 1. Exact match on key
        if query in self.waypoints:
            return self.waypoints[query]
        if q_norm in self.waypoints:
            return self.waypoints[q_norm]

        # 2. Check name and aliases
        for wp in self.waypoints.values():
            if _normalize_text(wp.name) == q_norm:
                return wp
            for alias in wp.aliases:
                if _normalize_text(alias) == q_norm:
                    return wp

        # 3. Substring / Token matching
        for wp in self.waypoints.values():
            wp_name_norm = _normalize_text(wp.name)
            if wp_name_norm in q_norm or q_norm in wp_name_norm:
                return wp
            for alias in wp.aliases:
                alias_norm = _normalize_text(alias)
                if alias_norm in q_norm or q_norm in alias_norm:
                    return wp

        return None

    def get(self, key: str) -> Optional[Waypoint]:
        return self.waypoints.get(key)

    def get_home(self) -> Optional[Waypoint]:
        if self.default_home_key and self.default_home_key in self.waypoints:
            return self.waypoints[self.default_home_key]
        return None

    def list_destinations(self) -> List[Dict[str, Any]]:
        """Returns structured list of available destinations for LLM and user feedback."""
        return [wp.to_dict() for wp in self.waypoints.values()]
