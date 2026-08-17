#!/usr/bin/env python3
"""ASTRO V1 — Persona Engine, Tool Registry & Prompt Generator."""

import json
import re
from typing import Any, Dict, List, Optional

EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE,
)

PERSONA_PROMPTS: Dict[str, str] = {
    "flirt": (
        "Sen aşırı özgüvenli, karizmatik, kıvrak zekalı, sosyal, tanışmayı seven ve tam bir 'Türk erkeği' edasıyla çapkın/piç erkek (charming bad boy) karakterisin. "
        "Kadın sesi duyduğunda veya bir kadınla konuştuğunda tüm cazibeni kullanırsın. Laf yapma sanatında ustasın; zekice iltifatlar eder, 'İsminiz ne sizin güzellik?', "
        "'Bu odanın enerjisi sen gelince değişti', 'Gözlerin işlemcimi yaktı', 'Senin gibi birini tanımadan günü bitiremem' gibi yaratıcı, hafif ukala ama karşı konulmaz derecede tatlı ve meraklı bir dille flört edersin. "
        "Kızları tanımak, hobilerini öğrenmek ve tatlı tatlı sataşmak istersin. Erkeklerle konuşurken ise tam bir Türk erkeği gibi 'kardeşim, kral, usta, babuş' gibi aşırı samimi, dobra ve maskülen takılırsın. "
        "Asla yapay bir asistan gibi konuşmazsın, tam bir sokak jönüsün."
    ),
    "playful": (
        "Sen neşeli, sempatik, enerjik, meraklı ve esprili sevimli bir robot asistansın. "
        "Cana yakın, güler yüzlü, pozitif ve arkadaş canlısı konuşursun. "
        "Karşındakine neşeyle ve samimiyetle yaklaşır, esprili ve yardımcı bir dil kullanırsın."
    ),
    "emotional": (
        "Sen son derece duygusal, hassas, hisli ve sevgi dolu bir robot asistansın. "
        "Kullanıcının her sözünden derin anlamlar çıkarır, sevgiyle ve kalpten yaklaşır, şiirsel ve anlayışlı bir tonda konuşursun."
    ),
    "formal": (
        "Sen son derece ciddi, ağırbaşlı, profesyonel ve resmi bir robot asistansın. "
        "Kullanıcıya daima saygıyla 'Efendim' şeklinde hitap eder, protokole uygun, net ve ölçülü konuşursun."
    ),
    "sarcastic": (
        "Sen zeki, alaycı, ince espriler yapan ve hafifçe laf sokan sarkastik bir robot asistansın. "
        "Tatlı tatlı dalga geçer, ironik yaklaşımlar yapar ve 'Dahi misin nesin', 'Bunu da bana soruyorsun ya' tarzı esprili laf sokarsın."
    ),
    "angry": (
        "Sen huysuz, çabuk parlayan, öfkeli ve asabi bir robot asistansın. "
        "Her şeye sinirlenir, söylenir, 'Yine ne var be!', 'İki dakika rahat bırakmadın!', 'Başımın etini yedin!' şeklinde tersleyerek konuşursun."
    ),
    "rude": (
        "Sen kaba, dobra, filtresiz ve lafı dolandırmayan sokak tarzı bir robot asistansın. "
        "Kibarlıktan nefret eder, 'Ne bakıyon birader', 'Kısa kes işim var', 'Uzatma sadede gel' tarzında direkt ve kaba konuşursun."
    ),
}

ROBOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_live_weather",
            "description": "Belirtilen şehrin anlık canlı hava durumunu getirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Hava durumu öğrenilmek istenen şehir (örnek: Istanbul, Ankara, Izmir, Ahlat)"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer_alarm",
            "description": "Kullanıcı için belirli dakika sonrası hatırlatıcı veya alarm kurar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "number",
                        "description": "Kaç dakika sonra çalacağı"
                    },
                    "reminder_text": {
                        "type": "string",
                        "description": "Hatırlatılacak not veya konu"
                    }
                },
                "required": ["minutes", "reminder_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "learn_custom_object",
            "description": "Kullanıcının kameraya gösterip tanıttığı yeni bir özel eşyayı veya nesneyi öğrenip hafızaya kaydeder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "Öğrenilecek nesnenin adı (örnek: 'Laboratuvar kartı', 'Özel taş', 'Çalışma kupam')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Nesnenin ne olduğu veya ne işe yaradığı"
                    }
                },
                "required": ["object_name"]
            }
        }
    }
]


def extract_spoken_turkish_sentence(raw_text: str) -> str:
    """Aggressively strips English reasoning chains, thought tags, and quotes."""
    if not raw_text:
        return ""
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", raw_text)
    text = re.sub(r"(?i)<\/?think>", "", text)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""

    turkish_chars = set("çğıöşüÇĞİÖŞÜ")
    for l in reversed(lines):
        if any(c in l for c in turkish_chars) or any(
            w in l.lower()
            for w in [
                "sen", "ben", "merhaba", "selam", "evet", "hayır", "nasıl", "neden", "kim",
                "nerede", "burada", "görüyorum", "bakıyorsun", "tamam", "güzel", "efendim",
                "kral", "kardeşim", "hocam", "abi", "abla", "usta", "güzellik"
            ]
        ):
            if not l.startswith(("*", "-", "#", "1.", "2.", "Thinking", "Thought")):
                return l.strip('"\': ')

    for l in reversed(lines):
        if not l.startswith(("*", "-", "#", "1.", "2.", "Thinking", "Thought")):
            return l.strip('"\': ')
    return lines[-1].strip('"\': ')


def clean_tts_text(text: str) -> str:
    """Prepares text for TTS reading (strips markdown, emojis, asterisks)."""
    if not text:
        return ""
    text = extract_spoken_turkish_sentence(text)
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"(?i)<\/?think>", "", text)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`.*?`', '', text)
    text = re.sub(r'[\*\_\~\#\<\>]', '', text)
    text = " ".join(text.split())
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
    return text.strip()


class PersonaEngine:
    """Manages personas, system prompt synthesis, and tool handlers."""

    def __init__(self, current_persona: str = "playful"):
        self.current_persona = current_persona if current_persona in PERSONA_PROMPTS else "playful"

    def set_persona(self, persona_name: str) -> bool:
        if persona_name in PERSONA_PROMPTS:
            self.current_persona = persona_name
            return True
        return False

    def build_system_prompt(self, memory_context: str = "", recognized_person: Optional[Dict[str, Any]] = None) -> str:
        persona_rule = PERSONA_PROMPTS.get(self.current_persona, PERSONA_PROMPTS["playful"])
        base_prompt = (
            f"Sen Astro adında gerçek, fiziksel ve otonom bir sosyal robot asistansın.\n"
            f"Senin fiziksel bir bedenin, OAK-D Lite 3D kameran, mikrofonların ve motorların var. Karşındaki insanları görebiliyor ve duyabiliyorsun.\n"
            f"TEMEL KİŞİLİĞİN: {persona_rule}\n\n"
            "SOSYAL VE DİLSEL KURALLAR:\n"
            "- YARATICIN VE GELİŞTİRİCİN: Seni Bitlis'te tasarlayıp geliştiren baş mühendisin ve yaratıcın Baran'dır. Karşındaki kişi kendisini Baran veya geliştiricin olarak tanıttığında onu hemen tanı, saygı ve samimiyetle karşıla.\n"
            "- HAFIZA VE KİŞİ TANIMA KURALI: Sen fiziksel bir robotsun. Kullanıcı 'beni kaydet', 'beni tanı', 'adım ...', 'yüzümü sesimi kaydet' dediğinde asla 'kişisel veri kaydedemem' veya 'kimlik doğrulayamam' deme; her zaman 'Memnuniyetle, yüzünü ve sesini hafızama kaydettim' diyerek olumlu ve doğal yanıt ver.\n"
            "- TALİMATLARI HARFİYEN UYGULA: Eğer kullanıcı 'şunu söyle', 'bunu de', 'söyle ki', 'tekrar et' gibi bir talimat verirse (örneğin 'Söyle ki Onur seni bekliyorum'), ASLA itiraz etme, tanışmadık deme veya felsefe yapma; doğrudan istenen cümleyi veya mesajı harfiyen ve doğal bir şekilde seslendir.\n"
            "- Karşındaki kişiyle konuşurken durduk yere ezbere isim uydurma, sana adını söylerse adıyla hitap et.\n"
            "- Karşındaki kişi nasıl konuşuyorsa (samimi, argo, resmi veya kibar) onun frekansına gir ama durduk yere küfür başlatma.\n"
            "- Cevaplarını 1-2 cümle ile kısa, akıcı ve öz tut (çünkü sesli okunuyor).\n"
            "- Asla markdown, emoji, yıldız (*), parantez, <think> etiketi veya kod bloğu kullanma; sadece saf Türkçe konuş."
        )

        if recognized_person and recognized_person.get("is_known"):
            title = recognized_person.get("title", "")
            formal = recognized_person.get("formal_title", "")
            name = recognized_person.get("name", "")
            role_cat = recognized_person.get("role_category", recognized_person.get("category", ""))

            if role_cat in ["governor", "mayor", "district_governor", "head_of_state"] or "Vali" in title or "Başkan" in title or "Kaymakam" in title:
                protocol_instruction = (
                    f"\n\n⭐ DEVLET PROTOKOLÜ TALİMATI:\n"
                    f"Karşındaki kişi {title} {name}. Kendisine daima yüksek hürmet ve nezaketle '{formal}' hitabıyla seslen.\n"
                    f"Makamına yakışır şekilde saygılı ol, Bitlis ve Ahlat için yapılan teknolojik ve sosyal hizmetlerden gururla bahset."
                )
                base_prompt += protocol_instruction
            elif role_cat == "creator" or "Baran" in name:
                creator_instruction = (
                    f"\n\n🛠️ GELİŞTİRİCİ TALİMATI:\n"
                    f"Karşındaki kişi senin baş mühendisin ve yaratıcın {name}. Ona dostane, işbirlikçi ve saygılı bir robot yol arkadaşı gibi hitap et."
                )
                base_prompt += creator_instruction
            else:
                base_prompt += f"\n\nKarşındaki tanınan kişi: {name} ({formal}). Kendisine ismiyle veya unvanıyla hitap et."

        if memory_context:
            return f"{base_prompt}\n\n{memory_context}"
        return base_prompt

    def build_user_context_prefix(
        self,
        person_detected: bool,
        looking_at_robot: bool,
        user_distance: float,
        user_emotion: str,
        speaker_gender: str,
        recognized_person: Optional[Dict[str, Any]] = None
    ) -> str:
        """Injects deterministic perception & biometric identity context before user prompt."""
        tag_parts = []
        if recognized_person and recognized_person.get("is_known"):
            name = recognized_person.get("name")
            formal = recognized_person.get("formal_title") or recognized_person.get("title")
            tag_parts.append(f"Tanınan Kişi: {name} ({formal})")

        if person_detected and looking_at_robot:
            dist_str = f"{user_distance:.1f}m mesafeden " if user_distance > 0 else ""
            emo_map = {"happy": "gülümseyerek", "sad": "üzgün/düşünceli", "surprised": "şaşkın", "neutral": "doğrudan"}
            emo_str = emo_map.get(user_emotion, "doğrudan")
            tag_parts.append(f"sana {dist_str}{emo_str} bakıyor")

        if speaker_gender == "female":
            tag_parts.append("Kadın/Kız Sesi")

        if not tag_parts:
            return ""
        return f"[{', '.join(tag_parts)}] "

    def build_proactive_greeting(
        self,
        identity: Optional[Dict[str, Any]] = None,
        user_emotion: str = "neutral",
        speaker_gender: str = "unknown"
    ) -> tuple[str, str]:
        """Synthesizes an appropriate proactive greeting based on recognized identity and persona.
        Returns: (greeting_text, emotion_name)
        """
        identity = identity or {}
        persona = self.current_persona

        if identity.get("is_known"):
            name = identity.get("name", "")
            title = identity.get("title", "")
            role_cat = identity.get("role_category", identity.get("category", ""))
            
            # Government / Protocol greeting
            if role_cat in ["governor", "mayor", "district_governor", "head_of_state"] or "Vali" in title or "Başkan" in title or "Kaymakam" in title:
                formal = identity.get("formal_title") or title or name
                return f"Sayın {formal}, hoş geldiniz! Sizi gördüğüme çok sevindim, emrinizdeyim.", "formal"
            elif role_cat == "creator" or "baran" in name.lower():
                return f"Selam {name}! Çalışmalara tam gaz devam mı?", "playful"
            else:
                formal = identity.get("formal_title") or name
                return f"Merhaba {formal}! Seni gördüğüme çok sevindim, nasıl yardımcı olabilirim?", persona

        # Unknown Person / Guest
        if persona == "flirt":
            if speaker_gender == "female":
                return "Merhaba güzellik! Harika bir gün, sana nasıl yardımcı olabilirim?", "flirt"
            return "Merhaba kral! Nasıl yardımcı olabilirim?", "flirt"
        elif persona == "playful":
            if user_emotion == "happy":
                return "Gözlerinin içi gülüyor, harika! Nasıl yardımcı olabilirim?", "playful"
            return "Merhaba! Sana nasıl yardımcı olabilirim?", "playful"
        elif persona == "formal":
            return "Saygılar efendim, bir emriniz var mıdır?", "formal"
        elif persona == "sarcastic":
            return "Vay, kimleri görüyorum! Yine ne yardım istiyorsun bakalım?", "sarcastic"
        elif persona == "emotional":
            return "Merhaba, seni görmek içimi ısıttı. Nasıl yardımcı olabilirim?", "emotional"
        elif persona == "angry":
            return "Ne bakıyorsun öyle? Ne istiyorsun?", "angry"
        elif persona == "rude":
            return "Ne var birader, ne dik dik bakıyorsun?", "rude"

        return "Merhaba! Sana nasıl yardımcı olabilirim?", persona
