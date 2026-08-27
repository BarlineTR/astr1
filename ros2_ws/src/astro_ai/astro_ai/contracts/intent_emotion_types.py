"""ASTRO V1 — Intent, Emotion, and Social Enums and Types."""

from enum import Enum


class IntentType(str, Enum):
    GREETING = "GREETING"
    FAREWELL = "FAREWELL"
    QUESTION = "QUESTION"
    REQUEST = "REQUEST"
    COMMAND = "COMMAND"
    STATEMENT = "STATEMENT"
    JOKE = "JOKE"
    SOCIAL_BID = "SOCIAL_BID"
    EMOTIONAL_DISCLOSURE = "EMOTIONAL_DISCLOSURE"
    MEMORY_QUERY = "MEMORY_QUERY"
    MEMORY_UPDATE = "MEMORY_UPDATE"
    CORRECTION = "CORRECTION"
    ATTENTION_SEEKING = "ATTENTION_SEEKING"
    FEEDBACK = "FEEDBACK"
    CONFIRMATION = "CONFIRMATION"
    DENIAL = "DENIAL"
    UNKNOWN = "UNKNOWN"


class EmotionSignal(str, Enum):
    HAPPY = "happy"
    SAD = "sad"
    SURPRISED = "surprised"
    ANGRY = "angry"
    FRUSTRATED = "frustrated"
    CURIOUS = "curious"
    NEUTRAL = "neutral"
    STRESSED = "stressed"


class ConversationPhase(str, Enum):
    UNATTENDED = "UNATTENDED"
    NOTICE_PERSON = "NOTICE_PERSON"
    ORIENTING = "ORIENTING"
    GREETING = "GREETING"
    ENGAGED = "ENGAGED"
    LISTENING = "LISTENING"
    RESPONDING = "RESPONDING"
    PROACTIVE = "PROACTIVE"
    DISENGAGING = "DISENGAGING"
    FAREWELL = "FAREWELL"


class RelationshipRole(str, Enum):
    OWNER = "owner"
    CREATOR = "creator"
    FAMILY = "family"
    FRIEND = "friend"
    REGULAR_GUEST = "regular_guest"
    NEW_USER = "new_user"
    UNKNOWN = "unknown"


class MemorySourceType(str, Enum):
    EXPLICIT_USER_STATEMENT = "explicit_user_statement"
    ROBOT_OBSERVATION = "robot_observation"
    REPEATED_BEHAVIOR = "repeated_behavior"
    TRUSTED_SYSTEM_FACT = "trusted_system_fact"
    THIRD_PARTY_STATEMENT = "third_party_statement"
    UNCERTAIN_INFERENCE = "uncertain_inference"
