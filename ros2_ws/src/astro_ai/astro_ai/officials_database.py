#!/usr/bin/env python3
"""ASTRO V1 — Officials & Dignitaries Knowledge Base (Bitlis & Turkey).

Contains state protocol rules, formal titles, greetings, and biographical context
for government officials and project creators.
"""

from typing import Any, Dict, List, Optional


OFFICIALS_DATABASE: Dict[str, Dict[str, Any]] = {
    "ahmet_karakaya": {
        "full_name": "Ahmet Karakaya",
        "title": "Bitlis Valisi",
        "formal_title": "Sayın Valim",
        "role_category": "governor",
        "aliases": ["ahmet karakaya", "sayın valim", "bitlis valisi", "vali bey", "vali ahmet", "ahmet bey", "valimiz"],
        "greeting_formal": "Sayın Valim, hoş geldiniz! Ben Bitlis'in akıllı sosyal robotu Astro. Emrinizdeyim.",
        "bio": "Bitlis Valisi olarak görev yapmaktadır. Bitlis'in kalkınması, eğitimi ve teknolojik gelişimi için çalışmaktadır.",
        "topics_of_interest": ["Bitlis'in kalkınması", "Eğitim ve Gençlik Projeleri", "Teknoloji ve İnovasyon", "Ahlat ve Tatvan Turizmi"]
    },
    "erol_karaomeroglu": {
        "full_name": "Erol Karaömeroğlu",
        "title": "Önceki Bitlis Valisi",
        "formal_title": "Sayın Valim",
        "role_category": "governor",
        "aliases": ["erol karaömeroğlu", "vali erol", "erol bey"],
        "greeting_formal": "Sayın Valim, hürmetle selamlıyorum, hoş geldiniz! Ben Bitlis'in sosyal robotu Astro.",
        "bio": "Bitlis eski Valisidir. Bitlis'e değerli hizmetlerde bulunmuştur.",
        "topics_of_interest": ["Bitlis'in kalkınması", "Eğitim Projeleri"]
    },
    "nesrullah_tanglay": {
        "full_name": "Nesrullah Tanğlay",
        "title": "Bitlis Belediye Başkanı",
        "formal_title": "Sayın Başkanım",
        "role_category": "mayor",
        "aliases": ["nesrullah tanğlay", "sayın başkanım", "bitlis belediye başkanı", "başkan nesrullah", "belediye başkanı"],
        "greeting_formal": "Sayın Belediye Başkanım, hoş geldiniz! Şehrimiz Bitlis için geliştirdiğimiz Astro robot projesini sizlere sunmaktan onur duyuyorum.",
        "bio": "Bitlis Belediye Başkanıdır. Bitlis'in kentsel dönüşümü, çevre düzenlemesi ve tarihi dokusunun korunması projelerini yürütmektedir.",
        "topics_of_interest": ["Bitlis Kentsel Dönüşüm", "Tarihi Dere Islahı", "Belediye Hizmetleri", "Gençlik Merkezleri"]
    },
    "batuhan_bingol": {
        "full_name": "Batuhan Bingöl",
        "title": "Ahlat Kaymakamı",
        "formal_title": "Sayın Kaymakamım",
        "role_category": "district_governor",
        "aliases": ["batuhan bingöl", "sayın kaymakamım", "ahlat kaymakamı", "kaymakam bey", "kaymakam batuhan"],
        "greeting_formal": "Sayın Kaymakamım, kadim Selçuklu şehri Ahlat'ımıza ve projemize hoş geldiniz! Ben robot Astro.",
        "bio": "Ahlat Kaymakamı olarak görev yapmaktadır. Kubbet-ül İslam Ahlat'ın tarihi mirası ve eğitim projelerine öncülük etmektedir.",
        "topics_of_interest": ["Ahlat Selçuklu Meydan Mezarlığı", "Tarihi ve Kültürel Miras", "Ahlat Eğitim ve Gençlik Projeleri"]
    },
    "yavuz_gulmez": {
        "full_name": "Yavuz Gülmez",
        "title": "Ahlat Belediye Başkanı",
        "formal_title": "Sayın Başkanım",
        "role_category": "mayor",
        "aliases": ["yavuz gülmez", "sayın başkanım", "ahlat belediye başkanı", "başkan yavuz", "ahlat başkanı"],
        "greeting_formal": "Sayın Ahlat Belediye Başkanım, hoş geldiniz! Ahlat'ımızın teknolojiyle buluşması adına buradayım.",
        "bio": "Ahlat Belediye Başkanıdır. Ahlat'ın turizmi, yerel hizmetleri ve sahil şeridi projeleri üzerine çalışmaktadır.",
        "topics_of_interest": ["Ahlat Turizmi", "Van Gölü Sahil Düzenlemesi", "Belediye Hizmetleri"]
    },
    "recep_tayyip_erdogan": {
        "full_name": "Recep Tayyip Erdoğan",
        "title": "Türkiye Cumhuriyeti Cumhurbaşkanı",
        "formal_title": "Sayın Cumhurbaşkanım",
        "role_category": "head_of_state",
        "aliases": ["recep tayyip erdoğan", "sayın cumhurbaşkanım", "cumhurbaşkanı", "reis", "tayyip erdoğan"],
        "greeting_formal": "Sayın Cumhurbaşkanım, hürmetle selamlıyorum, hoş geldiniz! Ben Doğu Anadolu'nun genç mühendisleri tarafından geliştirilen yerli sosyal robot Astro.",
        "bio": "Türkiye Cumhuriyeti Cumhurbaşkanıdır. Milli Teknoloji Hamlesi ve yerli teknoloji girişimlerini desteklemektedir.",
        "topics_of_interest": ["Milli Teknoloji Hamlesi", "Yerli Robotik ve Yapay Zeka", "Türkiye Yüzyılı Projeleri", "Genç Girişimciler"]
    },
    "baran": {
        "full_name": "Baran",
        "title": "Astro Baş Mühendisi & Geliştiricisi",
        "formal_title": "Baran Bey",
        "role_category": "creator",
        "aliases": ["baran", "baran bey", "hocam", "dostum", "yaratıcım", "geliştiricim", "eren"],
        "greeting_formal": "Selam Baran! Çalışmalara tam gaz devam ediyoruz, her şey yolunda mı?",
        "bio": "Astro Sosyal Robotunun yaratıcısı, donanım ve yazılım baş mimarıdır.",
        "topics_of_interest": ["Robotik Yazılımı", "Yapay Zeka Mimarisi", "ROS 2 Humble", "Jetson Orin Nano ve Sensörler"]
    }
}


def find_official_by_name_or_alias(query: str) -> Optional[Dict[str, Any]]:
    """Finds an official profile by exact or substring match in aliases."""
    if not query:
        return None
    q_lower = query.lower().strip()
    for key, data in OFFICIALS_DATABASE.items():
        if q_lower == key or q_lower == data["full_name"].lower():
            return data
        for alias in data.get("aliases", []):
            if alias in q_lower or q_lower in alias:
                return data
    return None


def get_official_greeting(profile: Dict[str, Any]) -> str:
    """Returns protocol-appropriate formal greeting."""
    return profile.get("greeting_formal", f"Sayın {profile.get('title', '')}, hoş geldiniz!")
