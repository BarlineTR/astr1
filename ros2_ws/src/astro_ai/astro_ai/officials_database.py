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
    "cevdet_yilmaz": {
        "full_name": "Cevdet Yılmaz",
        "title": "Cumhurbaşkanı Yardımcısı",
        "formal_title": "Sayın Cumhurbaşkanı Yardımcım",
        "role_category": "vice_president",
        "aliases": ["cevdet yılmaz", "sayın cumhurbaşkanı yardımcım", "cumhurbaşkanı yardımcısı", "cevdet bey"],
        "greeting_formal": "Sayın Cumhurbaşkanı Yardımcım, hoş geldiniz! Bölgemizin kalkınması ve teknoloji hamlemiz adına geliştirdiğimiz sosyal robot Astro emrinizdedir.",
        "bio": "Türkiye Cumhuriyeti Cumhurbaşkanı Yardımcısıdır. Kalkınma ve ekonomik koordinasyonu yürütmektedir.",
        "topics_of_interest": ["Bölgesel Kalkınma", "Ekonomi ve Yatırım", "Doğu Anadolu Projeleri"]
    },
    "hakan_fidan": {
        "full_name": "Hakan Fidan",
        "title": "Dışişleri Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["hakan fidan", "sayın bakanım", "dışişleri bakanı", "hakan bey"],
        "greeting_formal": "Sayın Bakanım, hürmetle selamlıyorum, hoş geldiniz! Ben Türkiye'nin yerli yapay zekalı sosyal robotu Astro.",
        "bio": "Türkiye Cumhuriyeti Dışişleri Bakanıdır. Türk dış politikasını ve milli stratejileri yönetmektedir.",
        "topics_of_interest": ["Dış Politika", "Milli Güvenlik ve Diplomasi", "Küresel Teknoloji Vizyonu"]
    },
    "ali_yerlikaya": {
        "full_name": "Ali Yerlikaya",
        "title": "İçişleri Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["ali yerlikaya", "sayın bakanım", "içişleri bakanı", "ali bey"],
        "greeting_formal": "Sayın Bakanım, milletimizin huzur ve güvenliğinin teminatı olan İçişleri Bakanlığımıza ve şahsınıza hürmetlerimi sunuyorum, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti İçişleri Bakanıdır. Kamu düzeni, güvenlik ve yerel idareleri koordine etmektedir.",
        "topics_of_interest": ["Kamu Düzeni ve Güvenlik", "Şehir Güvenliği Teknolojileri", "Afet Yönetimi"]
    },
    "yasar_guler": {
        "full_name": "Yaşar Güler",
        "title": "Milli Savunma Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["yaşar güler", "sayın bakanım", "milli savunma bakanı", "yaşar paşa"],
        "greeting_formal": "Sayın Bakanım, kahraman ordumuzun ve savunma sanayimizin gücüyle gurur duyuyoruz, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Milli Savunma Bakanıdır.",
        "topics_of_interest": ["Milli Savunma", "Savunma Sanayii", "Sınır Güvenliği ve İleri Teknoloji"]
    },
    "mehmet_simsek": {
        "full_name": "Mehmet Şimşek",
        "title": "Hazine ve Maliye Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["mehmet şimşek", "sayın bakanım", "maliye bakanı", "mehmet bey"],
        "greeting_formal": "Sayın Bakanım, hoş geldiniz! Ülkemizin katma değerli yüksek teknoloji üretimine katkı sağlamak üzere geliştirilen robot Astro emrinizdedir.",
        "bio": "Türkiye Cumhuriyeti Hazine ve Maliye Bakanıdır.",
        "topics_of_interest": ["Katma Değerli Üretim", "Ekonomik Reformlar", "Teknoloji Yatırımları"]
    },
    "mehmet_fatih_kacir": {
        "full_name": "Mehmet Fatih Kacır",
        "title": "Sanayi ve Teknoloji Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["mehmet fatih kaçır", "mehmet fatih kacır", "fatih kacır", "sayın bakanım", "sanayi bakanı", "teknoloji bakanı"],
        "greeting_formal": "Sayın Bakanım, Milli Teknoloji Hamlesi meşalesinin ışığında Doğu Anadolu'da geliştirilen sosyal robot Astro olarak sizleri selamlamaktan büyük gurur duyuyorum!",
        "bio": "Türkiye Cumhuriyeti Sanayi ve Teknoloji Bakanıdır. Milli Teknoloji Hamlesi, yapay zeka stratejileri ve TEKNOFEST girişimlerinin öncüsüdür.",
        "topics_of_interest": ["Milli Teknoloji Hamlesi", "Yerli Robotik ve Otonomi", "Yapay Zeka Stratejisi", "TEKNOFEST ve Genç Girişimcilik"]
    },
    "yilmaz_tunc": {
        "full_name": "Yılmaz Tunç",
        "title": "Adalet Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["yılmaz tunç", "sayın bakanım", "adalet bakanı"],
        "greeting_formal": "Sayın Bakanım, hürmetle selamlıyorum, hoş geldiniz! Ben robot Astro.",
        "bio": "Türkiye Cumhuriyeti Adalet Bakanıdır.",
        "topics_of_interest": ["Hukuk ve Adalet Reformları", "Yargıda Bilişim ve Yapay Zeka"]
    },
    "yusuf_tekin": {
        "full_name": "Yusuf Tekin",
        "title": "Milli Eğitim Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["yusuf tekin", "sayın bakanım", "milli eğitim bakanı", "eğitim bakanı"],
        "greeting_formal": "Sayın Bakanım, gençlerimize ilham olmak ve okullarımızda robotik vizyonunu güçlendirmek adına buradayım, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Milli Eğitim Bakanıdır. Türkiye Yüzyılı Maarif Modeli ve teknoloji destekli eğitimi yönetmektedir.",
        "topics_of_interest": ["Robotik ve Kodlama Eğitimi", "Genç Yetenekler", "Eğitim Teknolojileri"]
    },
    "kemal_memisoglu": {
        "full_name": "Kemal Memişoğlu",
        "title": "Sağlık Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["kemal memişoğlu", "sayın bakanım", "sağlık bakanı"],
        "greeting_formal": "Sayın Bakanım, sağlık ordumuzun ve bakanlığımızın nezdinde şahsınızı hürmetle selamlıyorum, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Sağlık Bakanıdır.",
        "topics_of_interest": ["Sağlıkta Yapay Zeka ve Robotik", "Şehir Hastaneleri", "Koruyucu Sağlık"]
    },
    "abdulkadir_uraloglu": {
        "full_name": "Abdulkadir Uraloğlu",
        "title": "Ulaştırma ve Altyapı Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["abdulkadir uraloğlu", "sayın bakanım", "ulaştırma bakanı"],
        "greeting_formal": "Sayın Bakanım, ülkemizin dijital ve fiziksel altyapı atılımlarını gururla takip ediyoruz, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Ulaştırma ve Altyapı Bakanıdır.",
        "topics_of_interest": ["Akıllı Ulaşım Sistemleri", "5G ve Fiber Altyapı", "Siber Güvenlik"]
    },
    "alparslan_bayraktar": {
        "full_name": "Alparslan Bayraktar",
        "title": "Enerji ve Tabii Kaynaklar Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["alparslan bayraktar", "sayın bakanım", "enerji bakanı"],
        "greeting_formal": "Sayın Bakanım, milli enerji ve teknoloji hedeflerimiz doğrultusunda sizleri selamlıyorum, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Enerji ve Tabii Kaynaklar Bakanıdır.",
        "topics_of_interest": ["Yenilenebilir Enerji", "Milli Madencilik ve Enerji Bağımsızlığı"]
    },
    "ibrahim_yumakli": {
        "full_name": "İbrahim Yumaklı",
        "title": "Tarım ve Orman Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["ibrahim yumaklı", "sayın bakanım", "tarım bakanı"],
        "greeting_formal": "Sayın Bakanım, verimli topraklarımız ve tarım teknolojilerimiz adına hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Tarım ve Orman Bakanıdır.",
        "topics_of_interest": ["Akıllı Tarım ve Robotik", "Su Verimliliği", "Orman Koruma"]
    },
    "murat_kurum": {
        "full_name": "Murat Kurum",
        "title": "Çevre, Şehircilik ve İklim Değişikliği Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["murat kurum", "sayın bakanım", "çevre bakanı", "şehircilik bakanı"],
        "greeting_formal": "Sayın Bakanım, dirençli ve akıllı şehirler vizyonumuzla sizleri hürmetle karşılıyorum, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Çevre, Şehircilik ve İklim Değişikliği Bakanıdır.",
        "topics_of_interest": ["Akıllı ve Dirençli Şehirler", "Sıfır Atık", "Kentsel Dönüşüm"]
    },
    "mehmet_nuri_ersoy": {
        "full_name": "Mehmet Nuri Ersoy",
        "title": "Kültür ve Turizm Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["mehmet nuri ersoy", "sayın bakanım", "kültür bakanı", "turizm bakanı"],
        "greeting_formal": "Sayın Bakanım, Selçuklu mirası Ahlat ve kadim Bitlis'imizin kültürel zenginlikleri adına hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Kültür ve Turizm Bakanıdır.",
        "topics_of_interest": ["Ahlat Selçuklu Mirası", "Kültür Yolu Festivalleri", "Dijital Müzecilik"]
    },
    "mahinur_ozdemir_goktas": {
        "full_name": "Mahinur Özdemir Göktaş",
        "title": "Aile ve Sosyal Hizmetler Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["mahinur özdemir göktaş", "mahinur özdemir", "sayın bakanım", "aile bakanı"],
        "greeting_formal": "Sayın Bakanım, sosyal dayanışma ve aile odaklı hizmetleriniz adına sizleri hürmetle karşılıyorum, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Aile ve Sosyal Hizmetler Bakanıdır.",
        "topics_of_interest": ["Sosyal Yardım Teknolojileri", "Engelli ve Yaşlı Bakım Robotları", "Aile Destekleri"]
    },
    "osman_askin_bak": {
        "full_name": "Osman Aşkın Bak",
        "title": "Gençlik ve Spor Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["osman aşkın bak", "sayın bakanım", "gençlik bakanı", "spor bakanı"],
        "greeting_formal": "Sayın Bakanım, Türk gençliğinin bilim ve teknolojiye olan tutkusuyla sizleri selamlıyorum, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Gençlik ve Spor Bakanıdır.",
        "topics_of_interest": ["Gençlik Merkezleri ve Kodlama", "Spor Teknolojileri", "Girişimci Gençler"]
    },
    "vedat_isikhan": {
        "full_name": "Vedat Işıkhan",
        "title": "Çalışma ve Sosyal Güvenlik Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["vedat ışıkhan", "sayın bakanım", "çalışma bakanı"],
        "greeting_formal": "Sayın Bakanım, hürmetle selamlıyorum, hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Çalışma ve Sosyal Güvenlik Bakanıdır.",
        "topics_of_interest": ["Geleceğin Meslekleri", "Nitelikli İşgücü ve İstihdam"]
    },
    "omer_bolat": {
        "full_name": "Ömer Bolat",
        "title": "Ticaret Bakanı",
        "formal_title": "Sayın Bakanım",
        "role_category": "minister",
        "aliases": ["ömer bolat", "sayın bakanım", "ticaret bakanı"],
        "greeting_formal": "Sayın Bakanım, yerli teknoloji ihracatımız ve güçlü ticaretimiz adına hoş geldiniz!",
        "bio": "Türkiye Cumhuriyeti Ticaret Bakanıdır.",
        "topics_of_interest": ["Yüksek Teknoloji İhracatı", "E-Ticaret ve Dijital Gümrük"]
    },
    "selcuk_bayraktar": {
        "full_name": "Selçuk Bayraktar",
        "title": "T3 Vakfı Mütevelli Heyeti Başkanı & Baykar Yönetim Kurulu Başkanı",
        "formal_title": "Selçuk Bey",
        "role_category": "creator",
        "aliases": ["selçuk bayraktar", "selçuk bey", "selcuk bayraktar", "bayraktar"],
        "greeting_formal": "Selçuk Bey, hoş geldiniz! Milli Teknoloji Hamlesi ve TEKNOFEST vizyonunuzla yetişen genç mühendislerin geliştirdiği sosyal robot Astro emrinizdedir!",
        "bio": "Milli Teknoloji Hamlesi ve TEKNOFEST'in lideri, Baykar Yönetim Kurulu Başkanı ve T3 Vakfı Mütevelli Heyeti Başkanıdır.",
        "topics_of_interest": ["Milli Teknoloji Hamlesi", "İnsansız Sistemler ve Havacılık", "Yapay Zeka ve Robotik", "TEKNOFEST"]
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
