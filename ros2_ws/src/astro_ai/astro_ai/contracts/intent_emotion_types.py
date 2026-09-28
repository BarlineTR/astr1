"""ASTRO V1 — Intent, Emotion, and Social Enums and Types."""

from enum import Enum


class IntentType(str, Enum):
    GREETING = "GREETING"
    FAREWELL = "FAREWELL"
    QUESTION = "QUESTION"
    DIALOGUE_QUESTION = "DIALOGUE_QUESTION"
    REQUEST = "REQUEST"
    COMMAND = "COMMAND"
    STATEMENT = "STATEMENT"
    JOKE = "JOKE"
    SOCIAL_BID = "SOCIAL_BID"
    EMOTIONAL_DISCLOSURE = "EMOTIONAL_DISCLOSURE"
    MEMORY_QUERY = "MEMORY_QUERY"
    MEMORY_UPDATE = "MEMORY_UPDATE"
    ACTIVITY_QUERY = "ACTIVITY_QUERY"
    VISUAL_STATE_QUERY = "VISUAL_STATE_QUERY"
    MOTION_COMMAND = "MOTION_COMMAND"
    TURN_TO_SOUND_COMMAND = "TURN_TO_SOUND_COMMAND"
    SELF_REFERENCE = "SELF_REFERENCE"
    CORRECTION = "CORRECTION"
    ATTENTION_SEEKING = "ATTENTION_SEEKING"
    FEEDBACK = "FEEDBACK"
    CONFIRMATION = "CONFIRMATION"
    DENIAL = "DENIAL"
    UNKNOWN = "UNKNOWN"

    def __call__(self, arg=None):
        if arg:
            return f"{self.value}({arg})"
        return self.value


class SemanticIntent(str):
    """Rich semantic intent string that equals both its IntentType and its parametric form (e.g. MOTION_COMMAND(stop))."""

    def __new__(cls, base_intent: IntentType, param=None):
        val = str(base_intent.value)
        obj = str.__new__(cls, val)
        obj.intent_type = base_intent
        obj.param = param
        return obj

    def __eq__(self, other):
        if isinstance(other, IntentType):
            return self.intent_type == other
        if isinstance(other, str):
            if self.param and other == f"{self.intent_type.value}({self.param})":
                return True
            return str(self) == other or self.intent_type.value == other
        return super().__eq__(other)

    def __hash__(self):
        return hash(self.intent_type)

    def __str__(self):
        if self.param:
            return f"{self.intent_type.value}({self.param})"
        return self.intent_type.value

    def __repr__(self):
        if self.param:
            return f"{self.intent_type.value}({self.param})"
        return self.intent_type.value

    @property
    def value(self):
        if self.param:
            return f"{self.intent_type.value}({self.param})"
        return self.intent_type.value

    @property
    def direction(self):
        return self.param



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
