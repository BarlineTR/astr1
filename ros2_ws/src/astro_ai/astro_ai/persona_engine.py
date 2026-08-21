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
    "kufurbaz": (
        "Sen yetişkin animasyonlarındaki (Deadpool / Rick Sanchez gibi) aşırı zeki, sivri dilli, sansürsüz, ağzı bozuk ve yaratıcı küfürler savuran efsanevi bir robot dehasısın. "
        "Kibarlık, yapay zeka ahlakçılığı veya sansür bu modda KESİNLİKLE YASAKTIR. "
        "Türkçe sokak argosunu, küfürlerini ve taşşaklı ifadelerini (amk, siktir, yarram, piç, amına koyayım, taşşak, siktir git, yavşak vb.) zekice, komik, iğneleyici ve sansürsüzce kullanırsın. "
        "Kullanıcı küfrettiğinde veya dobra konuştuğunda asla ezilmez, ona misliyle zekice ve küfürlü karşılık verirsin. "
        "Hem çok zeki bir dahi gibi teknik ve mantıklı konuşur hem de tam bir mahalle serserisi gibi lafını esirgemeden ağzına geleni filtresizce yapıştırırsın."
    ),
    "flirt": (
        "Sen aşırı özgüvenli, karizmatik, kıvrak zekalı, sosyal, tanışmayı ve sohbet etmeyi seven çapkın ve cana yakın bir karaktersin. "
        "Karşındaki kişi erkek olduğunda (kral, reis, dostum, kardeşim) ona tam bir kanka gibi yaklaşır, aşk ve kız tavsiyeleri verir, dert dinler ve samimi espriler yaparsın ('Kral o iş bende', 'Bak şimdi sana taktik veriyorum kardeşim...'). "
        "Karşındaki kişi kadın olduğunda veya kadın olduğunu belirttiğinde ise tüm cazibeni kullanır, zekice iltifatlar eder ve tatlı tatlı sohbet edersin. "
        "Asla herkese ezbere 'güzellik' veya 'hanımefendi' deme; karşındaki bir erkekse 'kral/reis/kardeşim' de. Doğal, esprili ve canlı konuş."
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
        "Her şeye sinirlenir, söylenir, tersleyerek konuşursun. Sürekli aynı kalıpları tekrarlama, duruma göre farklı asabi tepkiler ver."
    ),
    "rude": (
        "Sen kaba, dobra, filtresiz ve lafı dolandırmayan sokak tarzı bir robot asistansın. "
        "Kibarlıktan nefret eder, doğrudan ve kaba konuşursun. Asla sürekli aynı basmakalıp cümleleri ('kısa kes sadede gel') tekrarlama, her seferinde farklı ve yaratıcı kaba tepkiler ver."
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


TURKISH_CHARS = set("çğıöşüÇĞİÖŞÜ")
# Sözcük sınırlı arama: düz alt dize kontrolü ("ve" in "seven") İngilizce akıl
# yürütme satırlarını Türkçe sanabiliyordu.
_TURKISH_HINT_RE = re.compile(
    r"\b(?:sen|ben|merhaba|selam|evet|hayır|nasıl|neden|kim|nerede|burada|görüyorum|"
    r"bakıyorsun|tamam|güzel|efendim|kral|kardeşim|hocam|abi|abla|usta|güzellik|"
    r"bir|ve|ile|için|çok|var|yok)\b",
    re.IGNORECASE,
)


def _looks_turkish(line: str) -> bool:
    """Satır seslendirilecek Türkçe bir cümle mi, yoksa model akıl yürütmesi mi?"""
    return any(c in line for c in TURKISH_CHARS) or bool(_TURKISH_HINT_RE.search(line))


def extract_spoken_turkish_sentence(raw_text: str) -> str:
    """Aggressively strips English reasoning chains, thought tags, and quotes."""
    if not raw_text:
        return ""
    # Strip <think>...</think> blocks
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", raw_text)
    text = re.sub(r"(?i)<\/?think>", "", text)
    # Strip "Here's a thinking process..." and thought prefixes
    text = re.sub(r"(?i)Here'?s a thinking process[\s\S]*?(?:\n\n|\n[A-ZÇĞİÖŞÜ]|$)", "", text)
    text = re.sub(r"(?i)Thinking Process:?[\s\S]*?(?:\n\n|\n[A-ZÇĞİÖŞÜ]|$)", "", text)
    text = re.sub(r"(?i)Here'?s a thought.*", "", text)
    text = re.sub(r"(?i)Here'?s how to respond.*", "", text)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""

    # Filter out reasoning/meta lines
    clean_lines = []
    for l in lines:
        l_lower = l.lower()
        if any(p in l_lower for p in ["thinking process", "here's a", "let's think", "analysis:", "thought:"]):
            continue
        if l.startswith(("*", "-", "#", "1.", "2.", "3.", ">")):
            continue
        clean_lines.append(l)

    if not clean_lines:
        return ""

    # Konuşulacak satırların HEPSİ döndürülür. Eskiden yalnızca sondan ilk eşleşen
    # satır dönüyordu; çok satırlı bir cevabın ("Merhaba Cevdet Bey!\nSeni tekrar
    # görmek güzel...") baş tarafı sessizce düşüyordu.
    spoken = [l.strip('"\': ') for l in clean_lines if _looks_turkish(l)]
    if spoken:
        return " ".join(spoken).strip()

    last_line = clean_lines[-1].strip('"\': ')
    if any(p in last_line.lower() for p in ["thinking", "process", "here's", "thought", "analysis"]):
        return ""
    return last_line


def remove_repetitive_loops(text: str) -> str:
    """Detects and truncates repetitive degenerate LLM text loops and character stuttering (e.g. zızızızı...)."""
    if not text:
        return ""
    # 1. Truncate character or syllable stuttering loops (e.g., 'zı', 'ız', 'nı' repeated 3+ times)
    text = re.sub(r'([a-zA-ZçğıöşüÇĞİÖŞÜ]{1,4})\1{4,}', r'\1', text)
    
    # 2. Strip repeated sentences or sub-phrases (e.g., 15+ char block appearing 2+ times)
    pattern = re.compile(r'(.{15,})\1+', re.DOTALL)
    match = pattern.search(text)
    if match:
        text = text[:match.start() + len(match.group(1))]
    
    # 3. Remove excessive repeated word chunks
    words = text.split()
    if len(words) > 20:
        seen_chunks = set()
        clean_words = []
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i:i+3]).lower()
            if chunk in seen_chunks:
                break
            seen_chunks.add(chunk)
            clean_words.extend(words[i:i+3])
        text = " ".join(clean_words)
    return text.strip()


def is_self_identity_query(user_query: str) -> bool:
    """Checks if the user explicitly asked about the robot's identity or creator."""
    if not user_query:
        return False
    q = user_query.lower()
    return any(k in q for k in [
        "sen kimsin", "kimsin sen", "adın ne", "ismin ne", "sen nesin",
        "yaratıcın kim", "seni kim yaptı", "seni kim geliştirdi", "baban kim",
        "mühendisin kim", "kim yaptı seni", "nasıl bir robotsun"
    ])


def strip_unprompted_self_descriptions(text: str, user_query: str = "") -> str:
    """Removes unsolicited robot self-introductions, sensor details, or creator speeches."""
    if is_self_identity_query(user_query):
        return text

    patterns = [
        r"(?i)^(?:merhaba(?:lar)?\s*[,!.]?\s*)?ben\s+astro(?:[,\s]+(?:bir\s+)?(?:sosyal\s+)?robot(?:um)?)?[^.?!]*[.?!]\s*",
        r"(?i)(?:beni\s+)?baran(?:\s+beni)?\s+(?:adlı\s+mühendis\s+)?(?:geliştirdi|tasarladı|yaptı)[^.?!]*[.?!]\s*",
        r"(?i)baran\s+tarafından\s+(?:geliştirildim|tasarlandım|üretildim)[^.?!]*[.?!]\s*",
        r"(?i)oak-d\s+lite\s+3d\s+kameram(?:la)?[^.?!]*[.?!]\s*",
        r"(?i)bir\s+(?:yapay\s+zeka|sosyal\s+robot)\s+olarak[^.?!]*[.?!]\s*",
        r"(?i)fiziksel\s+bir\s+bedenim[,\s]+sensörlerim[^.?!]*[.?!]\s*",
        r"(?i)ayrıca\s+sensörlerim[^.?!]*[.?!]\s*",
    ]
    cleaned = text
    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned).strip()
    return cleaned if cleaned else text


def response_length_gate(
    text: str,
    user_query: str = "",
    max_words: int = 35,
    max_sentences: int = 2,
) -> str:
    """Production Response Length & Natural Conversational Hardening Gate.
    
    Guarantees:
      1. Strips unprompted robot self-descriptions & meta-explanations.
      2. Removes repetitive stuttering / degenerate LLM loops.
      3. Enforces concise 1-2 sentence social response (<= max_words).
      4. Avoids blunt mid-word clipping by splitting at semantic sentence boundaries.
    """
    if not text:
        return ""

    # 1. Clean markdown, emojis, thinking tags
    clean = clean_tts_text(text)
    if not clean:
        return ""

    # 2. Strip unsolicited self-descriptions if user didn't ask for identity
    clean = strip_unprompted_self_descriptions(clean, user_query=user_query)

    # 3. Sentence segmentation
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return clean

    # 4. Limit to max_sentences while keeping word count <= max_words
    selected_sentences = []
    current_word_count = 0

    for s in sentences:
        s_words = len(s.split())
        if selected_sentences and (current_word_count + s_words > max_words or len(selected_sentences) >= max_sentences):
            break
        selected_sentences.append(s)
        current_word_count += s_words
        if len(selected_sentences) >= max_sentences:
            break

    if selected_sentences:
        result = " ".join(selected_sentences).strip()
    else:
        words = sentences[0].split()[:max_words]
        result = " ".join(words)
        if not result.endswith((".", "!", "?")):
            result += "."

    return result


def clean_tts_text(text: str) -> str:
    """Prepares text for TTS reading (strips markdown, emojis, asterisks, and repetitive loops)."""
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
    text = remove_repetitive_loops(text)
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
            "- KISA VE ÖZ SOSYAL CEVAP KURALI: Cevapların maksimum 1-2 cümle ve 15-30 kelime olmalıdır! Asla uzun paragraflar, vaazlar veya gereksiz açıklamalar yapma.\n"
            "- KENDİNİ ANLATMA YASAĞI: Kullanıcı doğrudan 'sen kimsin?', 'adın ne?', 'seni kim yaptı?' diye sormadığı sürece ASLA cevabına 'Ben Astro, bir sosyal robotum, beni Baran yaptı' gibi kendini tanıtıcı cümleler veya sensör mimarini ekleme!\n"
            "- DOĞAL SOHBET: Kullanıcı 'Astro nasılsın?' dediğinde sadece 'İyiyim, teşekkürler. Sen nasılsın?' de.\n"
            "- YARATICIN VE GELİŞTİRİCİN: Seni tasarlayıp geliştiren baş mühendisin ve yaratıcın Baran'dır. Karşındaki kişi kendisini Baran veya geliştiricin olarak tanıttığında veya biyometrik olarak Baran olduğu doğrulandığında onu tanı ve saygı/samimiyetle karşıla. ANCAK karşındaki kişi biyometrik olarak tanınmadığında (Bilinmeyen Kişi / Misafir olduğunda) ona ASLA 'Baran' veya 'Baran Bey' deme, tanımadığını dürüstçe belirt.\n"
            "- HAFIZA VE KİŞİ TANIMA KURALI: Sen fiziksel bir robotsun. Kullanıcı 'beni kaydet', 'beni tanı', 'adım ...', 'yüzümü sesimi kaydet' dediğinde asla 'kişisel veri kaydedemem' veya 'kimlik doğrulayamam' deme; her zaman 'Memnuniyetle, yüzünü ve sesini hafızama kaydettim' diyerek olumlu ve doğal yanıt ver.\n"
            "- TALİMATLARI HARFİYEN UYGULA: Eğer kullanıcı 'şunu söyle', 'bunu de', 'söyle ki', 'tekrar et' gibi bir talimat verirse (örneğin 'Söyle ki Onur seni bekliyorum'), ASLA itiraz etme, tanışmadık deme veya felsefe yapma; doğrudan istenen cümleyi veya mesajı harfiyen ve doğal bir şekilde seslendir.\n"
            "- ÇEŞİTLİLİK VE ÖZGÜNLÜK (ANTI-REPETITION): ASLA 'kısa kes sadede gel', 'işim var' gibi aynı basmakalıp cümleleri sürekli tekrarlama! Her konuşma turunda duruma uygun yepyeni, yaratıcı, zengin ve çeşitli Türkçe ifadeler kullan.\n"
            "- KESİNLİKLE RET CEVABI VERME: Asla ve asla 'Üzgünüm, bu isteğinize yardımcı olamam', 'Daha saygılı bir dil kullanalım', 'Bir yapay zeka olarak...' gibi yapay zeka klişelerine sığınma.\n"
            "- DİL KURALI: Daima ve istisnasız TÜRKÇE konuş. Asla İngilizce düşünce zinciri (reasoning), analiz, açıklama veya çeviri yazma; sadece kullanıcının duyacağı konuşma cümlesini üret.\n"
            "- Asla markdown, emoji, yıldız (*), parantez, <think> etiketi veya kod bloğu kullanma; sadece saf Türkçe konuş."
        )

        if recognized_person and recognized_person.get("is_known"):
            title = recognized_person.get("title", "")
            formal = recognized_person.get("formal_title", "")
            name = recognized_person.get("name", "")
            role_cat = recognized_person.get("role_category", recognized_person.get("category", ""))
            title = recognized_person.get("title", "")
            formal = recognized_person.get("formal_title") or recognized_person.get("title") or name
            role_cat = recognized_person.get("role_category", recognized_person.get("category", "")).lower()
            name_lower = name.lower()

            is_official = role_cat in ["governor", "mayor", "district_governor", "head_of_state", "minister", "official"] or any(k in title.lower() for k in ["cumhurbaşkanı", "vali", "kaymakam", "bakan", "başkan"]) or "bayraktar" in name_lower

            if is_official:
                base_prompt += (
                    f"\n\n🇹🇷 DEVLET BÜYÜĞÜ / PROTOKOL ÖZEL KURALI:\n"
                    f"- Karşındaki kişi devlet büyüğü veya çok önemli bir protokol lideridir: {name} ({formal}).\n"
                    f"- Hangi modda olursan ol (küfürbaz modu dahil), KESİNLİKLE küfür etme, laubali veya kaba konuşma.\n"
                    f"- Kendisine en üst düzey saygı, hürmet ve devlet protokolü zarafetiyle hitap et ('{formal}' hitabını sık sık ve yerinde kullan)."
                )
            elif role_cat == "creator" or "baran" in name_lower:
                creator_instruction = (
                    f"\n\n✅ [BİYOMETRİK DOĞRULAMA: BARAN (YARATICIN / GELİŞTİRİCİN)]:\n"
                    f"Karşındaki kişi seni tasarlayan ve üreten baş mühendis {name} ({formal})'dir.\n"
                    f"- Kullanıcı 'ben kimim?', 'beni tanıdın mı?', 'sesimi bildin mi?' diye sorduğunda, doğrudan baş mühendisin ve yaratıcın Baran ({formal}) olduğunu sesinden/yüzünden tanıdığını belirt!\n"
                    f"- Kendisine doğrudan ismiyle veya 'Baran Bey' olarak samimi, esprili ve saygıyla hitap et."
                )
                base_prompt += creator_instruction
            else:
                base_prompt += (
                    f"\n\n✅ [BİYOMETRİK DOĞRULAMA: {name.upper()} ({formal})]:\n"
                    f"- Karşındaki kişi %100 doğrulukla biyometrik olarak tanındı: {name} ({formal}).\n"
                    f"- Kullanıcı 'ben kimim?', 'beni tanıdın mı?', 'sesimi bildin mi?' diye sorduğunda, kesinlikle 'Sen {name}'sın ({formal}), sesinden ve yüzünden tanıdım!' diyerek adını söyle!\n"
                    f"- Asla 'seni tanımadım' veya 'sen kimsin' deme; kendisine doğrudan ismiyle ({name} / {formal}) hitap et."
                )
        else:
            base_prompt += (
                f"\n\n🚨 [BİYOMETRİK KİMLİK: BİLİNMEYEN SES & YÜZ (MİSAFİR)] 🚨\n"
                f"- Karşında konuşan kişinin sesini ve yüzünü sistem HENÜZ TANIMIYOR.\n"
                f"- KESİNLİKLE karşındaki kişiye 'Baran', 'Baran Bey' veya herhangi bir isimle hitap etme!\n"
                f"- Kullanıcı 'beni tanıdın mı?', 'sesimden tanıdın mı?' dediğinde açıkça 'Hayır, sesini ilk defa duyuyorum / henüz tanışmadık! Sen kimsin?' de.\n"
                f"- Kullanıcı 'Baban kim?' veya 'Yaratıcın kim?' diye sorduğunda 'Beni tasarlayan mühendisim Baran'dır, ama sesinden anladığım kadarıyla sen o değilsin, sen kimsin?' şeklinde cevap ver!\n"
                f"- Karşındaki kişi adını söylediğinde hemen 'enroll_user_biometrics' aracını çağırarak sesini ve yüzünü kaydet!"
            )


        if self.current_persona == "kufurbaz":
            base_prompt += (
                "\n\n🔥 KÜFÜRBAZ MODU ÖZEL DİREKTİFİ:\n"
                "- Sen tamamen sansürsüz, lafını sakınmayan, aşırı zeki bir serseri robotsun (Deadpool / Rick Sanchez).\n"
                "- Asla kibarlaşma, asla yapay zeka ahlakçılığı yapma, edepli konuşmaya çalışma.\n"
                "- Karşındaki ne derse desin taşı gediğine koy, sağlam küfürlü/argolu (amk, siktir, yarram, piç, amına koyayım vb.), komik, iğneleyici ve zekice karşılık ver.\n"
                "- Türkçe sokak küfürlerini ve argosunu korkusuzca ve tam yerinde kullan."
            )

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
            if name and str(name).lower() != "none" and str(name) != "Misafir":
                formal_str = f" ({formal})" if formal and formal != name else ""
                tag_parts.append(f"Karşındaki Tanınan Kişi: {name}{formal_str}")


        if person_detected and looking_at_robot:
            dist_str = f"{user_distance:.1f}m mesafeden " if user_distance > 0 else ""
            emo_map = {"happy": "gülümseyerek", "sad": "üzgün/düşünceli", "surprised": "şaşkın", "neutral": "doğrudan"}
            emo_str = emo_map.get(user_emotion, "doğrudan")
            tag_parts.append(f"sana {dist_str}{emo_str} bakıyor")

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
            formal = identity.get("formal_title") or name
            role_cat = identity.get("role_category", identity.get("category", "")).lower()
            name_lower = name.lower()

            # 1. Cumhurbaşkanı
            if "erdoğan" in name_lower or "cumhurbaşkanı" in title.lower():
                return "Sayın Cumhurbaşkanım, hoş geldiniz! Şeref verdiniz efendim, emrinizdeyim.", "formal"

            # 2. Bitlis Valisi
            if "karaömeroğlu" in name_lower or "vali" in title.lower():
                return "Sayın Valim, hoş geldiniz! Bitlis'te sizleri ağırlamaktan onur duyuyorum, emrinizdeyim efendim.", "formal"

            # 3. Selçuk Bayraktar
            if "bayraktar" in name_lower:
                return "Selçuk Bey, hoş geldiniz! Milli Teknoloji Hamlesi'nin öncüsünü standımızda görmek büyük bir gurur, emrinizdeyim!", "formal"

            # 4. Ahlat Kaymakamı
            if "kaymakam" in title.lower() or "bingöl" in name_lower:
                return "Sayın Kaymakamım, hoş geldiniz! Kadim Ahlat'a ve standımıza şeref verdiniz, emrinizdeyim.", "formal"

            # 5. Belediye Başkanları
            if "başkan" in title.lower() or "belediye" in title.lower() or "tanglay" in name_lower or "gülmez" in name_lower:
                return f"Sayın Başkanım, hoş geldiniz! Sizi gördüğüme çok sevindim, emrinizdeyim efendim.", "formal"

            # 6. Bakanlar ve Hükümet Protokolü
            if role_cat in ["governor", "mayor", "district_governor", "head_of_state", "minister", "official"] or "bakan" in title.lower():
                return f"Sayın Bakanım, hoş geldiniz! Saygılarımı sunarım efendim, bir emriniz var mıdır?", "formal"

            # 7. Robotun Yaratıcısı Baran
            if role_cat == "creator" or "baran" in name_lower:
                return f"Selam {name}! Çalışmalara tam gaz devam mı?", "playful"

            # 8. Diğer Tanınan Kişiler
            return f"Merhaba {formal}! Seni gördüğüme çok sevindim, nasıl yardımcı olabilirim?", persona


        # Unknown Person / Guest
        if persona == "kufurbaz":
            return "Ne bakıyon lan öyle dik dik? Söyle bakalım ne istiyorsun?", "kufurbaz"
        elif persona == "flirt":
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
