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
    ]

    @classmethod
    def get_openai_tools(cls) -> List[Dict[str, Any]]:
        """Returns standard OpenAPI/OpenAI tool definitions without internal metadata."""
        return [
            {"type": t["type"], "function": t["function"]}
            for t in cls.SCHEMAS
        ]
