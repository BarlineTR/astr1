"""ASTRO V1 — Categorized Tool Registry."""

from enum import Enum
from typing import Any, Dict, List


class ToolCategory(str, Enum):
    PERCEPTION = "Perception"
    MEMORY = "Memory"
    SOCIAL = "Social"
    ENVIRONMENT = "Environment"
    ROBOT = "Robot"
    UTILITY = "Utility"
    OFFICE = "Office"


class ToolRegistry:
    """Provides categorized tool schemas for LLM tool calling."""

    SCHEMAS: List[Dict[str, Any]] = [
        # Perception
        {
            "category": ToolCategory.PERCEPTION,
            "type": "function",
            "function": {
                "name": "inspect_camera_view",
                "description": "Kameranın gördüğü ortamı veya eldeki nesneyi detaylı analiz eder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "focus": {"type": "string", "description": "Odaklanılacak nesne veya detay"}
                    },
                    "required": ["focus"]
                }
            }
        },
        # Memory
        {
            "category": ToolCategory.MEMORY,
            "type": "function",
            "function": {
                "name": "save_user_memory",
                "description": "Kullanıcının tercihlerini ve bilgilerini hafızaya kaydeder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Bilgi kategorisi (ör: favorite_team, coffee)"},
                        "value": {"type": "string", "description": "Değer (ör: Galatasaray, sütsüz)"}
                    },
                    "required": ["key", "value"]
                }
            }
        },
        {
            "category": ToolCategory.MEMORY,
            "type": "function",
            "function": {
                "name": "recall_user_memory",
                "description": "Kişi hakkında hafızada kayıtlı bilgileri sorgular.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Sorgulanan kişinin adı"}
                    },
                    "required": ["name"]
                }
            }
        },
        # Social & Persona
        {
            "category": ToolCategory.SOCIAL,
            "type": "function",
            "function": {
                "name": "change_persona",
                "description": "Robotun konuşma üslubunu ve kişiliğini değiştirir.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "persona": {"type": "string", "description": "Yeni kişilik (playful, formal, sarcastic, kufurbaz vb.)"}
                    },
                    "required": ["persona"]
                }
            }
        },
        # Environment
        {
            "category": ToolCategory.ENVIRONMENT,
            "type": "function",
            "function": {
                "name": "get_live_weather",
                "description": "Belirtilen şehrin güncel hava durumunu getirir.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "Şehir adı (ör: Bitlis, Ahlat, Istanbul)"}
                    },
                    "required": ["city"]
                }
            }
        },
        # Utility
        {
            "category": ToolCategory.UTILITY,
            "type": "function",
            "function": {
                "name": "set_reminder",
                "description": "Kullanıcı için belirli dakika sonrası hatırlatıcı kurar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "minutes": {"type": "number", "description": "Kaç dakika sonra çalacağı"},
                        "topic": {"type": "string", "description": "Hatırlatılacak konu"}
                    },
                    "required": ["minutes", "topic"]
                }
            }
        },
        # Robot Physical Movement
        {
            "category": ToolCategory.ROBOT,
            "type": "function",
            "function": {
                "name": "turn_to_sound",
                "description": "Kullanıcı 'sesimin geldiği yöne dön', 'bana dön', 'sesime bak' dediğinde çağrılır. Mikrofon dizisinden (DOA) sesin gerçek yönünü tespit edip döner.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "category": ToolCategory.ROBOT,
            "type": "function",
            "function": {
                "name": "move_robot",
                "description": "Kullanıcı doğrudan belirli bir yöne gitmesini istediğinde çağrılır ('ileri git', 'geri gel', 'dur', 'sağa dön', 'sola dön'). DİKKAT: 'sesime dön' için turn_to_sound çağrılır.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["forward", "backward", "left", "right", "stop"],
                            "description": "Hareket yönü"
                        },
                        "speed": {"type": "number", "description": "Hız (0.1 - 0.4 m/s)"},
                        "duration": {"type": "number", "description": "Kaç saniye hareket edeceği"}
                    },
                    "required": ["direction"]
                }
            }
        },
        # Office & Calendar
        {
            "category": ToolCategory.OFFICE,
            "type": "function",
            "function": {
                "name": "check_calendar_events",
                "description": "Kullanıcının bugünkü veya belirli bir zaman aralığındaki takvim programını ve toplantılarını sorgular.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Zaman aralığı veya konu (örn: bugün, bu hafta)"},
                        "days": {"type": "number", "description": "Kaç günlük takvimin sorgulanacağı"}
                    },
                    "required": []
                }
            }
        },
        {
            "category": ToolCategory.OFFICE,
            "type": "function",
            "function": {
                "name": "add_calendar_event",
                "description": "Takvime yeni bir toplantı veya etkinlik ekler.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Toplantı başlığı"},
                        "date": {"type": "string", "description": "Tarih veya gün (örn: yarın, salı)"},
                        "time": {"type": "string", "description": "Saat (örn: 14:00)"},
                        "duration_minutes": {"type": "number", "description": "Süre (dakika)"},
                        "location": {"type": "string", "description": "Konum veya oda"}
                    },
                    "required": ["title"]
                }
            }
        },
        {
            "category": ToolCategory.OFFICE,
            "type": "function",
            "function": {
                "name": "update_calendar_event",
                "description": "Takvimdeki mevcut bir toplantının saatini, gününü veya yerini günceller.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Güncellenecek toplantının adı"},
                        "new_date": {"type": "string", "description": "Yeni tarih veya gün"},
                        "new_time": {"type": "string", "description": "Yeni saat"},
                        "new_location": {"type": "string", "description": "Yeni konum"},
                        "new_title": {"type": "string", "description": "Yeni başlık"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "category": ToolCategory.OFFICE,
            "type": "function",
            "function": {
                "name": "delete_calendar_event",
                "description": "Takvimdeki bir toplantıyı veya randevuyu siler.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "İptal edilecek toplantı adı"}
                    },
                    "required": ["query"]
                }
            }
        },
    ]

    @classmethod
    def get_openai_tools(cls) -> List[Dict[str, Any]]:
        """Returns standard OpenAPI/OpenAI tool definitions without internal metadata."""
        return [
            {"type": t["type"], "function": t["function"]}
            for t in cls.SCHEMAS
        ]
